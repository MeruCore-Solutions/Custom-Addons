from datetime import date, datetime, time
from decimal import Decimal

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class OBAIApproval(models.Model):
    _name = "ob.ai.approval"
    _description = "AI Approval Request"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"

    name = fields.Char(required=True, default="AI Approval", tracking=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, tracking=True)
    requested_by_id = fields.Many2one(
        "res.users",
        string="Requested By",
        default=lambda self: self.env.user,
        required=True,
        tracking=True,
    )
    reviewer_id = fields.Many2one("res.users", string="Reviewer", tracking=True)
    source_conversation_id = fields.Many2one("ob.ai.conversation", string="Source Conversation", ondelete="set null")
    source_message_id = fields.Many2one("ob.ai.message", string="Source Message", ondelete="set null")
    related_record_ref = fields.Reference(selection="_selection_reference_models", string="Related Record", tracking=True)
    action_type = fields.Selection(
        [
            ("reminder", "Reminder"),
            ("activity", "Activity"),
            ("chatter", "Chatter"),
            ("validation", "Validation"),
            ("dashboard", "Dashboard"),
            ("document", "Document"),
            ("other", "Other"),
        ],
        default="other",
        required=True,
        tracking=True,
    )
    review_status = fields.Selection(
        [
            ("draft", "Draft"),
            ("pending_review", "Pending Review"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("applied", "Applied"),
        ],
        default="pending_review",
        required=True,
        tracking=True,
    )
    approval_scope = fields.Selection(
        [
            ("general", "General"),
            ("accounting", "Accounting"),
            ("hr", "HR"),
            ("healthcare", "Healthcare"),
        ],
        default="general",
        tracking=True,
    )
    action_summary = fields.Text(required=True)
    payload_json = fields.Json(default=dict)
    result_message = fields.Text(readonly=True)
    idempotency_key = fields.Char(index=True, copy=False)
    reviewed_on = fields.Datetime(readonly=True)
    applied_on = fields.Datetime(readonly=True)
    conversation_id = fields.Many2one(
        comodel_name="ob.ai.conversation",
        string="Conversation",
        store=True,
        readonly=True,
        index=True,
    )
    user_id = fields.Many2one(
        "res.users",
        string="Requester (Legacy)",
        default=lambda self: self.env.user,
        required=True,
        index=True,
        ondelete="restrict",
    )


    def _selection_reference_models(self):
        return self.env["ob.ai.conversation"]._selection_reference_models()

    @api.model_create_multi
    def create(self, vals_list):
        sanitized_vals_list = [self._sanitize_json_fields(values) for values in vals_list]
        return super().create(sanitized_vals_list)

    def write(self, vals):
        return super().write(self._sanitize_json_fields(vals))

    def action_submit(self):
        self.write({"review_status": "pending_review"})

    def action_approve(self):
        self.write({
            "review_status": "approved",
            "reviewer_id": self.env.user.id,
            "reviewed_on": fields.Datetime.now(),
        })

    def action_reject(self):
        self.write({
            "review_status": "rejected",
            "reviewer_id": self.env.user.id,
            "reviewed_on": fields.Datetime.now(),
        })

    def action_apply(self):
        for approval in self:
            if approval.review_status != "approved":
                raise UserError(_("Only approved AI actions can be applied."))
            result = self.env["ob.ai.action.service"].apply_approved_action(approval)
            approval.write({
                "review_status": "applied",
                "applied_on": fields.Datetime.now(),
                "result_message": result.get("summary_text"),
            })

    def _sanitize_json_fields(self, values):
        values = dict(values or {})
        values = self._normalize_legacy_values(values)
        if "payload_json" in values:
            values["payload_json"] = self._json_safe(values.get("payload_json"))
        return values

    def _normalize_legacy_values(self, values):
        values = dict(values or {})
        legacy_summary = values.pop("summary", False)
        if legacy_summary and not values.get("action_summary"):
            values["action_summary"] = legacy_summary
        if values.get("conversation_id") and not values.get("source_conversation_id"):
            values["source_conversation_id"] = values["conversation_id"]
        if values.get("user_id") and not values.get("requested_by_id"):
            values["requested_by_id"] = values["user_id"]
        return values

    def _json_safe(self, value):
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, datetime):
            return fields.Datetime.to_string(value)
        if isinstance(value, date):
            return fields.Date.to_string(value)
        if isinstance(value, time):
            return value.isoformat()
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, bytes):
            return "<binary>"
        if isinstance(value, models.BaseModel):
            if len(value) == 1:
                return "%s,%s" % (value._name, value.id)
            return ["%s,%s" % (record._name, record.id) for record in value]
        if isinstance(value, dict):
            return {str(key): self._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self._json_safe(item) for item in value]
        return str(value)
