from odoo import api, fields, models


class OBAIValidationResult(models.Model):
    _name = "ob.ai.validation.result"
    _description = "AI Validation Result"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"

    name = fields.Char(compute="_compute_name", store=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, tracking=True)
    source_conversation_id = fields.Many2one("ob.ai.conversation", string="Source Conversation", ondelete="set null")
    source_approval_id = fields.Many2one("ob.ai.approval", string="Related Approval", ondelete="set null")
    related_record_ref = fields.Reference(selection="_selection_reference_models", string="Related Record", tracking=True)
    record_model = fields.Char(index=True)
    record_res_id = fields.Integer(index=True)
    rule_id = fields.Many2one("ob.ai.validation.rule", ondelete="cascade", tracking=True)
    validation_status = fields.Selection(
        [
            ("pass", "Pass"),
            ("warning", "Warning"),
            ("fail", "Fail"),
            ("error", "Error"),
        ],
        default="pass",
        required=True,
        tracking=True,
    )
    ai_explanation = fields.Text()
    confidence_score = fields.Float(digits=(16, 4))
    suggested_action = fields.Text()
    reviewer_id = fields.Many2one("res.users", string="Reviewer", tracking=True)
    review_status = fields.Selection(
        [
            ("draft", "Draft"),
            ("pending_review", "Pending Review"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("applied", "Applied"),
        ],
        default="draft",
        required=True,
        tracking=True,
    )
    final_decision = fields.Text()
    metrics_payload = fields.Json(default=dict)
    created_by_ai = fields.Boolean(default=True)

    @api.depends("related_record_ref", "rule_id", "validation_status")
    def _compute_name(self):
        for record in self:
            ref_name = record.related_record_ref.display_name if record.related_record_ref else "Record"
            rule_name = record.rule_id.display_name or "Rule"
            record.name = "%s - %s (%s)" % (ref_name, rule_name, record.validation_status.title())

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            related_ref = values.get("related_record_ref")
            if related_ref and isinstance(related_ref, str) and "," in related_ref:
                model_name, res_id = related_ref.split(",", 1)
                values.setdefault("record_model", model_name)
                values.setdefault("record_res_id", int(res_id))
        return super().create(vals_list)

    def _selection_reference_models(self):
        return self.env["ob.ai.conversation"]._selection_reference_models()
