from odoo import fields, models


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    ocr_document_id = fields.Many2one("ob.ocr.document", string="OCR Document", index=True)
    is_ocr_processed = fields.Boolean(string="OCR Processed File", default=False)
