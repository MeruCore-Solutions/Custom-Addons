from datetime import timedelta

from odoo import api, fields, models


SHARED_DATA_RETENTION_DEFAULT_DAYS = 1095


class OBAIAuditLog(models.Model):
    _name = "ob.ai.audit.log"
    _description = "AI Audit Log"
    _order = "create_date desc, id desc"

    name = fields.Char(compute="_compute_name")
    conversation_id = fields.Many2one("ob.ai.conversation", ondelete="cascade")
    message_id = fields.Many2one("ob.ai.message", ondelete="set null")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
    user_id = fields.Many2one("res.users", string="Requested By", default=lambda self: self.env.user)
    provider_id = fields.Many2one("ob.ai.provider", string="Provider")
    model_id = fields.Many2one("ob.ai.model", string="Model")
    schema_version_id = fields.Many2one("ob.ai.schema.version", string="Schema Version")
    request_token_id = fields.Many2one("ob.ai.request.token", string="Communication Token", ondelete="set null")
    investigation_trace_id = fields.Many2one("ob.ai.investigation.trace", string="Investigation Trace", ondelete="set null")
    memory_state_id = fields.Many2one("ob.ai.memory.state", string="Memory State", ondelete="set null")
    request_kind = fields.Selection(
        [
            ("chat", "Chat"),
            ("summary", "Summary"),
        ],
        default="chat",
        required=True,
    )
    status = fields.Selection(
        [
            ("success", "Success"),
            ("error", "Error"),
            ("blocked", "Blocked"),
        ],
        default="success",
        required=True,
    )
    provider_response_id = fields.Char(string="Provider Response ID")
    prompt_char_count = fields.Integer()
    response_char_count = fields.Integer()
    input_tokens = fields.Integer()
    output_tokens = fields.Integer()
    latency_ms = fields.Integer()
    http_status = fields.Integer()
    accessed_models = fields.Char(help="Comma-separated technical model names included in the AI context.")
    accessed_record_ids = fields.Json(default=dict)
    accessed_fields = fields.Json(default=dict)
    blocked_fields = fields.Json(default=dict)
    hidden_record_count = fields.Integer()
    intent_code = fields.Char()
    related_model = fields.Char()
    related_record_refs = fields.Json(default=list)
    action_requested = fields.Char()
    action_performed = fields.Char()
    confidence_score = fields.Float(digits=(16, 4))
    human_review_status = fields.Char()
    prompt_template_version = fields.Integer()
    input_stored = fields.Boolean()
    output_stored = fields.Boolean()
    request_id = fields.Char()
    idempotency_key = fields.Char(index=True)
    warning_message = fields.Text()
    context_payload = fields.Json()
    request_payload = fields.Json()
    response_payload = fields.Json()
    error_message = fields.Text()

    @api.depends("conversation_id", "status", "create_date")
    def _compute_name(self):
        for record in self:
            label = record.conversation_id.display_name or "AI Request"
            record.name = "%s - %s" % (label, record.status.title())

    @api.model
    def _cron_apply_retention_policies(self):
        self._cleanup_audit_payloads()
        self.env["ob.ai.message"]._cleanup_message_retention()

    @api.model
    def _cleanup_audit_payloads(self):
        params = self.env["ir.config_parameter"].sudo()
        store_raw = params.get_param("ob_ai_assistant.store_raw_payload", default="True") == "True"
        shared_data_retention_days = int(
            params.get_param(
                "ob_ai_assistant.shared_data_retention_days",
                default=str(SHARED_DATA_RETENTION_DEFAULT_DAYS),
            )
        )
        if not store_raw:
            all_logs = self.search([])
            if all_logs:
                all_logs.write({
                    "request_payload": False,
                    "response_payload": False,
                    "context_payload": False,
                    "input_stored": False,
                    "output_stored": False,
                })
            return
        if shared_data_retention_days < 0:
            return
        now = fields.Datetime.now()
        shared_data_cutoff = now - timedelta(days=shared_data_retention_days)
        stale_logs = self.search([("create_date", "<", shared_data_cutoff)])
        if stale_logs:
            stale_logs.write({
                "request_payload": False,
                "response_payload": False,
                "context_payload": False,
                "input_stored": False,
                "output_stored": False,
            })
