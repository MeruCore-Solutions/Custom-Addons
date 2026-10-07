import json

from odoo import _, api, fields, models


class OcrProvider(models.Model):
    _name = "ob.ocr.provider"
    _description = "OCR Provider"
    _order = "sequence, name"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, index=True)
    provider_key = fields.Char(required=True, default="tesseract")
    service_model = fields.Char(required=True, default="ob.ocr.provider.service")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    is_default = fields.Boolean(string="Default Provider")
    handwriting_supported = fields.Boolean(default=True)
    store_processed_images = fields.Boolean(default=False)
    allowed_mimetypes = fields.Char(
        string="Allowed Mime Types",
        default="application/pdf,image/png,image/jpeg,image/jpg,image/tiff,image/webp",
    )
    company_id = fields.Many2one("res.company", string="Company")
    config_json = fields.Json(string="Provider Configuration")
    config_json_text = fields.Text(
        string="Configuration JSON",
        compute="_compute_config_json_text",
        inverse="_inverse_config_json_text",
    )
    note = fields.Text(translate=True)

    _code_unique = models.Constraint(
        "UNIQUE(code)",
        "The OCR provider code must be unique.",
    )

    @api.depends("config_json")
    def _compute_config_json_text(self):
        for record in self:
            record.config_json_text = json.dumps(record.config_json or {}, indent=2, sort_keys=True)

    def _inverse_config_json_text(self):
        for record in self:
            record.config_json = json.loads(record.config_json_text or "{}")

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.filtered("is_default")._unset_other_defaults()
        return records

    def write(self, vals):
        result = super().write(vals)
        if vals.get("is_default"):
            self.filtered("is_default")._unset_other_defaults()
        return result

    def _unset_other_defaults(self):
        for record in self:
            others = self.search([("id", "!=", record.id), ("is_default", "=", True)])
            if others:
                others.write({"is_default": False})

    def _get_service(self):
        self.ensure_one()
        return self.env[self.service_model]

    def extract_text(self, document):
        self.ensure_one()
        return self._get_service().extract_text(self, document)

    def extract_json(self, document, schema):
        self.ensure_one()
        return self._get_service().extract_json(self, document, schema)

    def detect_language(self, document):
        self.ensure_one()
        return self._get_service().detect_language(self, document)

    def supports_handwriting(self):
        self.ensure_one()
        return self._get_service().supports_handwriting(self)

    def supports_file_type(self, mimetype):
        self.ensure_one()
        return self._get_service().supports_file_type(self, mimetype)
