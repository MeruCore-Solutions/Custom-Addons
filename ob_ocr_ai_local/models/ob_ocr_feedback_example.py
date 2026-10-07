import json

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class OcrFeedbackExample(models.Model):
    _name = "ob.ocr.feedback.example"
    _description = "OCR AI Feedback Example"
    _order = "last_used_date desc, write_date desc, id desc"

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", string="Company")
    document_type_id = fields.Many2one("ob.ocr.document.type", required=True, ondelete="cascade")
    provider_id = fields.Many2one("ob.ocr.provider", string="Suggested Provider", ondelete="set null")
    document_id = fields.Many2one("ob.ocr.document", string="Source Document", ondelete="cascade")
    related_model = fields.Char(readonly=True)
    related_res_id = fields.Integer(readonly=True)
    language = fields.Char()
    partner_name = fields.Char()
    reference_text = fields.Char()
    raw_text = fields.Text(required=True)
    extracted_json = fields.Json(required=True)
    extracted_json_text = fields.Text(
        string="Extracted JSON",
        compute="_compute_extracted_json_text",
        inverse="_inverse_extracted_json_text",
    )
    use_count = fields.Integer(default=0, readonly=True)
    last_used_date = fields.Datetime(readonly=True)
    note = fields.Text()

    _document_unique = models.Constraint(
        "UNIQUE(document_id)",
        "Each OCR document can only create one feedback example.",
    )

    @api.depends("extracted_json")
    def _compute_extracted_json_text(self):
        for record in self:
            record.extracted_json_text = json.dumps(record.extracted_json or {}, indent=2, sort_keys=True)

    def _inverse_extracted_json_text(self):
        for record in self:
            try:
                record.extracted_json = json.loads(record.extracted_json_text or "{}")
            except json.JSONDecodeError as exc:
                raise ValidationError(_("Invalid JSON value: %s") % exc) from exc
