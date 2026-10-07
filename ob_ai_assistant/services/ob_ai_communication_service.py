import hashlib
import hmac
import json
import secrets
import uuid
from datetime import datetime, timedelta, timezone

from odoo import _, fields, models
from odoo.exceptions import UserError


class OBAICommunicationService(models.AbstractModel):
    _name = "ob.ai.communication.service"
    _description = "AI Communication Service"

    DEFAULT_SCOPES = ["read_context", "read_schema", "request_more_data"]
    ACTION_SCOPE = "execute_actions"
    GATEWAY_DEFAULT_CLOCK_SKEW_SECONDS = 180

    def issue_request_token(self, conversation=False, scopes=None, request_kind="chat_context", ttl_minutes=False):
        conversation = conversation.exists() if conversation else False
        user = conversation.user_id if conversation else self.env.user
        company = conversation.company_id if conversation else (user.company_id or self.env.company)
        schema_version = self.env["ob.ai.schema.service"].ensure_current_schema(trigger_source="conversation" if conversation else "auto")
        access_service = self.env["ob.ai.access.service"].with_user(user).with_company(company)
        templates = access_service.get_user_templates(user=user)
        requested_scopes = list(scopes or self.DEFAULT_SCOPES)
        requested_scopes = [scope for scope in requested_scopes if scope]

        allow_action_scope = self._can_issue_action_scope(user, access_service=access_service, templates=templates)
        auto_action_scope = self._get_bool_param("ob_ai_assistant.gateway_auto_action_scope", True)
        if auto_action_scope and request_kind in {"chat_context", "action_proposal"} and allow_action_scope:
            if self.ACTION_SCOPE not in requested_scopes:
                requested_scopes.append(self.ACTION_SCOPE)
        if self.ACTION_SCOPE in requested_scopes and not allow_action_scope:
            raise UserError(_("You are not allowed to issue gateway tokens with action-execution scope."))

        ttl_minutes = ttl_minutes or max(self._get_int_param("ob_ai_assistant.request_token_ttl_minutes", 15), 1)
        token_value = secrets.token_urlsafe(32)
        token_jti = uuid.uuid4().hex
        token_record = self.env["ob.ai.request.token"].sudo().create({
            "conversation_id": conversation.id if conversation else False,
            "user_id": user.id,
            "company_id": company.id,
            "schema_version_id": schema_version.id if schema_version else False,
            "request_kind": request_kind,
            "token_jti": token_jti,
            "token_hint": token_jti[:8],
            "token_digest": self._token_digest(token_value),
            "scope_json": requested_scopes or list(self.DEFAULT_SCOPES),
            "template_snapshot": {
                "ids": templates.ids,
                "names": templates.mapped("display_name"),
            },
            "template_signature": self._template_signature(templates),
            "expires_at": fields.Datetime.now() + timedelta(minutes=ttl_minutes),
            "max_investigation_steps": max(self._get_int_param("ob_ai_assistant.max_investigation_steps", 3), 1),
            "max_models_per_request": max(self._get_int_param("ob_ai_assistant.max_models_per_request", 6), 1),
            "max_records_per_fetch": max(self._get_int_param("ob_ai_assistant.max_records_per_fetch", 25), 1),
        })
        return {
            "token": token_value,
            "record": token_record,
            "schema_version": schema_version,
        }

    def validate_request_token(self, token_value, required_scope=False, conversation=False, update_usage=True):
        if not token_value:
            raise UserError(_("A secure AI request token is required."))
        token_record = self.env["ob.ai.request.token"].sudo().search([
            ("token_digest", "=", self._token_digest(token_value)),
        ], limit=1)
        if not token_record:
            raise UserError(_("The secure AI request token is invalid."))
        if token_record.state == "revoked":
            raise UserError(_("The secure AI request token has been revoked."))
        if token_record.expires_at and token_record.expires_at <= fields.Datetime.now():
            token_record.write({"state": "expired"})
            raise UserError(_("The secure AI request token has expired."))
        if conversation and token_record.conversation_id != conversation:
            raise UserError(_("The secure AI request token does not belong to this conversation."))
        if required_scope and required_scope not in (token_record.scope_json or []):
            raise UserError(_("The secure AI request token does not allow %s.") % required_scope)
        if update_usage:
            self._register_token_use(token_record)
        return token_record

    def _register_token_use(self, token_record):
        token_record.sudo().write({
            "last_used_at": fields.Datetime.now(),
            "use_count": token_record.use_count + 1,
        })

    def revoke_request_token(self, token_value, reason=False):
        token_record = self.validate_request_token(token_value)
        token_record.write({
            "state": "revoked",
            "revoked_reason": reason or _("Revoked by the AI communication service."),
        })
        return token_record

    def gateway_is_enabled(self):
        return self._get_bool_param("ob_ai_assistant.gateway_enabled", True)

    def prepare_gateway_auth_headers(self, token_value, payload, required_scope, sequence=False, timestamp=False):
        token_record = self.validate_request_token(
            token_value,
            required_scope=required_scope,
            update_usage=False,
        )
        payload_raw = self._canonical_payload(payload)
        timestamp = int(timestamp or self._current_epoch_seconds())
        sequence = int(sequence or (token_record.use_count + 1))
        signature = self._build_gateway_signature(
            token_record,
            required_scope,
            timestamp,
            sequence,
            payload_raw,
        )
        return {
            "Authorization": "Bearer %s" % token_value,
            "X-OB-AI-Timestamp": str(timestamp),
            "X-OB-AI-Sequence": str(sequence),
            "X-OB-AI-Signature": signature,
            "X-OB-AI-Scope": required_scope,
        }

    def validate_signed_gateway_request(self, headers, raw_body, required_scope):
        if not self.gateway_is_enabled():
            raise UserError(_("The AI communication gateway is disabled."))
        token_value = self._extract_gateway_token(headers)
        token_record = self.validate_request_token(
            token_value,
            required_scope=required_scope,
            update_usage=False,
        )
        if not self._get_bool_param("ob_ai_assistant.gateway_require_signature", True):
            self._register_token_use(token_record)
            return token_record
        timestamp = self._parse_int_header(headers, "X-OB-AI-Timestamp", _("Missing gateway timestamp header."))
        sequence = self._parse_int_header(headers, "X-OB-AI-Sequence", _("Missing gateway sequence header."))
        signature = (headers.get("X-OB-AI-Signature") or "").strip()
        if not signature:
            raise UserError(_("Missing gateway signature header."))
        max_skew = max(
            self._get_int_param(
                "ob_ai_assistant.gateway_max_clock_skew_seconds",
                self.GATEWAY_DEFAULT_CLOCK_SKEW_SECONDS,
            ),
            10,
        )
        now_ts = self._current_epoch_seconds()
        if abs(now_ts - timestamp) > max_skew:
            raise UserError(_("Gateway request timestamp is outside the allowed clock skew window."))
        expected_sequence = token_record.use_count + 1
        if sequence != expected_sequence:
            raise UserError(_("Gateway request sequence is invalid for this token."))
        expected_signature = self._build_gateway_signature(
            token_record,
            required_scope,
            timestamp,
            sequence,
            raw_body or b"",
        )
        if not hmac.compare_digest(expected_signature, signature):
            raise UserError(_("Gateway request signature is invalid."))
        self._register_token_use(token_record)
        return token_record

    def fetch_schema_bundle(self, token_value, model_names=None):
        token_record = self.validate_request_token(token_value, required_scope="read_schema")
        return self.fetch_schema_bundle_for_token(token_record, model_names=model_names)

    def fetch_schema_bundle_for_token(self, token_record, model_names=None):
        schema_service = self.env["ob.ai.schema.service"]
        model_names = model_names or self.env["ob.ai.access.service"].with_user(token_record.user_id).with_company(token_record.company_id).available_allowed_models(user=token_record.user_id).mapped("model_id.model")[: token_record.max_models_per_request]
        payload = schema_service.get_model_schema_payload(
            model_names[: token_record.max_models_per_request],
            user=token_record.user_id,
            schema_version=token_record.schema_version_id,
        )
        return {
            "token_id": token_record.id,
            "schema_version_id": token_record.schema_version_id.id if token_record.schema_version_id else False,
            "odoo_version": token_record.schema_version_id.odoo_version if token_record.schema_version_id else False,
            "models": payload,
        }

    def fetch_record_bundle(self, token_value, model_name, domain=None, limit=False, field_names=None, order=False):
        token_record = self.validate_request_token(token_value, required_scope="read_context")
        return self.fetch_record_bundle_for_token(
            token_record,
            model_name,
            domain=domain,
            limit=limit,
            field_names=field_names,
            order=order,
        )

    def fetch_record_bundle_for_token(self, token_record, model_name, domain=None, limit=False, field_names=None, order=False):
        company = token_record.company_id
        access_service = self.env["ob.ai.access.service"].with_user(token_record.user_id).with_company(company)
        allowed_model = access_service.get_allowed_model(model_name, user=token_record.user_id)
        policy = access_service.get_model_access_policy(allowed_model, user=token_record.user_id)
        limit = min(
            limit or policy.get("search_limit") or policy.get("max_record_count") or 5,
            token_record.max_records_per_fetch,
        )
        context_bundle = access_service.build_search_context(
            allowed_model,
            domain=domain or [],
            limit=limit,
            order=order or policy.get("default_order"),
            source="communication_gateway",
        )
        allowed_field_names = set(access_service.get_allowed_field_names(allowed_model, policy=policy))
        requested_fields = [field_name for field_name in (field_names or []) if field_name in allowed_field_names]
        blocked_requested_fields = sorted(set(field_names or []) - allowed_field_names)
        if requested_fields:
            rows = []
            for row in context_bundle["records"]:
                rows.append({key: value for key, value in row.items() if key in requested_fields or key == "display_name"})
            context_bundle["records"] = rows
            context_bundle["accessed_fields"][model_name] = [field_name for field_name in context_bundle["accessed_fields"].get(model_name, []) if field_name in requested_fields or field_name == "display_name"]
        context_bundle.update({
            "token_id": token_record.id,
            "schema_version_id": token_record.schema_version_id.id if token_record.schema_version_id else False,
            "blocked_requested_fields": blocked_requested_fields,
        })
        return context_bundle

    def count_records(self, token_value, model_name, domain=None):
        token_record = self.validate_request_token(token_value, required_scope="read_context")
        return self.count_records_for_token(token_record, model_name, domain=domain)

    def count_records_for_token(self, token_record, model_name, domain=None):
        _, _, record_model, _ = self._get_model_access(token_record, model_name)
        return {
            "token_id": token_record.id,
            "model": model_name,
            "count": record_model.search_count(domain or []),
        }

    def aggregate_records(self, token_value, model_name, domain=None, field_name=False, operator="sum"):
        token_record = self.validate_request_token(token_value, required_scope="read_context")
        return self.aggregate_records_for_token(
            token_record,
            model_name,
            domain=domain,
            field_name=field_name,
            operator=operator,
        )

    def aggregate_records_for_token(self, token_record, model_name, domain=None, field_name=False, operator="sum"):
        _, access_service, record_model, policy = self._get_model_access(token_record, model_name)
        allowed_field_names = set(access_service.get_allowed_field_names(policy["allowed_model"], policy=policy))
        aggregate_spec, field = self._prepare_aggregate_spec(record_model, field_name, operator, allowed_field_names)
        aggregate_row = record_model._read_group(domain or [], aggregates=[aggregate_spec, "__count"])
        values = aggregate_row[0] if aggregate_row else (False, 0)
        return {
            "token_id": token_record.id,
            "model": model_name,
            "field_name": field.name if field else False,
            "field_label": field.string if field else _("Visible records"),
            "operator": operator,
            "aggregate_spec": aggregate_spec,
            "value": self._serialize_value(values[0] if values else False),
            "count": int(values[1] or 0) if len(values) > 1 else 0,
        }

    def group_records(self, token_value, model_name, groupby_field, domain=None, aggregate_specs=None, limit=False, order=False):
        token_record = self.validate_request_token(token_value, required_scope="read_context")
        return self.group_records_for_token(
            token_record,
            model_name,
            groupby_field,
            domain=domain,
            aggregate_specs=aggregate_specs,
            limit=limit,
            order=order,
        )

    def group_records_for_token(self, token_record, model_name, groupby_field, domain=None, aggregate_specs=None, limit=False, order=False):
        _, access_service, record_model, policy = self._get_model_access(token_record, model_name)
        allowed_field_names = set(access_service.get_allowed_field_names(policy["allowed_model"], policy=policy))
        group_field = self._ensure_groupable_field(record_model, groupby_field, allowed_field_names)
        aggregate_specs = aggregate_specs or ["__count"]
        prepared_specs = [
            self._prepare_aggregate_spec(record_model, field_name, operator, allowed_field_names)[0]
            if aggregate_spec != "__count"
            else "__count"
            for aggregate_spec in aggregate_specs
            for field_name, operator in [self._split_aggregate_spec(aggregate_spec)]
        ]
        group_limit = min(limit or token_record.max_records_per_fetch, token_record.max_records_per_fetch)
        rows = record_model._read_group(
            domain or [],
            groupby=[group_field.name],
            aggregates=prepared_specs,
            limit=group_limit,
            order=order or self._default_group_order(prepared_specs, group_field.name),
        )
        groups = []
        total_count = 0
        for row in rows:
            pointer = 0
            group_value = row[pointer]
            pointer += 1
            aggregates = {}
            count_value = 0
            for spec in prepared_specs:
                raw_value = row[pointer] if pointer < len(row) else False
                pointer += 1
                key = self._aggregate_result_key(spec)
                serialized = self._serialize_value(raw_value)
                aggregates[key] = serialized
                if spec == "__count":
                    count_value = int(raw_value or 0)
            total_count += count_value
            groups.append({
                "group_key": self._serialize_group_key(group_value),
                "group_label": self._group_label(group_value),
                "count": count_value,
                "aggregates": aggregates,
            })
        return {
            "token_id": token_record.id,
            "model": model_name,
            "groupby_field": group_field.name,
            "groupby_label": group_field.string,
            "aggregate_specs": prepared_specs,
            "groups": groups,
            "group_count": len(groups),
            "total_count": total_count,
        }

    def execute_tool_plan(self, token_value, requests, max_requests=False):
        token_record = self.validate_request_token(token_value, required_scope="read_context")
        return self.execute_tool_plan_for_token(token_record, requests, max_requests=max_requests)

    def dispatch_tool_calls(self, token_value, tool_calls, max_requests=False):
        token_record = self.validate_request_token(token_value, required_scope=self.ACTION_SCOPE)
        return self.dispatch_tool_calls_for_token(token_record, tool_calls, max_requests=max_requests)

    def dispatch_tool_calls_for_token(self, token_record, tool_calls, max_requests=False):
        if tool_calls is None:
            tool_calls = []
        if not isinstance(tool_calls, list):
            raise UserError(_("Tool calls must be provided as a list."))
        max_requests = max_requests or self._get_int_param("ob_ai_assistant.orchestrator_max_tools", 12)
        max_requests = max(int(max_requests or 1), 1)
        tool_service = self.env["ob.ai.tool.service"].with_user(token_record.user_id).with_company(token_record.company_id)
        results = []
        for item in tool_calls[:max_requests]:
            if not isinstance(item, dict):
                results.append({
                    "status": "error",
                    "error": _("Each tool call must be a JSON object."),
                })
                continue
            tool_code = (item.get("tool") or item.get("tool_code") or "").strip()
            arguments = item.get("arguments") or {}
            if not tool_code:
                results.append({
                    "status": "error",
                    "error": _("tool is required for every call."),
                })
                continue
            dispatch_result = tool_service.dispatch(
                tool_code=tool_code,
                arguments=arguments if isinstance(arguments, dict) else {},
                conversation=token_record.conversation_id,
                session=False,
                step=False,
                user=token_record.user_id,
            )
            dispatch_result["tool"] = tool_code
            results.append(dispatch_result)
        return {
            "results": results,
            "count": len(results),
            "max_requests": max_requests,
        }

    def execute_tool_plan_for_token(self, token_record, requests, max_requests=False):
        if requests is None:
            requests = []
        if not isinstance(requests, list):
            raise UserError(_("Tool requests must be provided as a list."))
        max_requests = max_requests or self._get_int_param("ob_ai_assistant.orchestrator_max_tools", 12)
        max_requests = max(int(max_requests or 1), 1)
        results = []
        merged_context = {
            "source": "communication_tool_plan",
            "records": [],
            "accessed_models": [],
            "accessed_record_ids": {},
            "accessed_fields": {},
            "blocked_fields": {},
            "hidden_record_count": 0,
        }
        warnings = []
        for request in requests[:max_requests]:
            result = self.execute_tool_request_for_token(token_record, request)
            results.append(result)
            if result.get("ok"):
                self._merge_context_bundle(merged_context, result.get("context_bundle"))
            else:
                if result.get("error"):
                    warnings.append(result["error"])
        return {
            "results": results,
            "context_bundle": merged_context,
            "warning_message": "\n".join(warnings) if warnings else False,
        }

    def execute_tool_request_for_token(self, token_record, request):
        normalized = self._normalize_tool_request(token_record, request)
        model_name = normalized["model"]
        operation = normalized["operation"]
        try:
            if operation == "count":
                payload = self.count_records_for_token(
                    token_record,
                    model_name,
                    domain=normalized.get("domain") or [],
                )
                return {
                    "ok": True,
                    "request": normalized,
                    "data": payload,
                    "context_bundle": self._context_bundle_from_count(payload),
                }
            if operation == "aggregate":
                payload = self.aggregate_records_for_token(
                    token_record,
                    model_name,
                    domain=normalized.get("domain") or [],
                    field_name=normalized.get("field_name"),
                    operator=normalized.get("operator") or "sum",
                )
                return {
                    "ok": True,
                    "request": normalized,
                    "data": payload,
                    "context_bundle": self._context_bundle_from_count(payload),
                }
            if operation == "group":
                payload = self.group_records_for_token(
                    token_record,
                    model_name,
                    normalized.get("groupby_field"),
                    domain=normalized.get("domain") or [],
                    aggregate_specs=normalized.get("aggregate_specs") or ["__count"],
                    limit=normalized.get("limit"),
                    order=normalized.get("order"),
                )
                return {
                    "ok": True,
                    "request": normalized,
                    "data": payload,
                    "context_bundle": self._context_bundle_from_group(payload),
                }
            payload = self.fetch_record_bundle_for_token(
                token_record,
                model_name,
                domain=normalized.get("domain") or [],
                limit=normalized.get("limit"),
                field_names=normalized.get("fields"),
                order=normalized.get("order"),
            )
            return {
                "ok": True,
                "request": normalized,
                "data": payload,
                "context_bundle": payload,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "request": normalized,
                "error": str(exc),
            }

    def _normalize_tool_request(self, token_record, request):
        if not isinstance(request, dict):
            raise UserError(_("Each tool request must be a JSON object."))
        operation = (request.get("operation") or "query").strip().lower()
        if operation not in {"query", "count", "aggregate", "group"}:
            raise UserError(_("Tool operation %s is not supported.") % operation)
        model_name = (request.get("model") or "").strip()
        if not model_name:
            raise UserError(_("Tool request model is required."))
        normalized = {
            "operation": operation,
            "model": model_name,
            "domain": self._sanitize_domain(request.get("domain")),
        }
        if operation in {"query", "group"}:
            limit = self._safe_int(request.get("limit"), default=5)
            normalized["limit"] = min(max(limit, 1), token_record.max_records_per_fetch or 25)
        fields = self._sanitize_field_names(request.get("fields"))
        if fields:
            normalized["fields"] = fields
        order = (request.get("order") or "").strip()
        if order:
            normalized["order"] = order[:120]
        if operation == "aggregate":
            normalized["field_name"] = (request.get("field_name") or "").strip() or False
            operator = (request.get("operator") or "sum").strip().lower()
            normalized["operator"] = operator
        if operation == "group":
            groupby_field = (request.get("groupby_field") or request.get("groupby") or "").strip()
            if not groupby_field:
                raise UserError(_("groupby_field is required for grouped tool requests."))
            normalized["groupby_field"] = groupby_field
            aggregate_specs = self._sanitize_aggregate_specs(request.get("aggregate_specs"))
            normalized["aggregate_specs"] = aggregate_specs or ["__count"]
        return normalized

    def _sanitize_domain(self, domain):
        if not isinstance(domain, list):
            return []
        sanitized = []
        supported_ops = {
            "=",
            "!=",
            ">",
            ">=",
            "<",
            "<=",
            "in",
            "not in",
            "ilike",
            "like",
            "not like",
            "child_of",
        }
        for token in domain:
            if token in ("|", "&", "!"):
                sanitized.append(token)
                continue
            if not isinstance(token, (list, tuple)) or len(token) != 3:
                continue
            field_name = str(token[0] or "").strip()
            operator = str(token[1] or "").strip().lower()
            if not field_name or operator not in supported_ops:
                continue
            sanitized.append([field_name, operator, self._sanitize_domain_value(token[2])])
        return sanitized

    def _sanitize_domain_value(self, value):
        if isinstance(value, (str, int, float, bool)) or value is False or value is None:
            return value
        if isinstance(value, (list, tuple)):
            return [self._sanitize_domain_value(item) for item in value][:30]
        return str(value)

    def _sanitize_field_names(self, values):
        if not isinstance(values, list):
            return []
        sanitized = []
        for value in values:
            field_name = str(value or "").strip()
            if not field_name:
                continue
            if field_name not in sanitized:
                sanitized.append(field_name)
            if len(sanitized) >= 20:
                break
        return sanitized

    def _sanitize_aggregate_specs(self, specs):
        if not isinstance(specs, list):
            return []
        supported = {"sum", "avg", "min", "max", "count", "count_distinct"}
        cleaned = []
        for spec in specs:
            spec = str(spec or "").strip()
            if not spec:
                continue
            if spec == "__count":
                cleaned.append(spec)
                continue
            if ":" not in spec:
                continue
            field_name, operator = spec.split(":", 1)
            if operator not in supported:
                continue
            cleaned.append("%s:%s" % (field_name.strip(), operator))
        return cleaned

    def _safe_int(self, value, default=0):
        try:
            return int(value or default)
        except (TypeError, ValueError):
            return default

    def _context_bundle_from_count(self, payload):
        model_name = payload.get("model")
        return {
            "source": "communication_tool_count",
            "records": [],
            "accessed_models": [model_name] if model_name else [],
            "accessed_record_ids": {},
            "accessed_fields": {model_name: []} if model_name else {},
            "blocked_fields": {},
            "hidden_record_count": 0,
        }

    def _context_bundle_from_group(self, payload):
        model_name = payload.get("model")
        return {
            "source": "communication_tool_group",
            "records": [],
            "accessed_models": [model_name] if model_name else [],
            "accessed_record_ids": {},
            "accessed_fields": {model_name: [payload.get("groupby_field")]} if model_name and payload.get("groupby_field") else {},
            "blocked_fields": {},
            "hidden_record_count": 0,
        }

    def _merge_context_bundle(self, merged, bundle):
        if not bundle:
            return
        for row in bundle.get("records") or []:
            merged["records"].append(row)
        for model_name in bundle.get("accessed_models") or []:
            if model_name not in merged["accessed_models"]:
                merged["accessed_models"].append(model_name)
        for model_name, record_ids in (bundle.get("accessed_record_ids") or {}).items():
            merged["accessed_record_ids"].setdefault(model_name, [])
            for record_id in record_ids:
                if record_id not in merged["accessed_record_ids"][model_name]:
                    merged["accessed_record_ids"][model_name].append(record_id)
        for model_name, field_names in (bundle.get("accessed_fields") or {}).items():
            merged["accessed_fields"].setdefault(model_name, [])
            for field_name in field_names:
                if field_name and field_name not in merged["accessed_fields"][model_name]:
                    merged["accessed_fields"][model_name].append(field_name)
        for model_name, field_names in (bundle.get("blocked_fields") or {}).items():
            merged["blocked_fields"].setdefault(model_name, [])
            for field_name in field_names:
                if field_name and field_name not in merged["blocked_fields"][model_name]:
                    merged["blocked_fields"][model_name].append(field_name)
        merged["hidden_record_count"] += int(bundle.get("hidden_record_count") or 0)

    def _token_digest(self, token_value):
        secret = self._get_secret().encode()
        return hmac.new(secret, token_value.encode(), hashlib.sha256).hexdigest()

    def _current_epoch_seconds(self):
        return int(datetime.now(timezone.utc).timestamp())

    def _canonical_payload(self, payload):
        if payload is None:
            return b"{}"
        if isinstance(payload, (bytes, bytearray)):
            return bytes(payload)
        if isinstance(payload, str):
            return payload.encode("utf-8")
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")

    def _build_gateway_signature(self, token_record, required_scope, timestamp, sequence, raw_body):
        body_bytes = raw_body if isinstance(raw_body, (bytes, bytearray)) else self._canonical_payload(raw_body)
        body_digest = hashlib.sha256(body_bytes).hexdigest()
        base = "%s|%s|%s|%s|%s" % (
            token_record.token_jti,
            required_scope,
            int(timestamp),
            int(sequence),
            body_digest,
        )
        secret = self._get_secret().encode("utf-8")
        return hmac.new(secret, base.encode("utf-8"), hashlib.sha256).hexdigest()

    def _extract_gateway_token(self, headers):
        authorization = (headers.get("Authorization") or headers.get("authorization") or "").strip()
        if authorization.lower().startswith("bearer "):
            token_value = authorization[7:].strip()
            if token_value:
                return token_value
        token_value = (headers.get("X-OB-AI-Token") or headers.get("x-ob-ai-token") or "").strip()
        if token_value:
            return token_value
        raise UserError(_("Missing gateway token."))

    def _parse_int_header(self, headers, header_name, error_message):
        raw_value = headers.get(header_name) or headers.get(header_name.lower())
        if raw_value is None:
            raise UserError(error_message)
        try:
            return int(str(raw_value).strip())
        except (TypeError, ValueError):
            raise UserError(error_message) from None

    def _get_secret(self):
        params = self.env["ir.config_parameter"].sudo()
        secret = params.get_param("ob_ai_assistant.communication_secret", default=False)
        if not secret:
            secret = secrets.token_hex(32)
            params.set_param("ob_ai_assistant.communication_secret", secret)
        return secret

    def _template_signature(self, templates):
        return "|".join(
            "%s:%s" % (template.id, fields.Datetime.to_string(template.write_date) if template.write_date else "")
            for template in templates
        )

    def _get_int_param(self, key, default=0):
        return int(self.env["ir.config_parameter"].sudo().get_param(key, default=str(default)) or default)

    def _get_bool_param(self, key, default=False):
        value = self.env["ir.config_parameter"].sudo().get_param(key, default=str(default))
        return value == "True"

    def _can_issue_action_scope(self, user, access_service=False, templates=False):
        access_service = access_service or self.env["ob.ai.access.service"].with_user(user).with_company(user.company_id or self.env.company)
        templates = templates if templates is not False else access_service.get_user_templates(user=user)
        if not self._get_bool_param("ob_ai_assistant.gateway_allow_action_scope", True):
            return False
        admin_only = self._get_bool_param("ob_ai_assistant.gateway_action_scope_admin_only", True)
        if admin_only:
            is_admin = bool(
                user.has_group("base.group_system")
                or user.has_group("ob_ai_assistant.group_ai_administrator")
            )
            if not is_admin:
                return False
        return bool(templates.filtered("allow_full_access")[:1])

    def _get_model_access(self, token_record, model_name):
        company = token_record.company_id
        access_service = self.env["ob.ai.access.service"].with_user(token_record.user_id).with_company(company)
        allowed_model = access_service.get_allowed_model(model_name, user=token_record.user_id)
        record_model = self.env[model_name].with_user(token_record.user_id).with_company(company)
        access_service._check_read_access(record_model)
        policy = access_service.get_model_access_policy(allowed_model, user=token_record.user_id)
        policy["allowed_model"] = allowed_model
        return allowed_model, access_service, record_model, policy

    def _prepare_aggregate_spec(self, record_model, field_name, operator, allowed_field_names):
        operator = (operator or "sum").lower()
        if operator == "count" and not field_name:
            return "__count", False
        if not field_name:
            raise UserError(_("A visible field is required for the %s aggregation.") % operator)
        field = self._ensure_field_allowed(record_model, field_name, allowed_field_names)
        if operator in {"sum", "avg", "min", "max"} and field.type not in {"integer", "float", "monetary"}:
            raise UserError(_("Field %s cannot be aggregated with %s.") % (field.string, operator))
        if operator in {"count", "count_distinct"}:
            return "%s:%s" % (field_name, operator), field
        if operator not in {"sum", "avg", "min", "max"}:
            raise UserError(_("Aggregation %s is not supported for secure AI communication.") % operator)
        return "%s:%s" % (field_name, operator), field

    def _ensure_groupable_field(self, record_model, field_name, allowed_field_names):
        field = self._ensure_field_allowed(record_model, field_name, allowed_field_names)
        if not field.store or field.type in {"binary", "html", "one2many", "many2many"}:
            raise UserError(_("Field %s cannot be used for grouped AI analysis.") % field.string)
        return field

    def _ensure_field_allowed(self, record_model, field_name, allowed_field_names):
        if field_name not in allowed_field_names or field_name not in record_model._fields:
            raise UserError(_("Field %s is not visible in the current AI scope.") % field_name)
        return record_model._fields[field_name]

    def _split_aggregate_spec(self, aggregate_spec):
        if aggregate_spec == "__count":
            return False, "count"
        field_name, operator = aggregate_spec.split(":", 1)
        return field_name, operator

    def _aggregate_result_key(self, aggregate_spec):
        if aggregate_spec == "__count":
            return "__count"
        field_name, operator = self._split_aggregate_spec(aggregate_spec)
        return "%s:%s" % (field_name, operator)

    def _default_group_order(self, aggregate_specs, groupby_field):
        if aggregate_specs:
            preferred = aggregate_specs[-1]
            if preferred == "__count":
                return "__count DESC"
            return "%s DESC" % preferred
        return "%s ASC" % groupby_field

    def _serialize_group_key(self, value):
        if hasattr(value, "_name"):
            return value.ids[0] if value else False
        return self._serialize_value(value)

    def _group_label(self, value):
        if hasattr(value, "_name"):
            return value.display_name if value else _("Undefined")
        serialized = self._serialize_value(value)
        return str(serialized) if serialized not in (False, None, "") else _("Undefined")

    def _serialize_value(self, value):
        if hasattr(value, "_name"):
            return {
                "id": value.ids[0] if value else False,
                "display_name": value.display_name if value else False,
            }
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return value
