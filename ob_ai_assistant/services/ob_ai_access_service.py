from odoo import _, models
from odoo.fields import Domain
from odoo.exceptions import AccessError, UserError


CAPABILITY_FIELD_MAP = {
    "document_context": "allow_document_context",
    "dashboard": "allow_dashboard_generation",
    "validation": "allow_validation",
    "activity": "allow_activity_creation",
    "reminder": "allow_reminder_creation",
    "chatter": "allow_chatter_posting",
}

CAPABILITY_LABELS = {
    "document_context": "document summaries",
    "dashboard": "dashboards and KPI answers",
    "validation": "validation checks",
    "activity": "follow-up activities",
    "reminder": "reminders",
    "chatter": "chatter notes",
}


class OBAIAccessService(models.AbstractModel):
    _name = "ob.ai.access.service"
    _description = "AI Access Service"

    def build_conversation_context(self, conversation):
        conversation.ensure_one()
        if conversation.related_record_ref:
            return self.build_record_context(conversation.related_record_ref, allowed_model=conversation.allowed_model_id or False)
        if conversation.allowed_model_id:
            return self.build_recent_records_context(conversation.allowed_model_id)
        return self._empty_context()

    def build_recent_records_context(self, allowed_model):
        allowed_model.ensure_one()
        policy = self.get_model_access_policy(allowed_model)
        model_name = allowed_model.model_id.model
        record_model = self.env[model_name]
        self._check_read_access(record_model)
        record_limit = max(policy.get("max_record_count") or 1, 1)
        records = record_model.search(
            [],
            limit=record_limit,
            order=policy.get("default_order") or allowed_model.default_order or "write_date desc, id desc",
        )
        return self._build_context_from_records(records, allowed_model, source="recent_records", access_policy=policy)

    def build_record_context(self, record, allowed_model=False):
        record = record.exists()
        if not record:
            raise UserError(_("The selected Odoo record no longer exists."))
        allowed_model = allowed_model or self.get_allowed_model(record._name)
        policy = self.get_model_access_policy(allowed_model)
        return self._build_context_from_records(record, allowed_model, source="related_record", access_policy=policy)

    def build_search_context(self, allowed_model, domain=None, limit=False, order=False, source="search_result"):
        allowed_model.ensure_one()
        policy = self.get_model_access_policy(allowed_model)
        record_model = self.env[allowed_model.model_id.model]
        self._check_read_access(record_model)
        limit = limit or policy.get("search_limit") or policy.get("max_record_count") or 5
        order = order or policy.get("default_order") or allowed_model.default_order or "write_date desc, id desc"
        records = record_model.search(domain or [], limit=limit, order=order)
        return self._build_context_from_records(records, allowed_model, source=source, access_policy=policy)

    def search_records_by_term(self, allowed_model, search_term, limit=5, extra_domain=None, use_name_fields=False):
        allowed_model.ensure_one()
        policy = self.get_model_access_policy(allowed_model)
        term = (search_term or "").strip()
        if not term:
            return self.env[allowed_model.model_id.model].browse()
        record_model = self.env[allowed_model.model_id.model]
        self._check_read_access(record_model)
        configured_fields = policy.get("name_field_names") if use_name_fields else policy.get("reference_field_names")
        field_names = self._parse_field_names(configured_fields)
        if not field_names:
            field_names = ["display_name", "name"]
        domain_parts = [Domain(field_name, "ilike", term) for field_name in field_names]
        search_domain = Domain.OR(domain_parts)
        if extra_domain:
            search_domain &= Domain(extra_domain)
        return record_model.search(
            search_domain,
            limit=limit or policy.get("search_limit") or 5,
            order=policy.get("default_order") or allowed_model.default_order or "write_date desc, id desc",
        )

    def get_user_templates(self, user=False):
        user = user or self.env.user
        domain = [("active", "=", True), ("user_ids", "in", user.id)]
        if self.env.company:
            domain += ["|", ("company_id", "=", False), ("company_id", "=", self.env.company.id)]
        templates = self.env["ob.ai.access.template"].sudo().search(domain, order="company_id desc, sequence, id")
        if templates and not self.env.context.get("ob_ai_skip_template_sync"):
            templates.with_context(ob_ai_skip_template_sync=True).action_sync_model_lines()
        return templates

    def get_template_signature(self, user=False):
        templates = self.get_user_templates(user=user)
        return "|".join(
            "%s:%s" % (template.id, template.write_date.isoformat() if template.write_date else "")
            for template in templates
        )

    def user_has_full_access(self, user=False):
        return bool(self.get_user_templates(user=user).filtered("allow_full_access")[:1])

    def available_allowed_models(self, user=False):
        user = user or self.env.user
        self.env["ob.ai.allowed.model"].sudo().ensure_default_models()
        domain = [("active", "=", True)]
        if self.env.company:
            domain += ["|", ("company_id", "=", False), ("company_id", "=", self.env.company.id)]
        base_models = self._filter_queryable_allowed_models(
            self.env["ob.ai.allowed.model"].search(domain, order="company_id desc, sequence, id")
        )
        templates = self.get_user_templates(user=user)
        if templates.filtered("allow_full_access"):
            return base_models
        if not templates:
            return base_models
        template_lines = templates.mapped("line_ids").filtered(lambda line: line.active and line.allowed_model_id.active)
        return self._filter_queryable_allowed_models(template_lines.mapped("allowed_model_id")).sorted(
            key=lambda record: (0 if record.company_id else 1, record.sequence, record.id)
        )

    def is_allowed_model_available(self, allowed_model, user=False):
        allowed_model = allowed_model.exists()
        if not allowed_model:
            return False
        return allowed_model in self.available_allowed_models(user=user)

    def find_allowed_model_for_model_names(self, model_names, user=False):
        if not model_names:
            return self.env["ob.ai.allowed.model"]
        user = user or self.env.user
        available_models = self.available_allowed_models(user=user)
        matched = available_models.filtered(lambda record: record.model_id.model in model_names)
        if matched:
            return matched
        if self._allow_admin_global_scope(user):
            created_models = self.env["ob.ai.allowed.model"]
            for model_name in model_names:
                created_models |= self._ensure_allowed_model_for_admin(model_name)
            if created_models:
                available_models |= created_models
                matched = available_models.filtered(lambda record: record.model_id.model in model_names)
        return matched

    def get_allowed_model(self, model_name, user=False):
        user = user or self.env.user
        allowed_model = self.find_allowed_model_for_model_names([model_name], user=user)[:1]
        if not allowed_model:
            raise UserError(_("Model %s is not whitelisted for AI access.") % model_name)
        return allowed_model

    def get_model_access_policy(self, allowed_model, user=False):
        allowed_model = allowed_model.exists()
        if not allowed_model:
            raise UserError(_("No allowed-model configuration is available for this AI request."))
        user = user or self.env.user
        templates = self.get_user_templates(user=user)
        full_access_template = templates.filtered("allow_full_access")[:1]
        if full_access_template:
            return self._full_access_policy_from_allowed_model(allowed_model, template=full_access_template)
        if not templates:
            return self._policy_from_allowed_model(allowed_model)

        # When several templates cover the same model, the earliest template/line wins.
        template_lines = templates.mapped("line_ids").filtered(
            lambda line: line.active and line.allowed_model_id == allowed_model and line.allowed_model_id.active
        ).sorted(
            key=lambda line: (0 if line.template_id.company_id else 1, line.template_id.sequence, line.sequence, line.id)
        )
        if not template_lines:
            raise UserError(_("Model %s is not available in your AI access templates.") % allowed_model.display_name)
        return self._policy_from_template_line(template_lines[:1], allowed_model)

    def has_model_capability(self, allowed_model, capability, user=False):
        if not allowed_model:
            return True
        field_name = CAPABILITY_FIELD_MAP.get(capability)
        if not field_name:
            return True
        policy = self.get_model_access_policy(allowed_model, user=user)
        return bool(policy.get(field_name))

    def ensure_model_capability(self, allowed_model, capability, user=False):
        if not allowed_model:
            return True
        if self.has_model_capability(allowed_model, capability, user=user):
            return True
        raise UserError(
            _("Model %s is not allowed to use %s through the AI access policy.")
            % (allowed_model.display_name, _(CAPABILITY_LABELS.get(capability, capability)))
        )

    def get_allowed_field_names(self, allowed_model, policy=False):
        allowed_model = allowed_model.exists()
        if not allowed_model:
            return []
        policy = policy or self.get_model_access_policy(allowed_model)
        field_names = set(
            policy.get("allowed_field_ids").filtered(lambda field: field.ttype != "binary").mapped("name")
        )
        if not field_names and not policy.get("template_line"):
            field_names = set(allowed_model._default_allowed_field_names(allowed_model.model_id.model))
        field_names -= set(policy.get("blocked_field_ids").mapped("name"))
        field_names.add("display_name")
        return sorted(field_names)

    def _policy_from_allowed_model(self, allowed_model):
        return {
            "source": "allowed_model",
            "template": False,
            "template_line": False,
            "allowed_field_ids": allowed_model.allowed_field_ids,
            "blocked_field_ids": allowed_model.blocked_field_ids,
            "max_record_count": allowed_model.max_record_count,
            "search_limit": allowed_model.search_limit,
            "default_order": allowed_model.default_order,
            "reference_field_names": allowed_model.reference_field_names,
            "name_field_names": allowed_model.name_field_names,
            "date_field_names": allowed_model.date_field_names,
            "allow_document_context": allowed_model.allow_document_context,
            "allow_chatter_posting": allowed_model.allow_chatter_posting,
            "allow_activity_creation": allowed_model.allow_activity_creation,
            "allow_reminder_creation": allowed_model.allow_reminder_creation,
            "allow_dashboard_generation": allowed_model.allow_dashboard_generation,
            "allow_validation": allowed_model.allow_validation,
            "require_human_approval": allowed_model.require_human_approval,
            "sensitivity_level": allowed_model.sensitivity_level,
        }

    def _full_access_policy_from_allowed_model(self, allowed_model, template=False):
        all_fields = self.env["ir.model.fields"].sudo().search([
            ("model_id", "=", allowed_model.model_id.id),
            ("ttype", "!=", "binary"),
        ])
        base_policy = self._policy_from_allowed_model(allowed_model)
        base_policy.update({
            "source": "full_access_template",
            "template": template,
            "allowed_field_ids": all_fields,
            "blocked_field_ids": self.env["ir.model.fields"],
            "max_record_count": max(allowed_model.max_record_count or 0, 50),
            "search_limit": max(allowed_model.search_limit or 0, 50),
        })
        return base_policy

    def _policy_from_template_line(self, line, allowed_model):
        return {
            "source": "template",
            "template": line.template_id,
            "template_line": line,
            "allowed_field_ids": line.allowed_field_ids,
            "blocked_field_ids": line.blocked_field_ids,
            "max_record_count": line.max_record_count,
            "search_limit": line.search_limit,
            "default_order": line.default_order,
            "reference_field_names": line.reference_field_names,
            "name_field_names": line.name_field_names,
            "date_field_names": line.date_field_names,
            "allow_document_context": line.allow_document_context,
            "allow_chatter_posting": line.allow_chatter_posting,
            "allow_activity_creation": line.allow_activity_creation,
            "allow_reminder_creation": line.allow_reminder_creation,
            "allow_dashboard_generation": line.allow_dashboard_generation,
            "allow_validation": line.allow_validation,
            "require_human_approval": line.require_human_approval,
            "sensitivity_level": line.sensitivity_level or allowed_model.sensitivity_level,
        }

    def _build_context_from_records(self, records, allowed_model, source, access_policy=False):
        records = records.exists()
        if not allowed_model:
            raise UserError(_("No allowed-model configuration was found for %s.") % records._name)
        access_policy = access_policy or self.get_model_access_policy(allowed_model)
        self._check_read_access(records)
        field_names, blocked_fields = self._resolve_fields(records, allowed_model, access_policy=access_policy)
        rows = records.read(field_names, load=None) if records else []
        sanitized_rows = [self._sanitize_row(row) for row in rows]
        model_name = records._name if records else allowed_model.model_id.model
        return {
            "source": source,
            "records": sanitized_rows,
            "accessed_models": [model_name],
            "accessed_record_ids": {model_name: records.ids},
            "accessed_fields": {model_name: field_names},
            "blocked_fields": {model_name: blocked_fields},
            "hidden_record_count": 0,
        }

    def _check_read_access(self, record_model):
        if getattr(record_model, "_abstract", False):
            raise UserError(_("Model %s is abstract and cannot be queried through AI access.") % record_model._name)
        if not self._model_storage_available(record_model._name):
            raise UserError(_("Model %s is currently unavailable for AI access because its storage is missing.") % record_model._name)
        try:
            record_model.check_access("read")
        except AccessError as exc:
            raise UserError(_("You do not have read access to %s.") % record_model._name) from exc

    def _filter_queryable_allowed_models(self, allowed_models):
        allowed_models = allowed_models.exists()
        if not allowed_models:
            return allowed_models
        queryable_model_names = self._queryable_model_names(allowed_models.mapped("model_id.model"))
        return allowed_models.filtered(lambda record: record.model_id.model in queryable_model_names)

    def _queryable_model_names(self, model_names):
        model_names = [model_name for model_name in set(model_names or []) if model_name and model_name in self.env]
        if not model_names:
            return set()
        table_by_model = {}
        for model_name in model_names:
            model = self.env[model_name]
            if getattr(model, "_abstract", False):
                continue
            table_name = getattr(model, "_table", False)
            if not table_name:
                continue
            table_by_model[model_name] = table_name
        if not table_by_model:
            return set()
        self.env.cr.execute(
            "SELECT relname FROM pg_class WHERE relname = ANY(%s)",
            [list(set(table_by_model.values()))],
        )
        available_tables = {row[0] for row in self.env.cr.fetchall()}
        return {
            model_name
            for model_name, table_name in table_by_model.items()
            if table_name in available_tables
        }

    def _model_storage_available(self, model_name):
        return model_name in self._queryable_model_names([model_name])

    def _resolve_fields(self, records, allowed_model, access_policy=False):
        access_policy = access_policy or self._policy_from_allowed_model(allowed_model)
        allowed_fields = access_policy.get("allowed_field_ids").filtered(lambda field: field.ttype != "binary")
        if not allowed_fields and not access_policy.get("template_line"):
            allowed_fields = self.env["ir.model.fields"].sudo().search([
                ("model_id", "=", allowed_model.model_id.id),
                ("name", "in", allowed_model._default_allowed_field_names(allowed_model.model_id.model)),
                ("ttype", "!=", "binary"),
            ])
        blocked_names = set(access_policy.get("blocked_field_ids").mapped("name"))
        binary_blocked = set(access_policy.get("allowed_field_ids").filtered(lambda field: field.ttype == "binary").mapped("name"))
        blocked_names |= binary_blocked
        field_names = [field.name for field in allowed_fields if field.name not in blocked_names]
        if "display_name" not in field_names:
            field_names.insert(0, "display_name")
        accessible_fields = set(records.fields_get(allfields=field_names).keys())
        field_names = [field_name for field_name in field_names if field_name in accessible_fields]
        field_names = [field_name for field_name in field_names if field_name not in blocked_names]
        return field_names, sorted(blocked_names)

    def _sanitize_row(self, row):
        sanitized = {}
        for key, value in row.items():
            if isinstance(value, bytes):
                sanitized[key] = "<binary>"
            else:
                sanitized[key] = value
        return sanitized

    def _parse_field_names(self, field_string):
        return [field_name.strip() for field_name in (field_string or "").split(",") if field_name.strip()]

    def _allow_admin_global_scope(self, user):
        enabled = self.env["ir.config_parameter"].sudo().get_param(
            "ob_ai_assistant.admin_global_scope_enabled",
            default="True",
        ) == "True"
        if not enabled:
            return False
        if not self.user_has_full_access(user=user):
            return False
        return bool(
            user.has_group("base.group_system")
            or user.has_group("ob_ai_assistant.group_ai_administrator")
        )

    def _ensure_allowed_model_for_admin(self, model_name):
        if not model_name or model_name not in self.env:
            return self.env["ob.ai.allowed.model"]
        if not self._model_storage_available(model_name):
            return self.env["ob.ai.allowed.model"]
        ir_model = self.env["ir.model"].sudo()._get(model_name)
        if not ir_model:
            return self.env["ob.ai.allowed.model"]
        domain = [("model_id", "=", ir_model.id)]
        if self.env.company:
            domain += ["|", ("company_id", "=", False), ("company_id", "=", self.env.company.id)]
        allowed_model = self.env["ob.ai.allowed.model"].sudo().search(domain, limit=1)
        if allowed_model:
            return allowed_model
        helper_model = self.env["ob.ai.allowed.model"]
        field_ids = self.env["ir.model.fields"].sudo().search([
            ("model_id", "=", ir_model.id),
            ("name", "in", helper_model._default_allowed_field_names(model_name)),
            ("ttype", "!=", "binary"),
        ])
        return self.env["ob.ai.allowed.model"].sudo().create({
            "name": ir_model.name or model_name,
            "model_id": ir_model.id,
            "company_id": self.env.company.id if self.env.company else False,
            "alias_keywords": (ir_model.name or "").lower().replace("/", " "),
            "allowed_field_ids": [(6, 0, field_ids.ids)],
            "reference_field_names": "name,display_name",
            "name_field_names": "name,display_name",
            "allow_document_context": True,
            "allow_chatter_posting": True,
            "allow_activity_creation": True,
            "allow_reminder_creation": True,
            "allow_dashboard_generation": True,
            "allow_validation": True,
        })

    def _empty_context(self):
        return {
            "source": "none",
            "records": [],
            "accessed_models": [],
            "accessed_record_ids": {},
            "accessed_fields": {},
            "blocked_fields": {},
            "hidden_record_count": 0,
        }
