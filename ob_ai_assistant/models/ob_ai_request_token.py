from odoo import _, api, fields, models


class OBAIRequestToken(models.Model):
    _name = "ob.ai.request.token"
    _description = "AI Request Token"
    _order = "create_date desc, id desc"

    name = fields.Char(compute="_compute_name")
    conversation_id = fields.Many2one("ob.ai.conversation", ondelete="cascade")
    audit_log_id = fields.Many2one("ob.ai.audit.log", ondelete="set null")
    user_id = fields.Many2one("res.users", required=True, default=lambda self: self.env.user)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company)
    schema_version_id = fields.Many2one("ob.ai.schema.version", ondelete="set null")
    request_kind = fields.Selection(
        [
            ("chat_context", "Chat Context"),
            ("schema_read", "Schema Read"),
            ("record_read", "Record Read"),
            ("action_proposal", "Action Proposal"),
        ],
        default="chat_context",
        required=True,
    )
    state = fields.Selection(
        [
            ("active", "Active"),
            ("expired", "Expired"),
            ("revoked", "Revoked"),
        ],
        default="active",
        required=True,
        index=True,
    )
    token_jti = fields.Char(required=True, index=True)
    token_hint = fields.Char(readonly=True)
    token_digest = fields.Char(required=True, index=True)
    scope_json = fields.Json(default=list)
    template_snapshot = fields.Json(default=dict)
    template_signature = fields.Char()
    expires_at = fields.Datetime(required=True, index=True)
    last_used_at = fields.Datetime()
    use_count = fields.Integer(default=0)
    max_investigation_steps = fields.Integer(default=3)
    max_models_per_request = fields.Integer(default=6)
    max_records_per_fetch = fields.Integer(default=25)
    revoked_reason = fields.Text()

    @api.depends("conversation_id", "user_id", "request_kind", "token_hint")
    def _compute_name(self):
        for record in self:
            base_label = record.conversation_id.display_name or record.user_id.display_name or _("AI Request")
            hint = record.token_hint or record.token_jti or ""
            record.name = "%s - %s" % (base_label, hint[:8])

    @api.model
    def _cron_cleanup_expired_tokens(self):
        now = fields.Datetime.now()
        expired = self.search([("state", "=", "active"), ("expires_at", "<=", now)])
        if expired:
            expired.write({"state": "expired"})

    def action_revoke(self):
        self.write({
            "state": "revoked",
            "revoked_reason": _("Revoked manually by an AI manager."),
        })
        return True
