from datetime import timedelta

from odoo import api, fields, models


RETENTION_PLACEHOLDER = "[Removed by retention policy]"


class OBAIMessage(models.Model):
    _name = "ob.ai.message"
    _description = "AI Conversation Message"
    _order = "id"

    conversation_id = fields.Many2one(
        "ob.ai.conversation",
        required=True,
        ondelete="cascade",
    )
    company_id = fields.Many2one(
        "res.company",
        related="conversation_id.company_id",
        store=True,
        readonly=True,
    )
    user_id = fields.Many2one("res.users", string="User", default=lambda self: self.env.user)
    role = fields.Selection(
        [
            ("user", "User"),
            ("assistant", "Assistant"),
            ("system", "System"),
        ],
        required=True,
        default="user",
    )
    content = fields.Text(required=True)
    provider_id = fields.Many2one("ob.ai.provider", string="Provider")
    model_id = fields.Many2one("ob.ai.model", string="Model")
    audit_log_id = fields.Many2one("ob.ai.audit.log", string="Audit Log", ondelete="set null")
    agent_session_id = fields.Many2one("ob.ai.agent.session", string="Agent Session", ondelete="set null", help="Filled for assistant messages produced by the agent solver.")
    input_tokens = fields.Integer(readonly=True)
    output_tokens = fields.Integer(readonly=True)

    @api.model
    def _cleanup_message_retention(self):
        params = self.env["ir.config_parameter"].sudo()
        prompt_days = int(params.get_param("ob_ai_assistant.prompt_retention_days", default="30"))
        response_days = int(params.get_param("ob_ai_assistant.response_retention_days", default="30"))
        now = fields.Datetime.now()
        if prompt_days >= 0:
            prompt_cutoff = now - timedelta(days=prompt_days)
            prompt_messages = self.search([
                ("role", "=", "user"),
                ("create_date", "<", prompt_cutoff),
                ("content", "!=", RETENTION_PLACEHOLDER),
            ])
            if prompt_messages:
                prompt_messages.write({"content": RETENTION_PLACEHOLDER})
        if response_days >= 0:
            response_cutoff = now - timedelta(days=response_days)
            response_messages = self.search([
                ("role", "=", "assistant"),
                ("create_date", "<", response_cutoff),
                ("content", "!=", RETENTION_PLACEHOLDER),
            ])
            if response_messages:
                response_messages.write({"content": RETENTION_PLACEHOLDER})
