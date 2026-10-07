import re

from odoo import _, fields, models


ROLE_KEYWORD_MAP = {
    "sales": ["sale", "sales", "booking", "quotation", "order"],
    "crm": ["crm", "lead", "opportunity", "pipeline", "deal"],
    "finance": ["invoice", "payment", "receivable", "bill", "finance", "accounting"],
    "inventory": ["delivery", "shipment", "stock", "inventory", "picking", "warehouse"],
    "procurement": ["purchase", "vendor", "procurement", "supplier"],
    "hr": ["employee", "leave", "staff", "attendance", "time off"],
    "project": ["project", "task", "milestone", "timesheet"],
    "support": ["ticket", "issue", "support", "helpdesk"],
    "custom": ["custom", "platform"],
}

CUSTOMER_TERMS = {"customer", "customers", "client", "clients", "partner", "partners", "contact", "contacts"}
BEHAVIOUR_TERMS = {"behavior", "behaviour", "engagement", "retention", "journey", "segment", "segmentation", "loyalty", "churn"}
INTERNAL_AI_TERMS = {
    "approval",
    "approvals",
    "audit",
    "audit log",
    "reminder",
    "reminders",
    "validation",
    "validations",
    "snapshot",
    "snapshots",
    "trace",
    "traces",
    "memory state",
    "conversation log",
}

FIELD_CANDIDATES = {
    "title_field_names": ["name", "display_name", "subject", "reference", "code", "number"],
    "state_field_names": ["state", "status", "activity_state"],
    "stage_field_names": ["stage_id", "stage", "kanban_state"],
    "amount_field_names": ["amount_total", "amount_untaxed", "amount_residual", "expected_revenue", "price_total", "balance"],
    "currency_field_names": ["currency_id", "company_currency", "company_currency_id"],
    "primary_date_field_names": ["date_order", "invoice_date", "date", "scheduled_date", "request_date_from", "date_open", "create_date", "write_date"],
    "due_date_field_names": ["date_deadline", "invoice_date_due", "commitment_date", "scheduled_date", "request_date_to", "date_closed"],
    "owner_field_names": ["user_id", "responsible_id", "assigned_user_id", "employee_id", "parent_id"],
    "partner_field_names": ["partner_id", "partner_name", "contact_name", "commercial_partner_id", "customer_id"],
    "priority_field_names": ["priority"],
    "probability_field_names": ["probability"],
    "description_field_names": ["description", "narration", "note", "memo", "origin", "ref"],
}

OPEN_STATE_TERMS = {"draft", "new", "open", "pending", "progress", "quotation", "sent", "assigned", "confirm", "waiting"}
CLOSED_STATE_TERMS = {"done", "closed", "complete", "won", "paid", "posted", "approved", "lost", "cancel", "cancelled", "refused"}
INACTIVE_STATE_TERMS = {"done", "closed", "lost", "cancel", "cancelled", "inactive", "archived"}
BUSINESS_DOMAIN_HINTS = {
    "sale",
    "sales",
    "revenue",
    "booking",
    "order",
    "quotation",
    "invoice",
    "billing",
    "account",
    "finance",
    "delivery",
    "shipment",
    "stock",
    "inventory",
    "warehouse",
    "crm",
    "lead",
    "opportunity",
    "pipeline",
    "customer",
    "customers",
    "partner",
}


class OBAISemanticService(models.AbstractModel):
    _name = "ob.ai.semantic.service"
    _description = "AI Semantic Service"

    def ensure_default_semantics(self, schema_version=False, force_update=False):
        return self.sync_semantics(schema_version=schema_version, force_update=force_update)

    def sync_semantics(self, schema_version=False, force_update=False, semantics=False):
        schema_version = schema_version or self.env["ob.ai.schema.service"].ensure_current_schema(trigger_source="auto")
        allowed_models = semantics.mapped("allowed_model_id") if semantics else self.env["ob.ai.allowed.model"].search(
            [("active", "=", True)],
            order="company_id desc, sequence, id",
        )
        semantic_model = self.env["ob.ai.model.semantic"].sudo().with_context(active_test=False)
        existing = semantic_model.search([("allowed_model_id", "in", allowed_models.ids)])
        by_allowed_model = {record.allowed_model_id.id: record for record in existing}
        schema_models = self._schema_models_by_name(schema_version)
        created_or_updated = semantic_model.browse()
        for allowed_model in allowed_models:
            values = self._build_semantic_values(allowed_model, schema_models.get(allowed_model.model_id.model))
            values["schema_version_id"] = schema_version.id if schema_version else False
            record = by_allowed_model.get(allowed_model.id)
            if not record:
                created_or_updated |= semantic_model.create(values)
            elif force_update or record.auto_generated:
                record.write(values)
                created_or_updated |= record
        return created_or_updated

    def get_semantic_for_allowed_model(self, allowed_model, ensure=True):
        allowed_model = allowed_model.exists()
        if not allowed_model:
            return self.env["ob.ai.model.semantic"]
        semantic_model = self.env["ob.ai.model.semantic"].sudo().with_context(active_test=False)
        semantic = semantic_model.search([("allowed_model_id", "=", allowed_model.id)], limit=1)
        if semantic or not ensure:
            return semantic
        self.sync_semantics()
        return semantic_model.search([("allowed_model_id", "=", allowed_model.id)], limit=1)

    def available_semantics(self, user=False):
        user = user or self.env.user
        access_service = self.env["ob.ai.access.service"].with_user(user).with_company(user.company_id)
        allowed_models = access_service.available_allowed_models(user=user)
        self.ensure_default_semantics()
        domain = [("active", "=", True), ("generic_query_enabled", "=", True), ("allowed_model_id", "in", allowed_models.ids)]
        return self.env["ob.ai.model.semantic"].sudo().search(domain, order="company_id desc, sequence, id")

    def has_generic_candidate(self, normalized_prompt, conversation=False, user=False, last_route=False):
        user = user or (conversation.user_id if conversation else self.env.user)
        if conversation and (conversation.allowed_model_id or conversation.related_record_ref):
            return True
        if last_route and last_route.get("intent_code") == "generic_investigation":
            return True
        return bool(self.match_semantics(
            normalized_prompt,
            conversation=conversation,
            user=user,
            last_route=last_route,
            limit=1,
        ))

    def match_semantics(
        self,
        normalized_prompt,
        conversation=False,
        user=False,
        last_route=False,
        limit=False,
        prefer_related_record=True,
        prefer_conversation_model=True,
        prefer_last_route=True,
        allow_internal_models=True,
    ):
        user = user or (conversation.user_id if conversation else self.env.user)
        semantics = self.available_semantics(user=user)
        if not semantics:
            return semantics
        if not allow_internal_models:
            semantics = semantics.filtered(lambda record: not self._is_internal_ai_model(record.model_id.model))
            if not semantics:
                return semantics
        if conversation and prefer_related_record and conversation.related_record_ref:
            semantic = semantics.filtered(lambda record: record.allowed_model_id.model_id.model == conversation.related_record_ref._name)[:1]
            if semantic:
                return semantic
        if conversation and prefer_conversation_model and conversation.allowed_model_id:
            semantic = semantics.filtered(lambda record: record.allowed_model_id == conversation.allowed_model_id)[:1]
            if semantic:
                return semantic
        if prefer_last_route and last_route and last_route.get("intent_code") == "generic_investigation" and last_route.get("generic_semantic_ids"):
            semantic_ids = last_route.get("generic_semantic_ids") or []
            matched = semantics.browse(semantic_ids).exists()
            if matched:
                return matched[: limit or len(matched)]
        normalized_prompt = (normalized_prompt or "").strip().lower()
        scored = []
        for semantic in semantics:
            score = self._semantic_score(semantic, normalized_prompt)
            if score > 0:
                scored.append((score, semantic.sequence, semantic.id))
        if not scored:
            return semantics[:1] if len(semantics) == 1 else self.env["ob.ai.model.semantic"]
        scored.sort(key=lambda item: (-item[0], item[1], item[2]))
        ordered_ids = [semantic_id for _, _, semantic_id in scored[: limit or len(scored)]]
        return self.env["ob.ai.model.semantic"].sudo().browse(ordered_ids)

    def get_runtime_semantic(self, semantic, user=False):
        semantic.ensure_one()
        user = user or self.env.user
        access_service = self.env["ob.ai.access.service"].with_user(user).with_company(user.company_id)
        policy = access_service.get_model_access_policy(semantic.allowed_model_id, user=user)
        allowed_field_names = set(access_service.get_allowed_field_names(semantic.allowed_model_id, policy=policy))
        model = self.env[semantic.model_id.model]
        payload = {
            "semantic_id": semantic.id,
            "allowed_model_id": semantic.allowed_model_id.id,
            "model": semantic.model_id.model,
            "label": semantic.business_label or semantic.allowed_model_id.name or semantic.model_id.display_name,
            "role": semantic.semantic_role,
            "default_sort_field": semantic.default_sort_field,
            "open_state_values": self._split_csv(semantic.open_state_values),
            "closed_state_values": self._split_csv(semantic.closed_state_values),
            "inactive_state_values": self._split_csv(semantic.inactive_state_values),
            "field_types": {},
        }
        for field_group in FIELD_CANDIDATES:
            field_names = [name for name in self._split_csv(getattr(semantic, field_group)) if name in allowed_field_names and name in model._fields]
            payload[field_group] = field_names
            for field_name in field_names:
                payload["field_types"][field_name] = model._fields[field_name].type
        return payload

    def _schema_models_by_name(self, schema_version):
        if not schema_version:
            return {}
        return {record.model_name: record for record in schema_version.schema_model_ids}

    def _build_semantic_values(self, allowed_model, schema_model=False):
        values = {
            "name": _("%s Semantics", allowed_model.display_name),
            "sequence": allowed_model.sequence,
            "company_id": allowed_model.company_id.id or False,
            "allowed_model_id": allowed_model.id,
            "business_label": allowed_model.name or allowed_model.model_id.display_name,
            "semantic_role": self._guess_role(allowed_model),
            "generic_query_enabled": True,
            "allow_cross_model": True,
            "default_sort_field": self._guess_default_sort_field(allowed_model),
            "semantic_hints": allowed_model.alias_keywords,
        }
        schema_fields = {field.name: field for field in schema_model.field_ids} if schema_model else {}
        for field_name, candidates in FIELD_CANDIDATES.items():
            selected = [candidate for candidate in candidates if candidate in schema_fields]
            values[field_name] = ",".join(selected[:3]) if selected else False
        values["open_state_values"] = self._guess_state_values(schema_fields, values.get("state_field_names"), OPEN_STATE_TERMS)
        values["closed_state_values"] = self._guess_state_values(schema_fields, values.get("state_field_names"), CLOSED_STATE_TERMS)
        values["inactive_state_values"] = self._guess_state_values(schema_fields, values.get("state_field_names"), INACTIVE_STATE_TERMS)
        return values

    def _guess_role(self, allowed_model):
        model_name = allowed_model.model_id.model or ""
        if model_name.startswith("sale."):
            return "sales"
        if model_name.startswith("crm."):
            return "crm"
        if model_name.startswith("account."):
            return "finance"
        if model_name.startswith("stock."):
            return "inventory"
        if model_name.startswith("purchase."):
            return "procurement"
        if model_name.startswith("hr."):
            return "hr"
        if model_name.startswith("project."):
            return "project"
        if model_name.startswith("helpdesk.") or model_name.startswith("desk."):
            return "support"
        if allowed_model.model_id.modules and "ob_" in allowed_model.model_id.modules:
            return "custom"
        return "generic"

    def _guess_default_sort_field(self, allowed_model):
        order = (allowed_model.default_order or "").split(",")[0].strip()
        if not order:
            return False
        return order.split()[0]

    def _guess_state_values(self, schema_fields, state_field_names, match_terms):
        for field_name in self._split_csv(state_field_names):
            schema_field = schema_fields.get(field_name)
            if not schema_field or not schema_field.selection_json:
                continue
            values = []
            for option in schema_field.selection_json:
                haystack = " ".join([
                    str(option.get("value") or "").lower(),
                    str(option.get("label") or "").lower(),
                ])
                if any(term in haystack for term in match_terms):
                    values.append(str(option.get("value")))
            if values:
                return ",".join(values)
        return False

    def _semantic_score(self, semantic, normalized_prompt):
        if not normalized_prompt:
            return 0
        score = 0
        tokens = set(self._tokenize(normalized_prompt))
        normalized_prompt = normalized_prompt.lower()
        model_name = semantic.model_id.model or ""
        aliases = [alias.strip().lower() for alias in (semantic.allowed_model_id.alias_keywords or "").split(",") if alias.strip()]
        labels = [
            (semantic.business_label or "").lower(),
            (semantic.name or "").lower(),
            (semantic.allowed_model_id.name or "").lower(),
            (semantic.model_id.name or "").lower(),
            (semantic.model_id.model or "").replace(".", " ").lower(),
            (semantic.semantic_hints or "").lower(),
        ]
        for phrase in aliases + labels:
            if not phrase:
                continue
            if self._phrase_in_prompt(phrase, normalized_prompt, tokens):
                score += 6 if " " in phrase else 3
        for role_keyword in ROLE_KEYWORD_MAP.get(semantic.semantic_role, []):
            if self._phrase_in_prompt(role_keyword, normalized_prompt, tokens):
                score += 3
        title_fields = set(self._split_csv(semantic.title_field_names))
        if CUSTOMER_TERMS & tokens and "name" in title_fields:
            score += 2
        if CUSTOMER_TERMS & tokens:
            if model_name == "res.partner":
                score += 8
            elif model_name == "crm.lead":
                score += 6
            elif semantic.semantic_role in {"crm", "sales"}:
                score += 3
        if BEHAVIOUR_TERMS & tokens:
            if model_name == "res.partner":
                score += 6
            elif model_name == "crm.lead":
                score += 5
            elif semantic.semantic_role in {"crm", "sales"}:
                score += 2
        if {"status", "summary", "overview", "briefing", "brief"} & tokens:
            score += 1
        if self._is_technical_platform_model(model_name) and tokens & BUSINESS_DOMAIN_HINTS:
            score -= 6
        return score

    def _split_csv(self, value):
        return [item.strip() for item in (value or "").split(",") if item.strip()]

    def _tokenize(self, text):
        return re.findall(r"[a-z0-9_]+", (text or "").lower())

    def _phrase_in_prompt(self, phrase, normalized_prompt, prompt_tokens):
        phrase = re.sub(r"\s+", " ", (phrase or "").strip().lower())
        if not phrase:
            return False
        phrase_tokens = self._tokenize(phrase)
        if not phrase_tokens:
            return False
        if len(phrase_tokens) == 1:
            return phrase_tokens[0] in prompt_tokens
        pattern = r"\b%s\b" % r"\s+".join(re.escape(token) for token in phrase_tokens)
        return bool(re.search(pattern, normalized_prompt))

    def _is_technical_platform_model(self, model_name):
        if not model_name:
            return False
        if model_name.startswith("ob.ai."):
            return False
        technical_prefixes = ("ir.", "base.", "web.", "bus.", "report.")
        technical_models = {
            "mail.channel",
            "mail.channel.member",
            "mail.message.schedule",
            "mail.message.translation",
            "res.config.settings",
            "ir.ui.view",
            "ir.model",
            "ir.model.fields",
            "ir.module.module",
        }
        return model_name.startswith(technical_prefixes) or model_name in technical_models

    def _is_internal_ai_model(self, model_name):
        return bool(model_name and model_name.startswith("ob.ai."))

    def _targets_internal_ai_model(self, normalized_prompt):
        return any(term in (normalized_prompt or "") for term in INTERNAL_AI_TERMS)
