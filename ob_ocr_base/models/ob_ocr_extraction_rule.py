from odoo import fields, models


class OcrExtractionRule(models.Model):
    _name = "ob.ocr.extraction.rule"
    _description = "OCR Extraction Rule"
    _order = "sequence, id"

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", string="Company")
    document_type_id = fields.Many2one("ob.ocr.document.type", required=True, ondelete="cascade")
    mapping_id = fields.Many2one("ob.ocr.mapping", string="Mapping", ondelete="cascade")
    provider_id = fields.Many2one("ob.ocr.provider", string="Provider")
    rule_type = fields.Selection(
        [
            ("regex", "Regex"),
            ("static", "Static"),
            ("template", "Template"),
        ],
        default="regex",
        required=True,
    )
    target_key = fields.Char(required=True)
    pattern = fields.Text()
    flags = fields.Char(help="Comma-separated Python regex flags such as IGNORECASE,MULTILINE.")
    default_value = fields.Char()
    is_line_rule = fields.Boolean(default=False)
    note = fields.Text(translate=True)
