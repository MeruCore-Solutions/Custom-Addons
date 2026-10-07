from odoo import fields, models


class OBAIValidationRule(models.Model):
    _name = "ob.ai.validation.rule"
    _description = "AI Validation Rule"
    _order = "sequence, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", string="Company")
    target_model_id = fields.Many2one(
        "ir.model",
        string="Target Model",
        required=True,
        domain="[('transient', '=', False)]",
        ondelete="cascade",
    )
    rule_type = fields.Selection(
        [
            ("required_fields", "Required Fields"),
            ("date_not_past", "Date Not Past"),
            ("numeric_positive", "Numeric Positive"),
            ("attachment_required", "Attachment Required"),
            ("state_in", "State In Allowed Values"),
        ],
        default="required_fields",
        required=True,
    )
    severity = fields.Selection(
        [
            ("info", "Info"),
            ("warning", "Warning"),
            ("error", "Error"),
        ],
        default="warning",
        required=True,
    )
    required_field_ids = fields.Many2many(
        "ir.model.fields",
        "ob_ai_validation_required_field_rel",
        "rule_id",
        "field_id",
        string="Required Fields",
        domain="[('model_id', '=', target_model_id)]",
    )
    date_field_id = fields.Many2one(
        "ir.model.fields",
        string="Date Field",
        domain="[('model_id', '=', target_model_id), ('ttype', 'in', ['date', 'datetime'])]",
    )
    numeric_field_id = fields.Many2one(
        "ir.model.fields",
        string="Numeric Field",
        domain="[('model_id', '=', target_model_id), ('ttype', 'in', ['integer', 'float', 'monetary'])]",
    )
    state_field_id = fields.Many2one(
        "ir.model.fields",
        string="State Field",
        domain="[('model_id', '=', target_model_id)]",
    )
    minimum_numeric_value = fields.Float(default=0.0)
    allowed_state_values = fields.Char(
        help="Comma-separated allowed values for the state field when rule type is State In Allowed Values.",
    )
    requires_approval = fields.Boolean()
    ai_instruction = fields.Text()
    description = fields.Text()
