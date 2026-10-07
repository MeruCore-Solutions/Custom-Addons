from odoo import fields, models


class OBAIDimensionMap(models.Model):
    _name = "ob.ai.dimension.map"
    _description = "AI Dimension Map"
    _order = "dimension_type, name"

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    description = fields.Text()
    dimension_type = fields.Selection(
        [
            ("time", "Time"),
            ("geography", "Geography"),
            ("category", "Category"),
            ("entity", "Entity / Person"),
            ("product_class", "Product Classification"),
            ("status", "Status / Stage"),
            ("custom", "Custom"),
        ],
        required=True,
        default="custom",
    )
    model_id = fields.Many2one("ir.model", string="Source Model", ondelete="cascade")
    field_name = fields.Char(string="Dimension Field", help="The field on the model that represents this dimension.")
    groupby_expression = fields.Char(
        help="Odoo group-by expression, e.g. 'date_order:month' or 'partner_id'."
    )
    value_map_json = fields.Text(
        string="Value Map (JSON)",
        help="Optional JSON object mapping raw field values to human-readable labels.",
    )
    kpi_ids = fields.Many2many(
        "ob.ai.kpi.definition",
        "ob_ai_kpi_dimension_rel",
        "dimension_id",
        "kpi_id",
        string="Applicable KPIs",
    )
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("code_uniq", "unique(code)", "Dimension code must be unique."),
    ]
