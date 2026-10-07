from odoo import _, api, fields, models


MEMORY_STATUS_SELECTION = [
    ("valid", "Valid"),
    ("stale", "Stale"),
    ("superseded", "Superseded"),
]

MEMORY_OPERATION_SELECTION = [
    ("aggregate", "Aggregate"),
    ("count", "Count"),
    ("group", "Group"),
    ("list", "List"),
    ("summary", "Summary"),
]


class OBAIMemoryState(models.Model):
    _name = "ob.ai.memory.state"
    _description = "AI Memory State"
    _order = "create_date desc, id desc"

    name = fields.Char(compute="_compute_name")
    conversation_id = fields.Many2one("ob.ai.conversation", ondelete="cascade", required=True)
    parent_memory_state_id = fields.Many2one("ob.ai.memory.state", string="Previous Memory State", ondelete="set null")
    last_trace_id = fields.Many2one("ob.ai.investigation.trace", string="Last Investigation Trace", ondelete="set null")
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, required=True)
    user_id = fields.Many2one("res.users", default=lambda self: self.env.user, required=True)
    schema_version_id = fields.Many2one("ob.ai.schema.version", ondelete="set null")
    semantic_ids = fields.Many2many(
        "ob.ai.model.semantic",
        "ob_ai_memory_state_semantic_rel",
        "memory_state_id",
        "semantic_id",
        string="Semantic Models",
    )
    allowed_model_ids = fields.Many2many(
        "ob.ai.allowed.model",
        "ob_ai_memory_state_allowed_model_rel",
        "memory_state_id",
        "allowed_model_id",
        string="Allowed Models",
    )
    result_reference_ids = fields.One2many("ob.ai.result.reference", "memory_state_id", string="Result References", readonly=True)
    template_signature = fields.Char()
    status = fields.Selection(MEMORY_STATUS_SELECTION, default="valid", required=True, index=True)
    intent_code = fields.Char()
    operation_type = fields.Selection(MEMORY_OPERATION_SELECTION, default="summary", required=True)
    target_model_name = fields.Char()
    multi_model = fields.Boolean()
    date_scope = fields.Char()
    state_scope = fields.Char()
    domain_payload = fields.Json(default=dict)
    result_record_refs = fields.Json(default=list)
    route_context_payload = fields.Json(default=dict)
    summary_excerpt = fields.Text()
    last_prompt = fields.Text()
    last_used_at = fields.Datetime()
    step_count = fields.Integer(default=0)
    result_reference_count = fields.Integer(compute="_compute_result_reference_count")

    @api.depends("conversation_id", "target_model_name", "operation_type")
    def _compute_name(self):
        for record in self:
            label = record.conversation_id.display_name or _("AI Memory")
            target = record.target_model_name or _("Generic")
            record.name = _("%(label)s - %(target)s %(operation)s", label=label, target=target, operation=(record.operation_type or "summary").title())

    @api.depends("result_reference_ids")
    def _compute_result_reference_count(self):
        for record in self:
            record.result_reference_count = len(record.result_reference_ids)

    def action_mark_stale(self):
        self.write({"status": "stale"})
        return True
