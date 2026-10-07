from odoo import fields, models


class OBAIModelRelationship(models.Model):
    _name = "ob.ai.model.relationship"
    _description = "AI Model Relationship"
    _order = "source_model_id, name"

    name = fields.Char(required=True)
    source_model_id = fields.Many2one("ir.model", required=True, ondelete="cascade", string="Source Model")
    target_model_id = fields.Many2one("ir.model", required=True, ondelete="cascade", string="Target Model")
    relationship_type = fields.Selection(
        [
            ("many2one", "Many-to-One (FK)"),
            ("one2many", "One-to-Many (Reverse FK)"),
            ("many2many", "Many-to-Many"),
            ("aggregation", "Aggregation Path"),
            ("reference", "Reference Field"),
        ],
        required=True,
        default="many2one",
    )
    source_field_name = fields.Char(string="Source Field", help="Field on the source model that links to target.")
    target_field_name = fields.Char(string="Target Field", help="Corresponding field on the target model.")
    join_path = fields.Text(
        help="For multi-hop joins, describe the full path as a Python list of (model, field) tuples in JSON.",
    )
    business_meaning = fields.Text(
        help="Plain-English description of what this relationship means, e.g. 'Each sale order belongs to one customer'.",
    )
    is_primary = fields.Boolean(
        default=False,
        help="Mark as primary when this is the most semantically meaningful link between the two models.",
    )
    active = fields.Boolean(default=True)
