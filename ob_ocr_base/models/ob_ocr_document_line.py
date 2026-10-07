from odoo import fields, models


class OcrDocumentLine(models.Model):
    _name = "ob.ocr.document.line"
    _description = "OCR Document Line"
    _order = "sequence, id"

    document_id = fields.Many2one("ob.ocr.document", required=True, ondelete="cascade")
    company_id = fields.Many2one(related="document_id.company_id", store=True, readonly=True)
    sequence = fields.Integer(default=10)
    line_type = fields.Selection(
        [
            ("line", "Line"),
            ("note", "Note"),
        ],
        default="line",
        required=True,
    )
    source_key = fields.Char()
    name = fields.Char(string="Description")
    product_code = fields.Char()
    barcode = fields.Char()
    product_name = fields.Char()
    quantity = fields.Float()
    uom_name = fields.Char()
    unit_price = fields.Float()
    discount = fields.Float()
    tax_names = fields.Char()
    confidence_score = fields.Float()
    raw_payload = fields.Json()
    corrected_payload = fields.Json()
    note = fields.Text()
