from odoo import models


class OCRTextService(models.AbstractModel):
    _name = "ob.ocr.text.service"
    _description = "OCR Text Service"

    def extract_document_text(self, document):
        provider = document._get_effective_provider()
        return provider.extract_text(document)
