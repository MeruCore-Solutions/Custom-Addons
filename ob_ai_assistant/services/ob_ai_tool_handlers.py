"""Tool handler implementations.

These methods are dynamically invoked by ob.ai.tool.service.dispatch().
Each handler:
  - Receives `conversation` (record or False), `user` (record), and tool-specific kwargs.
  - Returns a JSON-serializable dict. By convention: {"ok": True, ...payload} or {"ok": False, "error": "..."}.
  - MUST respect Odoo ACLs (always use .with_user(user) or sudo() deliberately).
  - MUST cap result sizes (use limit, don't return giant payloads).

The class is registered as an AbstractModel that EXTENDS ob.ai.tool.service so
all `tool_*` methods are accessible to the dispatcher's getattr() lookup.
"""

import json
import logging
from datetime import date, datetime

from dateutil.relativedelta import relativedelta

from odoo import _, fields, models

_logger = logging.getLogger(__name__)

DEFAULT_RECORD_LIMIT = 25
MAX_RECORD_LIMIT = 200
DEFAULT_FIELDS = ["id", "display_name"]
SAFE_DOMAIN_OPERATORS = {
    "=", "!=", ">", ">=", "<", "<=",
    "in", "not in", "ilike", "like", "not ilike", "not like",
    "=like", "=ilike", "child_of", "parent_of",
}
SAFE_AGG_OPERATORS = {"sum", "avg", "min", "max", "count", "count_distinct"}
UNSAFE_METHOD_NAMES = {
    "create", "write", "unlink", "search", "search_read", "read", "read_group",
    "name_search", "check_access", "check_access_rights", "sudo", "with_user",
    "with_context", "fields_get", "mapped", "filtered", "flush", "recompute",
    "copy", "copy_data", "export_data", "import_data", "web_search_read",
}


class OBAIToolHandlers(models.AbstractModel):
    _inherit = "ob.ai.tool.service"

    # ================================================================== #
    # SCHEMA / DISCOVERY TOOLS
    # ================================================================== #

    def tool_list_models(self, conversation=None, user=None, category=None):
        """Return the list of Odoo models the AI is allowed to query."""
        user = user or self.env.user
        access_service = self.env["ob.ai.access.service"].with_user(user).with_company(user.company_id or self.env.company)
        allowed = access_service.available_allowed_models(user=user)
        result = []
        for am in allowed:
            if not am.model_id:
                continue
            result.append({
                "model": am.model_id.model,
                "name": am.model_id.name,
                "display_name": am.name or am.model_id.name,
                "description": am.display_name or "",
            })
        return {
            "ok": True,
            "models": result,
            "count": len(result),
            "admin_global_scope": access_service._allow_admin_global_scope(user),
        }

    def tool_describe_model(self, conversation=None, user=None, model_name=None):
        """Return field definitions and business semantics for an Odoo model."""
        validation = self._validate_odoo_access(model_name, user=user)
        if not validation["ok"]:
            return validation
        allowed = validation["allowed"]
        model_name = allowed.model_id.model

        allowed_field_names = self._get_allowed_field_names(allowed)
        fields_info = self.env[model_name].fields_get(allowed_field_names or None)
        compact_fields = {}
        for fname, finfo in fields_info.items():
            compact_fields[fname] = {
                "string": finfo.get("string"),
                "type": finfo.get("type"),
                "required": finfo.get("required"),
                "readonly": finfo.get("readonly"),
                "help": (finfo.get("help") or "")[:300],
                "relation": finfo.get("relation"),
                "selection": [s[0] for s in (finfo.get("selection") or [])][:30] if finfo.get("selection") else None,
            }
        # Semantic hints
        semantic = self.env["ob.ai.model.semantic"].sudo().search([("model_id.model", "=", model_name)], limit=1)
        semantic_payload = {}
        if semantic:
            semantic_payload = {
                "name": semantic.name,
                "business_label": semantic.business_label or semantic.name,
                "semantic_role": semantic.semantic_role,
                "hints": semantic.semantic_hints or "",
                "example_queries": semantic.example_queries or "",
                "title_fields": semantic.title_field_names or "",
                "state_fields": semantic.state_field_names or "",
                "primary_date_fields": semantic.primary_date_field_names or "",
                "owner_fields": semantic.owner_field_names or "",
            }
        # Relationships
        rels = self.env["ob.ai.model.relationship"].sudo().search([
            "|", ("source_model_id.model", "=", model_name), ("target_model_id.model", "=", model_name),
            ("active", "=", True),
        ])
        rel_payload = [{
            "source": r.source_model_id.model,
            "target": r.target_model_id.model,
            "type": r.relationship_type,
            "field": r.source_field_name,
            "meaning": r.business_meaning,
        } for r in rels]
        return {
            "ok": True, "model": model_name,
            "fields": compact_fields, "semantic": semantic_payload,
            "relationships": rel_payload, "field_count": len(compact_fields),
        }

    def tool_get_relationships(self, conversation=None, user=None, model_name=None):
        """List all model relationships involving the given model."""
        if not model_name:
            return {"ok": False, "error": "model_name is required."}
        rels = self.env["ob.ai.model.relationship"].sudo().search([
            "|", ("source_model_id.model", "=", model_name), ("target_model_id.model", "=", model_name),
            ("active", "=", True),
        ])
        return {"ok": True, "relationships": [{
            "name": r.name, "source": r.source_model_id.model, "target": r.target_model_id.model,
            "type": r.relationship_type, "source_field": r.source_field_name,
            "target_field": r.target_field_name, "meaning": r.business_meaning,
            "is_primary": r.is_primary,
        } for r in rels]}

    # ================================================================== #
    # PRIMITIVE ODOO DATA TOOLS
    # ================================================================== #

    def tool_odoo_search_read(self, conversation=None, user=None,
                              model=None, domain=None, fields=None,
                              limit=None, order=None, offset=0):
        """search_read with whitelist enforcement."""
        validation = self._validate_odoo_access(model, user=user)
        if not validation["ok"]:
            return validation
        allowed = validation["allowed"]
        allowed_fields = self._get_allowed_field_names(allowed)
        safe_domain = self._sanitize_domain(domain or [])
        # Force company scope on company-bound models
        if "company_id" in self.env[model]._fields and user and user.company_id:
            safe_domain.append(["company_id", "in", [user.company_id.id]])
        request_fields = list(fields or DEFAULT_FIELDS)
        if allowed_fields:
            request_fields = [f for f in request_fields if f in allowed_fields] or list(DEFAULT_FIELDS)
        capped_limit = min(int(limit or DEFAULT_RECORD_LIMIT), MAX_RECORD_LIMIT)
        records = self.env[model].with_user(user).search_read(
            domain=safe_domain,
            fields=request_fields,
            limit=capped_limit,
            offset=max(int(offset or 0), 0),
            order=order or False,
        )
        return {
            "ok": True, "model": model, "count": len(records),
            "records": records, "domain_used": safe_domain, "fields_used": request_fields,
        }

    def tool_odoo_count(self, conversation=None, user=None, model=None, domain=None):
        validation = self._validate_odoo_access(model, user=user)
        if not validation["ok"]:
            return validation
        safe_domain = self._sanitize_domain(domain or [])
        if "company_id" in self.env[model]._fields and user and user.company_id:
            safe_domain.append(["company_id", "in", [user.company_id.id]])
        count = self.env[model].with_user(user).search_count(safe_domain)
        return {"ok": True, "model": model, "count": count, "domain_used": safe_domain}

    def tool_odoo_aggregate(self, conversation=None, user=None,
                            model=None, field=None, operator="sum", domain=None):
        validation = self._validate_odoo_access(model, user=user)
        if not validation["ok"]:
            return validation
        if operator not in SAFE_AGG_OPERATORS:
            return {"ok": False, "error": "operator '%s' not allowed; use one of %s" % (operator, sorted(SAFE_AGG_OPERATORS))}
        if not field:
            return {"ok": False, "error": "field is required."}
        if field not in self.env[model]._fields:
            return {"ok": False, "error": "field '%s' does not exist on model '%s'." % (field, model)}
        allowed_field_names = self._get_allowed_field_names(validation["allowed"])
        if allowed_field_names and field not in allowed_field_names and operator not in ("count", "count_distinct"):
            return {"ok": False, "error": "field '%s' is not in the allowed-field whitelist for '%s'." % (field, model)}
        safe_domain = self._sanitize_domain(domain or [])
        if "company_id" in self.env[model]._fields and user and user.company_id:
            safe_domain.append(["company_id", "in", [user.company_id.id]])
        if operator == "count":
            value = self.env[model].with_user(user).search_count(safe_domain)
            return {"ok": True, "model": model, "operator": "count", "value": value, "domain_used": safe_domain}
        agg_spec = "%s:%s" % (field, operator)
        groups = self.env[model].with_user(user).read_group(safe_domain, [agg_spec], [])
        value = groups[0].get(field) if groups else 0
        return {
            "ok": True, "model": model, "operator": operator, "field": field,
            "value": value or 0, "domain_used": safe_domain,
        }

    def tool_odoo_group_by(self, conversation=None, user=None,
                           model=None, groupby=None, aggregate_fields=None, domain=None, limit=50):
        validation = self._validate_odoo_access(model, user=user)
        if not validation["ok"]:
            return validation
        if not groupby:
            return {"ok": False, "error": "groupby is required."}
        safe_domain = self._sanitize_domain(domain or [])
        if "company_id" in self.env[model]._fields and user and user.company_id:
            safe_domain.append(["company_id", "in", [user.company_id.id]])
        groupby_list = groupby if isinstance(groupby, list) else [groupby]
        agg_specs = []
        for spec in aggregate_fields or []:
            if isinstance(spec, str) and ":" in spec:
                fname, op = spec.split(":", 1)
                if op in SAFE_AGG_OPERATORS:
                    agg_specs.append(spec)
        if not agg_specs:
            agg_specs = ["__count"]
        try:
            groups = self.env[model].with_user(user).read_group(
                domain=safe_domain, fields=agg_specs, groupby=groupby_list,
                limit=min(int(limit or 50), 200), lazy=False,
            )
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": "read_group failed: %s" % exc}
        return {"ok": True, "model": model, "groupby": groupby_list, "aggregates": agg_specs, "groups": groups, "group_count": len(groups)}

    def tool_odoo_get_record(self, conversation=None, user=None, model=None, record_id=None, fields=None):
        validation = self._validate_odoo_access(model, user=user)
        if not validation["ok"]:
            return validation
        if not record_id:
            return {"ok": False, "error": "record_id is required."}
        record = self.env[model].with_user(user).browse(int(record_id))
        if not record.exists():
            return {"ok": False, "error": "Record %s,%s does not exist or is not accessible." % (model, record_id)}
        allowed_field_names = self._get_allowed_field_names(validation["allowed"])
        request_fields = list(fields or DEFAULT_FIELDS)
        if allowed_field_names:
            request_fields = [f for f in request_fields if f in allowed_field_names] or list(DEFAULT_FIELDS)
        data = record.read(request_fields)
        return {"ok": True, "model": model, "id": record.id, "data": data[0] if data else {}}

    def tool_search_records(self, conversation=None, user=None, model=None, term=None, limit=10):
        validation = self._validate_odoo_access(model, user=user)
        if not validation["ok"]:
            return validation
        if not term:
            return {"ok": False, "error": "term is required."}
        records = self.env[model].with_user(user).name_search(name=term, limit=min(int(limit or 10), 50))
        return {"ok": True, "model": model, "term": term, "matches": [{"id": r[0], "display_name": r[1]} for r in records]}

    # ================================================================== #
    # GENERIC ODOO ACTION TOOLS (analyst-grade operations)
    # ================================================================== #

    def tool_odoo_create_records(
        self,
        conversation=None,
        user=None,
        model=None,
        values_list=None,
        return_fields=None,
        dry_run=False,
    ):
        validation = self._validate_odoo_access(model, user=user)
        if not validation["ok"]:
            return validation
        model_obj = self.env[model].with_user(user)
        try:
            model_obj.check_access("create")
            model_obj.check_access("read")
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": "Access check failed for %s: %s" % (model, exc)}

        payload = values_list or []
        if isinstance(payload, dict):
            payload = [payload]
        if not isinstance(payload, list) or not payload:
            return {"ok": False, "error": "values_list must be a non-empty object or list of objects."}

        access_service = self.env["ob.ai.access.service"]
        policy = access_service.get_model_access_policy(validation["allowed"], user=user)
        allowed_fields = set(access_service.get_allowed_field_names(validation["allowed"], policy=policy))

        sanitized_values = []
        errors = []
        for index, values in enumerate(payload, start=1):
            if not isinstance(values, dict):
                errors.append({"row_number": index, "error": "each values row must be an object"})
                continue
            try:
                sanitized = self._sanitize_write_values(
                    model_obj,
                    values,
                    allowed_fields=allowed_fields,
                    user=user,
                    m2o_cache={},
                )
                if sanitized:
                    sanitized_values.append(sanitized)
                else:
                    errors.append({"row_number": index, "error": "all fields were empty or blocked"})
            except Exception as exc:  # noqa: BLE001
                errors.append({"row_number": index, "error": str(exc)})

        if not sanitized_values:
            return {
                "ok": False,
                "error": "No valid create rows after sanitization.",
                "errors": errors[:20],
            }

        if dry_run:
            return {
                "ok": True,
                "model": model,
                "dry_run": True,
                "create_count": len(sanitized_values),
                "preview_values": sanitized_values[:10],
                "errors": errors[:20],
            }

        created_records = self.env[model].with_user(user).browse()
        write_errors = list(errors)
        for index, values in enumerate(sanitized_values, start=1):
            try:
                created_records |= model_obj.create(values)
            except Exception as exc:  # noqa: BLE001
                write_errors.append({"row_number": index, "error": str(exc)})
                if len(write_errors) >= 20:
                    break

        preview_fields = self._safe_preview_fields(model_obj, allowed_fields, return_fields=return_fields)
        preview_rows = created_records.read(preview_fields, load=None) if created_records else []
        return {
            "ok": True,
            "model": model,
            "dry_run": False,
            "created_count": len(created_records),
            "requested_count": len(sanitized_values),
            "created_ids": created_records.ids,
            "records": preview_rows[:50],
            "errors": write_errors[:20],
        }

    def tool_odoo_update_records(
        self,
        conversation=None,
        user=None,
        model=None,
        values=None,
        record_ids=None,
        domain=None,
        limit=200,
        return_fields=None,
        dry_run=False,
    ):
        validation = self._validate_odoo_access(model, user=user)
        if not validation["ok"]:
            return validation
        if not isinstance(values, dict) or not values:
            return {"ok": False, "error": "values must be a non-empty object."}
        model_obj = self.env[model].with_user(user)
        try:
            model_obj.check_access("write")
            model_obj.check_access("read")
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": "Access check failed for %s: %s" % (model, exc)}

        access_service = self.env["ob.ai.access.service"]
        policy = access_service.get_model_access_policy(validation["allowed"], user=user)
        allowed_fields = set(access_service.get_allowed_field_names(validation["allowed"], policy=policy))
        try:
            sanitized_values = self._sanitize_write_values(
                model_obj,
                values,
                allowed_fields=allowed_fields,
                user=user,
                m2o_cache={},
            )
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
        if not sanitized_values:
            return {"ok": False, "error": "No writable fields remain after sanitization."}

        records = self._resolve_target_records(
            model_obj=model_obj,
            record_ids=record_ids,
            domain=domain,
            limit=limit,
        )
        if not records:
            return {"ok": False, "error": "No matching records found for update."}

        preview_fields = self._safe_preview_fields(model_obj, allowed_fields, return_fields=return_fields)
        before_rows = records[:50].read(preview_fields, load=None)
        if dry_run:
            return {
                "ok": True,
                "model": model,
                "dry_run": True,
                "update_count": len(records),
                "values": sanitized_values,
                "records_before": before_rows,
            }

        records.write(sanitized_values)
        after_rows = records[:50].read(preview_fields, load=None)
        return {
            "ok": True,
            "model": model,
            "dry_run": False,
            "updated_count": len(records),
            "updated_ids": records.ids[:200],
            "values": sanitized_values,
            "records_before": before_rows,
            "records_after": after_rows,
        }

    def tool_odoo_delete_records(
        self,
        conversation=None,
        user=None,
        model=None,
        record_ids=None,
        domain=None,
        limit=200,
        dry_run=False,
    ):
        validation = self._validate_odoo_access(model, user=user)
        if not validation["ok"]:
            return validation
        model_obj = self.env[model].with_user(user)
        try:
            model_obj.check_access("unlink")
            model_obj.check_access("read")
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": "Access check failed for %s: %s" % (model, exc)}

        records = self._resolve_target_records(
            model_obj=model_obj,
            record_ids=record_ids,
            domain=domain,
            limit=limit,
        )
        if not records:
            return {"ok": False, "error": "No matching records found for delete."}

        sample = [{"id": record.id, "display_name": record.display_name} for record in records[:50]]
        if dry_run:
            return {
                "ok": True,
                "model": model,
                "dry_run": True,
                "delete_count": len(records),
                "sample": sample,
            }

        deleted_ids = list(records.ids)
        records.unlink()
        return {
            "ok": True,
            "model": model,
            "dry_run": False,
            "deleted_count": len(deleted_ids),
            "deleted_ids": deleted_ids[:200],
            "sample": sample,
        }

    def tool_odoo_call_method(
        self,
        conversation=None,
        user=None,
        model=None,
        method=None,
        record_id=None,
        record_ids=None,
        domain=None,
        limit=200,
        args=None,
        kwargs=None,
        call_on_model=False,
        dry_run=False,
    ):
        validation = self._validate_odoo_access(model, user=user)
        if not validation["ok"]:
            return validation
        if not method:
            return {"ok": False, "error": "method is required."}
        if not self._is_safe_business_method(method):
            return {
                "ok": False,
                "error": "Method '%s' is blocked. Use business methods such as action_*/button_*." % method,
            }

        model_obj = self.env[model].with_user(user)
        try:
            model_obj.check_access("read")
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": "Access check failed for %s: %s" % (model, exc)}

        if call_on_model:
            target = model_obj
        else:
            resolved_ids = list(record_ids or [])
            if record_id:
                resolved_ids.append(int(record_id))
            target = self._resolve_target_records(
                model_obj=model_obj,
                record_ids=resolved_ids or False,
                domain=domain,
                limit=limit,
            )
        if not target:
            return {"ok": False, "error": "No target records were found for method call."}
        if not hasattr(target, method):
            return {"ok": False, "error": "Method '%s' was not found on model '%s'." % (method, model)}

        method_callable = getattr(target, method)
        if not callable(method_callable):
            return {"ok": False, "error": "Attribute '%s' is not callable on model '%s'." % (method, model)}

        args = args if isinstance(args, list) else []
        kwargs = kwargs if isinstance(kwargs, dict) else {}
        if dry_run:
            return {
                "ok": True,
                "model": model,
                "method": method,
                "dry_run": True,
                "target_count": len(target) if hasattr(target, "ids") else 0,
                "target_ids": target.ids[:200] if hasattr(target, "ids") else [],
                "args": args,
                "kwargs": kwargs,
            }

        result = method_callable(*args, **kwargs)
        return {
            "ok": True,
            "model": model,
            "method": method,
            "target_count": len(target) if hasattr(target, "ids") else 0,
            "target_ids": target.ids[:200] if hasattr(target, "ids") else [],
            "result": self._jsonable_result(result),
        }

    # ================================================================== #
    # KPI TOOLS
    # ================================================================== #

    def tool_list_kpis(self, conversation=None, user=None, category=None):
        domain = [("active", "=", True)]
        if category:
            domain.append(("category", "=", category))
        kpis = self.env["ob.ai.kpi.definition"].sudo().search(domain)
        return {"ok": True, "kpis": [{
            "code": k.code, "name": k.name, "category": k.category,
            "model": k.model_id.model if k.model_id else None,
            "field": k.field_name, "aggregation": k.aggregation,
            "unit": k.unit, "synonyms": k.get_synonym_list(),
            "description": k.description or "",
        } for k in kpis]}

    def tool_compute_kpi(self, conversation=None, user=None, kpi_code=None, date_from=None, date_to=None, extra_domain=None):
        if not kpi_code:
            return {"ok": False, "error": "kpi_code is required."}
        kpi = self.env["ob.ai.kpi.definition"].sudo().search([("code", "=", kpi_code), ("active", "=", True)], limit=1)
        if not kpi:
            return {"ok": False, "error": "KPI '%s' not found." % kpi_code}
        if not kpi.model_id or kpi.model_id.model not in self.env:
            return {"ok": False, "error": "KPI '%s' is not bound to a queryable model." % kpi_code}
        request = kpi.build_tool_request(domain=self._sanitize_domain(extra_domain or []), date_from=date_from, date_to=date_to)
        if not request:
            return {"ok": False, "error": "KPI definition is incomplete (missing field or aggregation)."}
        # Dispatch through aggregate primitive for safety
        return self.tool_odoo_aggregate(
            conversation=conversation, user=user,
            model=request["model"], field=request.get("field_name"),
            operator=request["operator"], domain=request.get("domain"),
        ) | {"kpi_code": kpi_code, "kpi_name": kpi.name, "unit": kpi.unit or ""}

    # ================================================================== #
    # STRATEGIC ANALYTICS TOOLS
    # ================================================================== #

    def tool_compute_health_score(self, conversation=None, user=None, with_narrative=False):
        analytics = self.env["ob.ai.analytics.service"]
        provider = conversation._get_effective_provider() if conversation and hasattr(conversation, "_get_effective_provider") else False
        model = conversation._get_effective_model(provider=provider) if provider and conversation and hasattr(conversation, "_get_effective_model") else False
        health = analytics.compute_health_score(
            conversation=conversation, company=user.company_id,
            provider=provider if with_narrative else None,
            model=model if with_narrative else None,
        )
        return {
            "ok": True, "health_score_id": health.id,
            "overall_score": health.overall_score, "grade": health.overall_grade,
            "domains": {
                "liquidity": health.liquidity_score, "growth": health.growth_score,
                "execution": health.execution_score, "pipeline": health.pipeline_score,
                "fulfillment": health.fulfillment_score, "receivable": health.receivable_score,
            },
            "metrics": json.loads(health.metrics_payload or "{}"),
            "warnings": json.loads(health.warnings_payload or "[]"),
            "narrative": health.analysis_text or "",
            "benchmark_gaps": health.benchmark_gap_text or "",
        }

    def tool_run_forecast(self, conversation=None, user=None, forecast_type="revenue", periods=3, period_unit="month"):
        analytics = self.env["ob.ai.analytics.service"]
        run = analytics.run_forecast(
            conversation=conversation, forecast_type=forecast_type,
            periods=int(periods or 3), period_unit=period_unit or "month",
            company=user.company_id, provider=None, model=None,
        )
        return {
            "ok": True, "forecast_run_id": run.id, "forecast_type": run.forecast_type,
            "methodology": run.methodology, "assumptions": run.assumptions,
            "forecast": run.get_forecast_data(),
        }

    def tool_run_scenario(self, conversation=None, user=None, scenario_type="custom", change_pct=10, direction="increase", extra_params=None):
        analytics = self.env["ob.ai.analytics.service"]
        params = {"scenario_type": scenario_type, "change_pct": float(change_pct or 0), "direction": direction or "increase"}
        if isinstance(extra_params, dict):
            params.update(extra_params)
        run = analytics.run_scenario(
            conversation=conversation, scenario_type=scenario_type, parameters=params,
            company=user.company_id, provider=None, model=None,
        )
        return {
            "ok": True, "scenario_run_id": run.id, "scenario_type": run.scenario_type,
            "parameters": params, "impact": run.get_impact(),
            "sensitivity": json.loads(run.sensitivity_payload or "[]"),
        }

    # ================================================================== #
    # BENCHMARK TOOLS
    # ================================================================== #

    def tool_get_benchmark(self, conversation=None, user=None, metric_category=None, country_code=None, industry_code=None):
        if not metric_category:
            return {"ok": False, "error": "metric_category is required."}
        bench = self.env["ob.ai.benchmark.service"]
        ctx = bench.get_benchmark_context(
            [metric_category], company=user.company_id,
            country_code=country_code or (user.company_id.country_id.code if user.company_id.country_id else None),
            industry_code=industry_code,
        )
        return {"ok": True, "metric_category": metric_category, "benchmarks": ctx}

    def tool_compare_to_benchmark(self, conversation=None, user=None, metric_categories=None, country_code=None, industry_code=None):
        cats = metric_categories or ["revenue", "margin", "ar_days", "inventory_turns"]
        bench = self.env["ob.ai.benchmark.service"]
        baselines = bench.get_internal_baselines(cats, reference_company=user.company_id)
        comparison = bench.compare_to_benchmarks(
            baselines, cats, company=user.company_id,
            country_code=country_code or (user.company_id.country_id.code if user.company_id.country_id else None),
            industry_code=industry_code,
        )
        return {"ok": True, "internal_baselines": baselines, "comparison": comparison}

    # ================================================================== #
    # DOCUMENT TOOLS
    # ================================================================== #

    def tool_list_record_attachments(self, conversation=None, user=None, model=None, record_id=None):
        if not model or not record_id:
            return {"ok": False, "error": "model and record_id are required."}
        attachments = self.env["ir.attachment"].with_user(user).search([
            ("res_model", "=", model), ("res_id", "=", int(record_id)),
        ], limit=50)
        return {"ok": True, "attachments": [{
            "id": a.id, "name": a.name, "mimetype": a.mimetype,
            "size": a.file_size, "create_date": str(a.create_date),
        } for a in attachments]}

    def tool_analyze_attachment(self, conversation=None, user=None, attachment_id=None):
        if not attachment_id:
            return {"ok": False, "error": "attachment_id is required."}
        attachment = self.env["ir.attachment"].with_user(user).browse(int(attachment_id))
        if not attachment.exists():
            return {"ok": False, "error": "Attachment %s not found or not accessible." % attachment_id}
        try:
            doc_service = self.env["ob.ai.document.service"]
            context = doc_service.build_attachment_context(attachment, conversation=conversation)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": "Document analysis failed: %s" % exc}
        return {"ok": True, "attachment_id": attachment.id, "name": attachment.name, "context": context}

    def tool_extract_attachment_data(self, conversation=None, user=None, attachment_id=None, sheet_name=None, max_rows=100):
        if not attachment_id:
            return {"ok": False, "error": "attachment_id is required."}
        attachment = self.env["ir.attachment"].with_user(user).browse(int(attachment_id))
        if not attachment.exists():
            return {"ok": False, "error": "Attachment %s not found or not accessible." % attachment_id}
        try:
            doc_service = self.env["ob.ai.document.service"]
            context = doc_service.build_attachment_context(
                attachment,
                conversation=conversation,
                max_rows=max(max_rows or 100, 1),
            )
            table_result = doc_service.get_attachment_tabular_rows(
                attachment,
                sheet_name=sheet_name,
                max_rows=max_rows or 100,
            )
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": "Attachment extraction failed: %s" % exc}

        return {
            "ok": True,
            "attachment_id": attachment.id,
            "name": attachment.name,
            "mimetype": attachment.mimetype,
            "context": context,
            "table_result": table_result,
        }

    def tool_import_attachment_rows(
        self,
        conversation=None,
        user=None,
        model=None,
        attachment_id=None,
        field_map=None,
        mode="create",
        key_field=None,
        sheet_name=None,
        max_rows=200,
        dry_run=False,
    ):
        if not model:
            return {"ok": False, "error": "model is required."}
        if not attachment_id:
            return {"ok": False, "error": "attachment_id is required."}
        if not isinstance(field_map, dict) or not field_map:
            return {"ok": False, "error": "field_map must be a non-empty object."}
        if mode not in {"create", "upsert"}:
            return {"ok": False, "error": "mode must be 'create' or 'upsert'."}

        validation = self._validate_odoo_access(model, user=user)
        if not validation["ok"]:
            return validation
        allowed_model = validation["allowed"]
        access_service = self.env["ob.ai.access.service"]
        policy = access_service.get_model_access_policy(allowed_model, user=user)
        allowed_fields = set(access_service.get_allowed_field_names(allowed_model, policy=policy))

        model_obj = self.env[model].with_user(user)
        try:
            model_obj.check_access("read")
            model_obj.check_access("create")
            model_obj.check_access("write")
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": "Access check failed for %s: %s" % (model, exc)}

        unknown_fields = [field_name for field_name in field_map if field_name not in model_obj._fields]
        if unknown_fields:
            return {"ok": False, "error": "Unknown target fields: %s" % ", ".join(sorted(unknown_fields))}
        blocked_fields = [field_name for field_name in field_map if allowed_fields and field_name not in allowed_fields]
        if blocked_fields:
            return {"ok": False, "error": "Fields are not allowed by access template: %s" % ", ".join(sorted(blocked_fields))}
        if mode == "upsert" and not key_field:
            return {"ok": False, "error": "key_field is required when mode='upsert'."}
        if key_field and key_field not in field_map:
            return {"ok": False, "error": "key_field must be present in field_map."}

        attachment = self.env["ir.attachment"].with_user(user).browse(int(attachment_id))
        if not attachment.exists():
            return {"ok": False, "error": "Attachment %s not found or not accessible." % attachment_id}

        doc_service = self.env["ob.ai.document.service"]
        rows_result = doc_service.get_attachment_tabular_rows(
            attachment,
            sheet_name=sheet_name,
            max_rows=max_rows or 200,
        )
        if not rows_result.get("ok"):
            return rows_result

        source_rows = rows_result.get("rows") or []
        if not source_rows:
            return {"ok": False, "error": "No rows were found in the selected table."}

        created_count = 0
        updated_count = 0
        skipped_count = 0
        error_rows = []
        sample_records = []
        m2o_cache = {}

        for index, row in enumerate(source_rows, start=1):
            try:
                values = self._build_import_values(model_obj, field_map, row, user=user, m2o_cache=m2o_cache)
                if not values:
                    skipped_count += 1
                    continue
                if mode == "upsert":
                    key_value = values.get(key_field)
                    if not key_value:
                        skipped_count += 1
                        continue
                    existing = model_obj.search([(key_field, "=", key_value)], limit=1)
                    if existing:
                        if not dry_run:
                            existing.write(values)
                        updated_count += 1
                        if len(sample_records) < 10:
                            sample_records.append({"id": existing.id, "action": "updated", "display_name": existing.display_name})
                    else:
                        if not dry_run:
                            created = model_obj.create(values)
                            rec_id = created.id
                            display_name = created.display_name
                        else:
                            rec_id = False
                            display_name = values.get("name") or values.get("display_name") or _("New record")
                        created_count += 1
                        if len(sample_records) < 10:
                            sample_records.append({"id": rec_id, "action": "created", "display_name": display_name})
                else:
                    if not dry_run:
                        created = model_obj.create(values)
                        rec_id = created.id
                        display_name = created.display_name
                    else:
                        rec_id = False
                        display_name = values.get("name") or values.get("display_name") or _("New record")
                    created_count += 1
                    if len(sample_records) < 10:
                        sample_records.append({"id": rec_id, "action": "created", "display_name": display_name})
            except Exception as exc:  # noqa: BLE001
                error_rows.append({"row_number": index, "error": str(exc)})
                skipped_count += 1
                if len(error_rows) >= 20:
                    break

        return {
            "ok": True,
            "model": model,
            "attachment_id": attachment.id,
            "table_name": rows_result.get("table_name"),
            "mode": mode,
            "dry_run": bool(dry_run),
            "created_count": created_count,
            "updated_count": updated_count,
            "skipped_count": skipped_count,
            "total_rows": len(source_rows),
            "sample_records": sample_records,
            "errors": error_rows,
            "message": _("Imported %(total)s rows into %(model)s (created: %(created)s, updated: %(updated)s, skipped: %(skipped)s).",
                         total=len(source_rows), model=model, created=created_count, updated=updated_count, skipped=skipped_count),
        }

    # ================================================================== #
    # WRITE TOOLS (always go through approval gate via requires_approval=True)
    # ================================================================== #

    def tool_propose_reminder(self, conversation=None, user=None, text=None, due_datetime=None):
        if not text:
            return {"ok": False, "error": "text is required."}
        reminder = self.env["ob.ai.reminder"].sudo().create({
            "name": text[:120],
            "user_id": user.id, "company_id": user.company_id.id,
            "conversation_id": conversation.id if conversation else False,
            "due_datetime": due_datetime or fields.Datetime.now(),
            "status": "scheduled",
        })
        return {"ok": True, "reminder_id": reminder.id, "message": "Reminder created and scheduled."}

    def tool_propose_activity(self, conversation=None, user=None, model=None, record_id=None, summary=None, note=None, due_date=None):
        if not (model and record_id and summary):
            return {"ok": False, "error": "model, record_id, and summary are required."}
        if model not in self.env:
            return {"ok": False, "error": "Model '%s' not loaded." % model}
        record = self.env[model].with_user(user).browse(int(record_id))
        if not record.exists():
            return {"ok": False, "error": "Record not found or not accessible."}
        activity_type = self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
        vals = {
            "res_model": model, "res_id": int(record_id),
            "res_model_id": self.env["ir.model"]._get(model).id,
            "summary": summary[:200], "note": note or False,
            "date_deadline": due_date or fields.Date.today(),
            "user_id": user.id,
            "activity_type_id": activity_type.id if activity_type else False,
        }
        activity = self.env["mail.activity"].with_user(user).create(vals)
        return {"ok": True, "activity_id": activity.id, "message": "Activity created on %s,%s." % (model, record_id)}

    def tool_propose_chatter(self, conversation=None, user=None, model=None, record_id=None, body=None):
        if not (model and record_id and body):
            return {"ok": False, "error": "model, record_id, and body are required."}
        if model not in self.env:
            return {"ok": False, "error": "Model '%s' not loaded." % model}
        record = self.env[model].with_user(user).browse(int(record_id))
        if not record.exists():
            return {"ok": False, "error": "Record not found or not accessible."}
        if not hasattr(record, "message_post"):
            return {"ok": False, "error": "Model '%s' does not support chatter." % model}
        msg = record.message_post(body=body[:5000], message_type="comment")
        return {"ok": True, "message_id": msg.id, "message": "Posted to chatter on %s,%s." % (model, record_id)}

    def tool_run_validation(self, conversation=None, user=None, model=None, record_id=None):
        if not (model and record_id):
            return {"ok": False, "error": "model and record_id are required."}
        record = self.env[model].with_user(user).browse(int(record_id))
        if not record.exists():
            return {"ok": False, "error": "Record not found or not accessible."}
        try:
            result = self.env["ob.ai.validation.service"].run_validation(record, conversation=conversation)
            return {"ok": True, "validation": {
                "action_performed": result.get("action_performed"),
                "summary": result.get("summary_text"),
            }}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": "Validation failed: %s" % exc}

    # ================================================================== #
    # Internal helpers
    # ================================================================== #

    def _validate_odoo_access(self, model_name, user=None):
        user = user or self.env.user
        if not model_name:
            return {"ok": False, "error": "model is required."}
        if model_name not in self.env:
            return {"ok": False, "error": "Model '%s' is not loaded in this Odoo instance." % model_name}
        access_service = self.env["ob.ai.access.service"].with_user(user).with_company(user.company_id or self.env.company)
        try:
            allowed = access_service.get_allowed_model(model_name, user=user)
            record_model = self.env[model_name].with_user(user)
            access_service._check_read_access(record_model)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}
        return {"ok": True, "allowed": allowed}

    def _get_allowed_field_names(self, allowed_model):
        if not allowed_model:
            return []
        names = []
        if hasattr(allowed_model, "allowed_field_ids"):
            names = allowed_model.allowed_field_ids.mapped("name")
        elif hasattr(allowed_model, "allowed_fields"):
            names = [f.strip() for f in (allowed_model.allowed_fields or "").split(",") if f.strip()]
        return names

    def _sanitize_domain(self, domain):
        """Validate domain triples; reject unsafe operators or non-list shape."""
        if not isinstance(domain, list):
            return []
        sanitized = []
        for token in domain:
            if token in ("&", "|", "!"):
                sanitized.append(token)
                continue
            if not isinstance(token, (list, tuple)) or len(token) != 3:
                continue
            field_name, operator, value = token
            if not isinstance(field_name, str) or not field_name:
                continue
            op = str(operator).strip().lower()
            if op not in SAFE_DOMAIN_OPERATORS:
                continue
            sanitized.append([field_name, op, value])
        return sanitized

    def _build_import_values(self, model_obj, field_map, source_row, user=None, m2o_cache=None):
        values = {}
        m2o_cache = m2o_cache or {}
        for target_field, source_key in field_map.items():
            if target_field not in model_obj._fields:
                continue
            raw_value = self._extract_row_value(source_row, source_key)
            converted = self._convert_import_value(
                model_obj,
                target_field,
                raw_value,
                user=user,
                m2o_cache=m2o_cache,
            )
            if converted is not None:
                values[target_field] = converted
        return values

    def _extract_row_value(self, source_row, source_key):
        if isinstance(source_row, dict):
            if source_key in source_row:
                return source_row[source_key]
            return source_row.get(str(source_key))
        if isinstance(source_row, list):
            if isinstance(source_key, int) and 0 <= source_key < len(source_row):
                return source_row[source_key]
            if isinstance(source_key, str) and source_key.isdigit():
                index = int(source_key)
                if 0 <= index < len(source_row):
                    return source_row[index]
        return False

    def _convert_import_value(self, model_obj, field_name, raw_value, user=None, m2o_cache=None):
        field = model_obj._fields[field_name]
        if raw_value in (False, None, "", "null", "None"):
            return False

        if field.type in {"char", "text", "html"}:
            return str(raw_value)
        if field.type in {"float", "monetary"}:
            return self._to_float(raw_value)
        if field.type == "integer":
            return int(self._to_float(raw_value))
        if field.type == "boolean":
            return self._to_bool(raw_value)
        if field.type == "date":
            return self._to_date_string(raw_value)
        if field.type == "datetime":
            return self._to_datetime_string(raw_value)
        if field.type == "selection":
            return self._to_selection_value(field, raw_value)
        if field.type == "many2one":
            return self._to_many2one_id(field, raw_value, user=user, m2o_cache=m2o_cache)
        if field.type in {"many2many", "one2many", "binary"}:
            return None
        return raw_value

    def _to_float(self, raw_value):
        if isinstance(raw_value, (int, float)):
            return float(raw_value)
        text = str(raw_value).strip()
        cleaned = "".join(char for char in text if char.isdigit() or char in {".", "-", ","})
        cleaned = cleaned.replace(",", "")
        return float(cleaned or 0.0)

    def _to_bool(self, raw_value):
        if isinstance(raw_value, bool):
            return raw_value
        text = str(raw_value).strip().lower()
        return text in {"1", "true", "yes", "y", "done", "ok"}

    def _to_date_string(self, raw_value):
        if isinstance(raw_value, date) and not isinstance(raw_value, datetime):
            return fields.Date.to_string(raw_value)
        parsed = fields.Date.to_date(raw_value)
        return fields.Date.to_string(parsed) if parsed else False

    def _to_datetime_string(self, raw_value):
        if isinstance(raw_value, datetime):
            return fields.Datetime.to_string(raw_value)
        parsed = fields.Datetime.to_datetime(raw_value)
        return fields.Datetime.to_string(parsed) if parsed else False

    def _to_selection_value(self, field, raw_value):
        text = str(raw_value).strip()
        selection = field.selection
        if callable(selection):
            selection = selection(self.env)
        key_by_label = {}
        for key, label in selection or []:
            key_by_label[str(label).strip().lower()] = key
            if str(key) == text:
                return key
        return key_by_label.get(text.lower()) or text

    def _to_many2one_id(self, field, raw_value, user=None, m2o_cache=None):
        relation_model = self.env[field.comodel_name].with_user(user)
        m2o_cache = m2o_cache or {}
        cache_key = (field.comodel_name, str(raw_value).strip().lower())
        if cache_key in m2o_cache:
            return m2o_cache[cache_key]
        if isinstance(raw_value, int):
            record = relation_model.browse(raw_value)
            result = record.id if record.exists() else False
            m2o_cache[cache_key] = result
            return result
        text = str(raw_value).strip()
        if text.isdigit():
            record = relation_model.browse(int(text))
            if record.exists():
                m2o_cache[cache_key] = record.id
                return record.id
        match = relation_model.name_search(name=text, operator="ilike", limit=1)
        result = match[0][0] if match else False
        m2o_cache[cache_key] = result
        return result

    def _sanitize_write_values(self, model_obj, values, allowed_fields=None, user=None, m2o_cache=None):
        allowed_fields = set(allowed_fields or [])
        m2o_cache = m2o_cache or {}
        sanitized = {}
        blocked_fields = []
        unknown_fields = []
        for field_name, raw_value in (values or {}).items():
            if field_name not in model_obj._fields:
                unknown_fields.append(field_name)
                continue
            if allowed_fields and field_name not in allowed_fields:
                blocked_fields.append(field_name)
                continue
            converted = self._convert_import_value(
                model_obj,
                field_name,
                raw_value,
                user=user,
                m2o_cache=m2o_cache,
            )
            if converted is None:
                continue
            sanitized[field_name] = converted
        if unknown_fields:
            raise ValueError("Unknown fields: %s" % ", ".join(sorted(set(unknown_fields))))
        if blocked_fields:
            raise ValueError("Fields blocked by access template: %s" % ", ".join(sorted(set(blocked_fields))))
        return sanitized

    def _resolve_target_records(self, model_obj, record_ids=None, domain=None, limit=200):
        if record_ids:
            cleaned_ids = []
            for rec_id in record_ids:
                if isinstance(rec_id, int):
                    cleaned_ids.append(rec_id)
                elif isinstance(rec_id, str) and rec_id.isdigit():
                    cleaned_ids.append(int(rec_id))
            return model_obj.browse(cleaned_ids).exists()
        safe_domain = self._sanitize_domain(domain or [])
        return model_obj.search(safe_domain, limit=min(int(limit or 200), MAX_RECORD_LIMIT))

    def _safe_preview_fields(self, model_obj, allowed_fields, return_fields=None):
        request_fields = list(return_fields or ["id", "display_name"])
        if allowed_fields:
            request_fields = [field_name for field_name in request_fields if field_name in allowed_fields or field_name == "id"] or ["id", "display_name"]
        accessible = set(model_obj.fields_get(allfields=request_fields).keys())
        cleaned = [field_name for field_name in request_fields if field_name in accessible]
        if "display_name" in model_obj._fields and "display_name" not in cleaned:
            cleaned.append("display_name")
        if "id" not in cleaned:
            cleaned.insert(0, "id")
        return cleaned

    def _is_safe_business_method(self, method_name):
        method_name = (method_name or "").strip()
        if not method_name:
            return False
        if method_name.startswith("_"):
            return False
        if method_name in UNSAFE_METHOD_NAMES:
            return False
        if method_name in {"action_send_prompt"}:
            return False
        allowed_prefixes = ("action_", "button_", "open_", "run_", "approve_", "reject_", "confirm_", "compute_")
        return method_name.startswith(allowed_prefixes)

    def _jsonable_result(self, value):
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, datetime):
            return fields.Datetime.to_string(value)
        if isinstance(value, date):
            return fields.Date.to_string(value)
        if isinstance(value, models.BaseModel):
            return {
                "model": value._name,
                "count": len(value),
                "ids": value.ids[:200],
                "display_names": value.mapped("display_name")[:50],
            }
        if isinstance(value, dict):
            return {str(key): self._jsonable_result(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self._jsonable_result(item) for item in value]
        try:
            json.dumps(value, default=str)
            return value
        except Exception:  # noqa: BLE001
            return str(value)
