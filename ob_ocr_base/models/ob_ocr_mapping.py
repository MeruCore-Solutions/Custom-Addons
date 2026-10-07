import json

from odoo import api, fields, models


class OcrMapping(models.Model):
    _name = "ob.ocr.mapping"
    _description = "OCR Mapping"
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", string="Company")
    document_type_id = fields.Many2one("ob.ocr.document.type", required=True, ondelete="cascade")
    target_model = fields.Char()
    provider_id = fields.Many2one("ob.ocr.provider", string="Provider")
    extraction_mode = fields.Selection(
        [
            ("regex", "Regex"),
            ("template", "Template"),
            ("provider", "Provider"),
            ("ai", "AI Assisted"),
        ],
        default="regex",
        required=True,
    )
    description = fields.Text(translate=True)
    schema_json = fields.Json(string="Schema")
    schema_json_text = fields.Text(
        string="Schema JSON",
        compute="_compute_schema_json_text",
        inverse="_inverse_schema_json_text",
    )
    field_ids = fields.One2many("ob.ocr.mapping.field", "mapping_id", string="Field Mapping")
    rule_ids = fields.One2many("ob.ocr.extraction.rule", "mapping_id", string="Extraction Rules")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("target_model") and vals.get("document_type_id"):
                document_type = self.env["ob.ocr.document.type"].browse(vals["document_type_id"])
                vals["target_model"] = document_type.target_model
        return super().create(vals_list)

    @api.onchange("document_type_id")
    def _onchange_document_type_id(self):
        for record in self:
            record.target_model = record.document_type_id.target_model

    @api.depends("schema_json")
    def _compute_schema_json_text(self):
        for record in self:
            record.schema_json_text = json.dumps(record.schema_json or {}, indent=2, sort_keys=True)

    def _inverse_schema_json_text(self):
        for record in self:
            record.schema_json = json.loads(record.schema_json_text or "{}")
