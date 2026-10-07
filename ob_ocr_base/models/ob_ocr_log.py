import json

from odoo import api, fields, models


class OcrLog(models.Model):
    _name = "ob.ocr.log"
    _description = "OCR Log"
    _order = "create_date desc, id desc"

    document_id = fields.Many2one("ob.ocr.document", required=True, ondelete="cascade")
    company_id = fields.Many2one(related="document_id.company_id", store=True, readonly=True)
    provider_id = fields.Many2one("ob.ocr.provider", string="Provider")
    user_id = fields.Many2one("res.users", string="User", default=lambda self: self.env.user, readonly=True)
    level = fields.Selection(
        [
            ("info", "Info"),
            ("warning", "Warning"),
            ("error", "Error"),
        ],
        default="info",
        required=True,
    )
    message = fields.Char(required=True)
    details_json = fields.Json(string="Details")
    details_text = fields.Text(string="Details JSON", compute="_compute_details_text")

    @api.depends("details_json")
    def _compute_details_text(self):
        for record in self:
            record.details_text = json.dumps(record.details_json or {}, indent=2, sort_keys=True)
