from odoo import _, fields, models
from odoo.exceptions import UserError


class OBAIValidationService(models.AbstractModel):
    _name = "ob.ai.validation.service"
    _description = "AI Validation Service"

    def run_validation(self, record, conversation=False):
        record = record.exists()
        if not record:
            raise UserError(_("Select a related Odoo record before requesting validation."))
        rules = self.env["ob.ai.validation.rule"].search(
            [
                ("active", "=", True),
                ("target_model_id.model", "=", record._name),
                "|",
                ("company_id", "=", False),
                ("company_id", "=", self.env.company.id),
            ],
            order="sequence, id",
        )
        results = self.env["ob.ai.validation.result"]
        if not rules:
            results |= self.env["ob.ai.validation.result"].create({
                "company_id": self.env.company.id,
                "source_conversation_id": conversation.id if conversation else False,
                "related_record_ref": "%s,%s" % (record._name, record.id),
                "record_model": record._name,
                "record_res_id": record.id,
                "validation_status": "warning",
                "ai_explanation": _("No validation rules are configured for %s yet.", record._name),
                "suggested_action": _("Create at least one validation rule for this model."),
                "review_status": "draft",
            })
            return {
                "action_performed": "validation_completed",
                "results": results,
                "summary_text": _("No validation rules are configured for %s.", record.display_name),
                "review_status": "draft",
            }
        for rule in rules:
            status, explanation, suggested_action, payload = self._evaluate_rule(record, rule)
            review_status = "pending_review" if rule.requires_approval and status in ("warning", "fail") else "draft"
            results |= self.env["ob.ai.validation.result"].create({
                "company_id": self.env.company.id,
                "source_conversation_id": conversation.id if conversation else False,
                "related_record_ref": "%s,%s" % (record._name, record.id),
                "record_model": record._name,
                "record_res_id": record.id,
                "rule_id": rule.id,
                "validation_status": status,
                "ai_explanation": explanation,
                "confidence_score": 1.0 if status == "pass" else 0.85,
                "suggested_action": suggested_action,
                "review_status": review_status,
                "metrics_payload": payload,
            })
        summary_text = self._build_summary_text(record, results)
        overall_status = "pending_review" if any(result.review_status == "pending_review" for result in results) else "draft"
        return {
            "action_performed": "validation_completed",
            "results": results,
            "summary_text": summary_text,
            "review_status": overall_status,
        }

    def _evaluate_rule(self, record, rule):
        try:
            if rule.rule_type == "required_fields":
                missing = [field.field_description or field.name for field in rule.required_field_ids if not record[field.name]]
                if missing:
                    return self._failure(
                        rule,
                        _("Missing required fields: %s.", ", ".join(missing)),
                        _("Fill in the missing values before proceeding."),
                        {"missing_fields": missing},
                    )
                return "pass", _("All required fields are filled."), False, {}
            if rule.rule_type == "date_not_past":
                date_value = record[rule.date_field_id.name] if rule.date_field_id else False
                if date_value and fields.Date.to_date(date_value) < fields.Date.context_today(self):
                    return self._failure(
                        rule,
                        _("%s is in the past.", rule.date_field_id.field_description or rule.date_field_id.name),
                        _("Review the missed date and reschedule if needed."),
                        {"date_value": str(date_value)},
                    )
                return "pass", _("The configured date check passed."), False, {"date_value": str(date_value) if date_value else False}
            if rule.rule_type == "numeric_positive":
                value = record[rule.numeric_field_id.name] if rule.numeric_field_id else 0.0
                if value <= rule.minimum_numeric_value:
                    return self._failure(
                        rule,
                        _(
                            "%(field)s is %(value)s and must be greater than %(minimum)s.",
                            field=rule.numeric_field_id.field_description or rule.numeric_field_id.name,
                            value=value,
                            minimum=rule.minimum_numeric_value,
                        ),
                        _("Adjust the numeric value before continuing."),
                        {"value": value, "minimum": rule.minimum_numeric_value},
                    )
                return "pass", _("The numeric threshold check passed."), False, {"value": value, "minimum": rule.minimum_numeric_value}
            if rule.rule_type == "attachment_required":
                attachment_count = self.env["ir.attachment"].search_count([("res_model", "=", record._name), ("res_id", "=", record.id)])
                if not attachment_count:
                    return self._failure(
                        rule,
                        _("No attachments were found for this record."),
                        _("Attach the required supporting documents."),
                        {"attachment_count": attachment_count},
                    )
                return "pass", _("Supporting attachments are present."), False, {"attachment_count": attachment_count}
            if rule.rule_type == "state_in":
                state_value = record[rule.state_field_id.name] if rule.state_field_id else False
                allowed_values = [value.strip() for value in (rule.allowed_state_values or "").split(",") if value.strip()]
                if allowed_values and state_value not in allowed_values:
                    return self._failure(
                        rule,
                        _("State %(state)s is not one of the allowed values: %(allowed)s.", state=state_value, allowed=", ".join(allowed_values)),
                        _("Move the record to an allowed state or revise the rule."),
                        {"state_value": state_value, "allowed_values": allowed_values},
                    )
                return "pass", _("The state-based validation check passed."), False, {"state_value": state_value, "allowed_values": allowed_values}
        except Exception as exc:  # noqa: BLE001
            return "error", str(exc), _("Review the validation rule configuration."), {}
        return "pass", _("No validation issue was found."), False, {}

    def _failure(self, rule, explanation, suggested_action, payload):
        return ("fail" if rule.severity == "error" else "warning"), explanation, suggested_action, payload

    def _build_summary_text(self, record, results):
        passed = len(results.filtered(lambda result: result.validation_status == "pass"))
        warnings = len(results.filtered(lambda result: result.validation_status == "warning"))
        failures = len(results.filtered(lambda result: result.validation_status == "fail"))
        errors = len(results.filtered(lambda result: result.validation_status == "error"))
        return _(
            "Validation for %(record)s finished with %(passed)s passed checks, %(warnings)s warnings, %(failures)s failures, and %(errors)s rule errors.",
            record=record.display_name,
            passed=passed,
            warnings=warnings,
            failures=failures,
            errors=errors,
        )
