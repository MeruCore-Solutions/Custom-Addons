from odoo import _, fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    ocr_document_count = fields.Integer(compute="_compute_ocr_document_count", string="OCR Documents")

    def _compute_ocr_document_count(self):
        document_model = self.env["ob.ocr.document"]
        for move in self:
            move.ocr_document_count = document_model.search_count([
                ("related_model", "=", "account.move"),
                ("related_res_id", "=", move.id),
            ])

    def action_open_ocr_documents(self):
        self.ensure_one()
        action = {
            "type": "ir.actions.act_window",
            "name": _("OCR Documents"),
            "res_model": "ob.ocr.document",
            "view_mode": "list,form",
            "domain": [("related_model", "=", "account.move"), ("related_res_id", "=", self.id)],
        }
        document = self.env["ob.ocr.document"].search(action["domain"], limit=1)
        if document and self.ocr_document_count == 1:
            action.update({"view_mode": "form", "res_id": document.id})
        return action
