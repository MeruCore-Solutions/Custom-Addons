from odoo import _, api, fields, models


INVESTIGATION_OPERATION_SELECTION = [
    ("aggregate", "Aggregate"),
    ("count", "Count"),
    ("group", "Group"),
    ("list", "List"),
    ("summary", "Summary"),
]


class OBAIInvestigationTrace(models.Model):
    _name = "ob.ai.investigation.trace"
    _description = "AI Investigation Trace"
    _order = "create_date desc, id desc"

    name = fields.Char(compute="_compute_name")
    conversation_id = fields.Many2one("ob.ai.conversation", ondelete="cascade")
    audit_log_id = fields.Many2one("ob.ai.audit.log", ondelete="set null")
    parent_trace_id = fields.Many2one("ob.ai.investigation.trace", string="Follow-up To", ondelete="set null")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, required=True)
    user_id = fields.Many2one("res.users", default=lambda self: self.env.user, required=True)
    request_token_id = fields.Many2one("ob.ai.request.token", ondelete="set null")
    schema_version_id = fields.Many2one("ob.ai.schema.version", ondelete="set null")
    semantic_ids = fields.Many2many(
        "ob.ai.model.semantic",
        "ob_ai_investigation_trace_semantic_rel",
        "trace_id",
        "semantic_id",
        string="Semantic Models",
    )
    allowed_model_ids = fields.Many2many(
        "ob.ai.allowed.model",
        "ob_ai_investigation_trace_allowed_model_rel",
        "trace_id",
        "allowed_model_id",
        string="Allowed Models",
    )
    prompt = fields.Text(required=True)
    normalized_prompt = fields.Text()
    operation_type = fields.Selection(INVESTIGATION_OPERATION_SELECTION, default="summary", required=True)
    date_scope = fields.Char()
    state_scope = fields.Char()
    status = fields.Selection(
        [
            ("planning", "Planning"),
            ("running", "Running"),
            ("ready", "Ready"),
            ("partial", "Partial"),
            ("error", "Error"),
        ],
        default="planning",
        required=True,
    )
    step_count = fields.Integer(default=0)
    steps_json = fields.Json(default=list)
    selected_record_refs = fields.Json(default=list)
    final_summary = fields.Text()
    last_error = fields.Text()

    @api.depends("conversation_id", "operation_type", "create_date")
    def _compute_name(self):
        for record in self:
            label = record.conversation_id.display_name or _("AI Investigation")
            record.name = _("%(label)s - %(operation)s", label=label, operation=(record.operation_type or "summary").title())
