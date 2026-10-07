from odoo import fields, models


class OBAIModel(models.Model):
    _name = "ob.ai.model"
    _description = "AI Model"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    provider_id = fields.Many2one(
        "ob.ai.provider",
        string="Provider",
        required=True,
        ondelete="cascade",
    )
    model_key = fields.Char(
        string="Model Identifier",
        required=True,
        help="Exact provider API model identifier.",
    )
    max_output_tokens = fields.Integer(
        string="Max Output Tokens",
        default=0,
        help="Optional per-model output token cap. Leave 0 to use the provider fallback.",
    )
    supports_vision = fields.Boolean(string="Supports Vision")
    note = fields.Text()

    _provider_model_key_unique = models.Constraint(
        "UNIQUE(provider_id, model_key)",
        "The model identifier must be unique per provider.",
    )
