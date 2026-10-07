from odoo import fields, models


class OcrMappingField(models.Model):
    _name = "ob.ocr.mapping.field"
    _description = "OCR Mapping Field"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    mapping_id = fields.Many2one("ob.ocr.mapping", required=True, ondelete="cascade")
    company_id = fields.Many2one(related="mapping_id.company_id", store=True, readonly=True)
    sequence = fields.Integer(default=10)
    source_key = fields.Char(required=True)
    target_field = fields.Char(required=True)
    regex_pattern = fields.Char()
    transform_type = fields.Selection(
        [
            ("none", "None"),
            ("strip", "Strip"),
            ("upper", "Uppercase"),
            ("lower", "Lowercase"),
            ("title", "Title Case"),
            ("float", "Float"),
            ("int", "Integer"),
            ("bool", "Boolean"),
            ("date", "Date"),
        ],
        default="none",
        required=True,
    )
    required = fields.Boolean(default=False)
    is_line_field = fields.Boolean(default=False)
    default_value = fields.Char()
    note = fields.Text(translate=True)
