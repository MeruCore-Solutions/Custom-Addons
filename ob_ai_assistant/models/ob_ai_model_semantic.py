from odoo import _, api, fields, models


SEMANTIC_ROLE_SELECTION = [
    ("generic", "Generic"),
    ("sales", "Sales"),
    ("crm", "CRM"),
    ("finance", "Finance"),
    ("inventory", "Inventory"),
    ("procurement", "Procurement"),
    ("hr", "HR"),
    ("project", "Project"),
    ("support", "Support"),
    ("custom", "Custom"),
]


class OBAIModelSemantic(models.Model):
    _name = "ob.ai.model.semantic"
    _description = "AI Model Semantic"
    _order = "sequence, name, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    auto_generated = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", string="Company", default=lambda self: self.env.company)
    allowed_model_id = fields.Many2one(
        "ob.ai.allowed.model",
        string="Allowed Model",
        required=True,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        ondelete="cascade",
    )
    model_id = fields.Many2one(related="allowed_model_id.model_id", store=True, readonly=True)
    schema_version_id = fields.Many2one("ob.ai.schema.version", string="Last Synced Schema Version", ondelete="set null")
    semantic_role = fields.Selection(SEMANTIC_ROLE_SELECTION, default="generic", required=True)
    business_label = fields.Char(help="Business-facing label the AI should use when summarizing this model.")
    generic_query_enabled = fields.Boolean(default=True)
    allow_cross_model = fields.Boolean(default=True)
    title_field_names = fields.Char(string="Title Fields")
    state_field_names = fields.Char(string="State Fields")
    stage_field_names = fields.Char(string="Stage Fields")
    amount_field_names = fields.Char(string="Amount Fields")
    currency_field_names = fields.Char(string="Currency Fields")
    primary_date_field_names = fields.Char(string="Primary Date Fields")
    due_date_field_names = fields.Char(string="Due Date Fields")
    owner_field_names = fields.Char(string="Owner Fields")
    partner_field_names = fields.Char(string="Partner Fields")
    priority_field_names = fields.Char(string="Priority Fields")
    probability_field_names = fields.Char(string="Probability Fields")
    description_field_names = fields.Char(string="Description Fields")
    open_state_values = fields.Char(string="Open State Values")
    closed_state_values = fields.Char(string="Closed State Values")
    inactive_state_values = fields.Char(string="Inactive State Values")
    default_sort_field = fields.Char()
    semantic_hints = fields.Text(
        help="Optional hints or business vocabulary that help the generic investigation engine understand this model.",
    )
    example_queries = fields.Text(
        help="Example prompts admins can store so users understand how this model should be queried.",
    )

    _allowed_model_unique = models.Constraint(
        "UNIQUE(allowed_model_id)",
        "Only one AI semantic definition per allowed model is supported.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            allowed_model = self.env["ob.ai.allowed.model"].browse(values.get("allowed_model_id"))
            if allowed_model:
                values.setdefault("name", _("%s Semantics", allowed_model.display_name))
                values.setdefault("sequence", allowed_model.sequence)
                values.setdefault("business_label", allowed_model.name or allowed_model.model_id.display_name)
        return super().create(vals_list)

    def action_sync_from_schema(self):
        self.env["ob.ai.semantic.service"].sync_semantics(force_update=True, semantics=self)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Semantics synced"),
                "message": _("The selected semantic definitions were refreshed from the current schema registry."),
                "type": "success",
                "sticky": False,
            },
        }
