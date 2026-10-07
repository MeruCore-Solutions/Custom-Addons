from odoo import models


class OCRRecordCreationService(models.AbstractModel):
    _name = "ob.ocr.record.creation.service"
    _description = "OCR Record Creation Service"

    def create_target_record(self, document):
        values = document._dispatch_document_type_method("prepare_method_name", "_prepare_target_values")
        return document._dispatch_document_type_method("create_method_name", "_create_target_record", values)

    def update_target_record(self, document):
        values = document._dispatch_document_type_method("prepare_method_name", "_prepare_target_values")
        return document._dispatch_document_type_method("update_method_name", "_update_target_record", values)
