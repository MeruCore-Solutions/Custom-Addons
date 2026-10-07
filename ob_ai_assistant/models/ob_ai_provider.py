from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class OBAIProvider(models.Model):
    _name = "ob.ai.provider"
    _description = "AI Provider"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, copy=False, index=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    company_id = fields.Many2one("res.company", string="Company")
    provider_type = fields.Selection(
        [
            ("openai", "ChatGPT (OpenAI)"),
            ("anthropic", "Claude (Anthropic)"),
        ],
        string="Provider Type",
        required=True,
        default="openai",
    )
    endpoint_url = fields.Char(required=True)
    api_key_parameter = fields.Char(
        required=True,
        help="Technical ir.config_parameter key used to retrieve the API key securely.",
    )
    default_model_id = fields.Many2one(
        "ob.ai.model",
        string="Default Model",
        domain="[('provider_id', '=', id)]",
    )
    timeout_seconds = fields.Integer(
        string="Timeout (seconds)",
        default=0,
        help="Leave 0 to use the global timeout from AI settings.",
    )
    max_retries = fields.Integer(
        string="Max Retries",
        default=0,
        help="Leave 0 to use the global retry count from AI settings.",
    )
    max_output_tokens = fields.Integer(
        string="Max Output Tokens",
        default=0,
        help="Optional provider-level output token cap. Leave 0 to use the service fallback.",
    )
    temperature = fields.Float(
        string="Temperature",
        default=0.2,
        digits=(16, 2),
    )
    note = fields.Text()
    api_key_configured = fields.Boolean(
        string="API Key Configured",
        compute="_compute_api_key_configured",
    )
    model_ids = fields.One2many("ob.ai.model", "provider_id", string="Models")

    _code_unique = models.Constraint(
        "UNIQUE(code)",
        "The provider code must be unique.",
    )

    @api.depends("api_key_parameter")
    def _compute_api_key_configured(self):
        params = self.env["ir.config_parameter"].sudo()
        for record in self:
            api_key = params.get_param(record.api_key_parameter or "", default=False) if record.api_key_parameter else False
            record.api_key_configured = bool(api_key)

    @api.constrains("default_model_id", "provider_type")
    def _check_default_model_provider(self):
        for record in self:
            if record.default_model_id and record.default_model_id.provider_id != record:
                raise ValidationError(_("The default model must belong to the selected AI provider."))

    def get_api_key(self):
        self.ensure_one()
        if not self.api_key_parameter:
            return False
        return self.env["ir.config_parameter"].sudo().get_param(self.api_key_parameter, default=False)
