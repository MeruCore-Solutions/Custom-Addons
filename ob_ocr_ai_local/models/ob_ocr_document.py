from odoo import _, api, fields, models
from odoo.exceptions import UserError


class OcrDocument(models.Model):
    _inherit = "ob.ocr.document"

    ai_feedback_example_count = fields.Integer(
        compute="_compute_ai_feedback_example_count",
        string="AI Feedback Examples",
    )

    @api.depends("document_type_id")
    def _compute_ai_feedback_example_count(self):
        example_model = self.env["ob.ocr.feedback.example"]
        for record in self:
            if not record.document_type_id:
                record.ai_feedback_example_count = 0
                continue
            record.ai_feedback_example_count = example_model.search_count([
                ("document_type_id", "=", record.document_type_id.id),
                "|",
                ("company_id", "=", False),
                ("company_id", "=", record.company_id.id),
            ])

    def action_mark_reviewed(self):
        result = super().action_mark_reviewed()
        self.env["ob.ocr.ai.feedback.service"].capture_from_documents(self)
        return result

    def action_create_target_record(self):
        result = super().action_create_target_record()
        self.env["ob.ocr.ai.feedback.service"].capture_from_documents(self)
        return result

    def action_update_target_record(self):
        result = super().action_update_target_record()
        self.env["ob.ocr.ai.feedback.service"].capture_from_documents(self)
        return result

    def action_open_ai_feedback_examples(self):
        self.ensure_one()
        if not self.document_type_id:
            raise UserError(_("The OCR document does not have a document type yet."))
        return {
            "type": "ir.actions.act_window",
            "name": _("AI Feedback Examples"),
            "res_model": "ob.ocr.feedback.example",
            "view_mode": "list,form",
            "domain": [
                ("document_type_id", "=", self.document_type_id.id),
                "|",
                ("company_id", "=", False),
                ("company_id", "=", self.company_id.id),
            ],
            "context": {
                "default_document_type_id": self.document_type_id.id,
                "default_company_id": self.company_id.id,
                "search_default_document_type_id": self.document_type_id.id,
            },
        }
