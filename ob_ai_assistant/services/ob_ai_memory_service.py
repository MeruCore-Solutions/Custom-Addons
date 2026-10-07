from odoo import _, fields, models
from odoo.exceptions import UserError


class OBAIMemoryService(models.AbstractModel):
    _name = "ob.ai.memory.service"
    _description = "AI Memory Service"

    def get_valid_memory_state(self, conversation, touch=False):
        conversation.ensure_one()
        memory_state = conversation.last_memory_state_id.exists()
        if not memory_state or memory_state.status != "valid":
            return self.env["ob.ai.memory.state"]
        if memory_state.user_id != conversation.user_id or memory_state.company_id != conversation.company_id:
            memory_state.sudo().write({"status": "stale"})
            return self.env["ob.ai.memory.state"]
        schema_service = self.env["ob.ai.schema.service"]
        current_schema = schema_service.get_current_version() or schema_service.ensure_current_schema(trigger_source="auto")
        if memory_state.schema_version_id and current_schema and memory_state.schema_version_id != current_schema:
            memory_state.sudo().write({"status": "stale"})
            return self.env["ob.ai.memory.state"]
        access_service = self.env["ob.ai.access.service"].with_user(conversation.user_id).with_company(conversation.company_id)
        current_signature = access_service.get_template_signature(user=conversation.user_id)
        if (memory_state.template_signature or "") != (current_signature or ""):
            memory_state.sudo().write({"status": "stale"})
            return self.env["ob.ai.memory.state"]
        if touch:
            memory_state.sudo().write({"last_used_at": fields.Datetime.now()})
        return memory_state

    def get_actionable_result_groups(self, memory_state, user=False, company=False):
        memory_state = memory_state.exists()
        if not memory_state:
            return [], []
        user = user or memory_state.user_id or self.env.user
        company = company or memory_state.company_id or user.company_id or self.env.company
        access_service = self.env["ob.ai.access.service"].with_user(user).with_company(company)
        grouped = {}
        warnings = []
        references = memory_state.result_reference_ids.sorted("sequence")
        if references:
            for reference in references:
                if not reference.model_name or not reference.record_id_value:
                    continue
                payload = grouped.setdefault(reference.model_name, {"ids": [], "references": []})
                payload["ids"].append(reference.record_id_value)
                payload["references"].append(reference)
        else:
            for record_ref in memory_state.result_record_refs or []:
                if not record_ref or "," not in record_ref:
                    continue
                model_name, record_id = record_ref.split(",", 1)
                if not record_id.isdigit():
                    continue
                payload = grouped.setdefault(model_name, {"ids": [], "references": []})
                payload["ids"].append(int(record_id))
        result_groups = []
        for model_name, payload in grouped.items():
            if model_name not in self.env:
                warnings.append(_("Model %s is no longer available in this Odoo instance.") % model_name)
                continue
            try:
                allowed_model = self._get_memory_allowed_model(memory_state, model_name, access_service, user=user)
                record_model = self.env[model_name].with_user(user).with_company(company)
                access_service._check_read_access(record_model)
            except UserError as exc:
                warnings.append(str(exc))
                continue
            visible_records = record_model.search([("id", "in", payload["ids"])])
            ordered_ids = [record_id for record_id in payload["ids"] if record_id in visible_records.ids]
            records = record_model.browse(ordered_ids)
            if not records:
                warnings.append(_("No still-visible records remain in the last AI result set for model %s.") % model_name)
                continue
            reference_map = {
                reference.record_ref: {
                    "display_name": reference.display_name,
                    "summary_line": reference.summary_line,
                }
                for reference in payload["references"]
            }
            result_groups.append({
                "model_name": model_name,
                "allowed_model": allowed_model,
                "records": records,
                "reference_map": reference_map,
            })
        return result_groups, warnings

    def _get_memory_allowed_model(self, memory_state, model_name, access_service, user=False):
        preferred_allowed_model_id = (memory_state.route_context_payload or {}).get("allowed_model_id")
        preferred_allowed_model = self.env["ob.ai.allowed.model"].browse(preferred_allowed_model_id).exists()
        if (
            preferred_allowed_model
            and preferred_allowed_model.model_id.model == model_name
            and access_service.is_allowed_model_available(preferred_allowed_model, user=user)
        ):
            return preferred_allowed_model
        matching_allowed_models = memory_state.allowed_model_ids.filtered(lambda record: record.model_id.model == model_name)
        for allowed_model in matching_allowed_models:
            if access_service.is_allowed_model_available(allowed_model, user=user):
                return allowed_model
        return access_service.get_allowed_model(model_name, user=user)

    def build_route_context(self, memory_state):
        memory_state = memory_state.exists()
        if not memory_state:
            return {}
        refs = memory_state.result_record_refs or []
        allowed_model = memory_state.allowed_model_ids[:1] if len(memory_state.allowed_model_ids) == 1 else self.env["ob.ai.allowed.model"]
        route_context = dict(memory_state.route_context_payload or {})
        route_context.update({
            "intent_code": memory_state.intent_code,
            "target_model_name": memory_state.target_model_name,
            "allowed_model_id": allowed_model.id if allowed_model else False,
            "target_record_ref": refs[0] if len(refs) == 1 else False,
            "date_scope": memory_state.date_scope or route_context.get("date_scope"),
            "generic_trace_id": memory_state.last_trace_id.id if memory_state.last_trace_id else False,
            "generic_semantic_ids": memory_state.semantic_ids.ids,
            "generic_query_type": memory_state.operation_type,
            "generic_date_scope": memory_state.date_scope,
            "generic_state_scope": memory_state.state_scope,
            "generic_multi_model": memory_state.multi_model,
            "generic_memory_state_id": memory_state.id,
        })
        return route_context

    def capture_investigation_state(self, conversation, route, trace, context_bundle, route_context_update, prompt):
        conversation.ensure_one()
        trace.ensure_one()
        previous_state = conversation.last_memory_state_id.exists()
        if previous_state and previous_state.status == "valid":
            previous_state.sudo().write({"status": "superseded"})
        access_service = self.env["ob.ai.access.service"].with_user(conversation.user_id).with_company(conversation.company_id)
        memory_state = self.env["ob.ai.memory.state"].sudo().create({
            "conversation_id": conversation.id,
            "parent_memory_state_id": previous_state.id if previous_state else False,
            "last_trace_id": trace.id,
            "company_id": conversation.company_id.id,
            "user_id": conversation.user_id.id,
            "schema_version_id": trace.schema_version_id.id if trace.schema_version_id else False,
            "semantic_ids": [(6, 0, trace.semantic_ids.ids)],
            "allowed_model_ids": [(6, 0, trace.allowed_model_ids.ids)],
            "template_signature": access_service.get_template_signature(user=conversation.user_id),
            "status": "valid",
            "intent_code": route.get("intent_code"),
            "operation_type": trace.operation_type,
            "target_model_name": route_context_update.get("target_model_name") or route.get("target_model_name"),
            "multi_model": bool(route_context_update.get("generic_multi_model")),
            "date_scope": route_context_update.get("generic_date_scope") or route.get("date_scope"),
            "state_scope": route_context_update.get("generic_state_scope"),
            "domain_payload": {
                "steps": trace.steps_json or [],
                "selected_record_refs": trace.selected_record_refs or [],
            },
            "result_record_refs": trace.selected_record_refs or [],
            "route_context_payload": route_context_update or {},
            "summary_excerpt": trace.final_summary,
            "last_prompt": prompt,
            "last_used_at": fields.Datetime.now(),
            "step_count": trace.step_count,
        })
        self._store_result_references(memory_state, trace, context_bundle)
        return memory_state

    def _store_result_references(self, memory_state, trace, context_bundle):
        rows = context_bundle.get("records") or []
        references = []
        for index, row in enumerate(rows, start=1):
            model_name = row.get("_model")
            record_id = row.get("id")
            if model_name and record_id:
                references.append({
                    "memory_state_id": memory_state.id,
                    "trace_id": trace.id,
                    "conversation_id": memory_state.conversation_id.id,
                    "company_id": memory_state.company_id.id,
                    "user_id": memory_state.user_id.id,
                    "sequence": index,
                    "model_name": model_name,
                    "record_id_value": int(record_id),
                    "record_ref": "%s,%s" % (model_name, record_id),
                    "display_name": row.get("display_name") or row.get("name"),
                    "summary_line": self._summary_line(row),
                })
        if not references:
            for index, record_ref in enumerate(trace.selected_record_refs or [], start=1):
                if "," not in record_ref:
                    continue
                model_name, record_id = record_ref.split(",", 1)
                if not record_id.isdigit():
                    continue
                references.append({
                    "memory_state_id": memory_state.id,
                    "trace_id": trace.id,
                    "conversation_id": memory_state.conversation_id.id,
                    "company_id": memory_state.company_id.id,
                    "user_id": memory_state.user_id.id,
                    "sequence": index,
                    "model_name": model_name,
                    "record_id_value": int(record_id),
                    "record_ref": record_ref,
                })
        if references:
            self.env["ob.ai.result.reference"].sudo().create(references)

    def _summary_line(self, row):
        preview_parts = []
        for field_name in ("display_name", "name", "state", "status"):
            if row.get(field_name):
                preview_parts.append(str(row[field_name]))
        return " | ".join(preview_parts[:3]) or False
