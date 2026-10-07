from odoo import api, fields, models


class OBAIReminder(models.Model):
    _name = "ob.ai.reminder"
    _description = "AI Reminder"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "due_datetime asc, id desc"

    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, tracking=True)
    requesting_user_id = fields.Many2one(
        "res.users",
        string="Requested By",
        default=lambda self: self.env.user,
        required=True,
        tracking=True,
    )
    assigned_user_id = fields.Many2one("res.users", string="Assigned To", tracking=True)
    related_record_ref = fields.Reference(selection="_selection_reference_models", string="Related Record", tracking=True)
    reminder_text = fields.Text(required=True, tracking=True)
    due_datetime = fields.Datetime(required=True, tracking=True)
    status = fields.Selection(
        [
            ("draft", "Draft"),
            ("pending", "Pending"),
            ("due", "Due"),
            ("done", "Done"),
            ("cancelled", "Cancelled"),
        ],
        default="pending",
        tracking=True,
    )
    source_conversation_id = fields.Many2one("ob.ai.conversation", string="Source Conversation", ondelete="set null")
    source_message_id = fields.Many2one("ob.ai.message", string="Source Message", ondelete="set null")
    created_by_ai = fields.Boolean(default=True)
    notification_sent = fields.Boolean(default=False)
    access_scope = fields.Char(help="Optional free-form business scope such as company, branch, or warehouse.")
    idempotency_key = fields.Char(index=True, copy=False)
    activity_id = fields.Many2one("mail.activity", string="Generated Activity", ondelete="set null", readonly=True)

    _company_idempotency_key_unique = models.Constraint(
        "UNIQUE(company_id, idempotency_key)",
        "The reminder idempotency key must be unique per company.",
    )

    def _selection_reference_models(self):
        return self.env["ob.ai.conversation"]._selection_reference_models()

    def action_mark_done(self):
        self.write({
            "status": "done",
            "notification_sent": True,
        })

    def action_cancel(self):
        self.write({"status": "cancelled"})

    @api.model
    def _cron_process_due_reminders(self):
        reminders = self.search([
            ("active", "=", True),
            ("status", "in", ["draft", "pending"]),
            ("due_datetime", "<=", fields.Datetime.now()),
        ])
        for reminder in reminders:
            self.env["ob.ai.action.service"]._notify_due_reminder(reminder)
