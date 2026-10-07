from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class OcrDocumentType(models.Model):
    _name = "ob.ocr.document.type"
    _description = "OCR Document Type"
    _order = "name"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(required=True, index=True)
    description = fields.Text(translate=True)
    target_model = fields.Char(string="Target Model")
    handler_model = fields.Char(string="Handler Model", default="ob.ocr.document", required=True)
    prepare_method_name = fields.Char(
        string="Prepare Method",
        default="_prepare_target_values",
        required=True,
    )
    create_method_name = fields.Char(
        string="Create Method",
        default="_create_target_record",
        required=True,
    )
    update_method_name = fields.Char(
        string="Update Method",
        default="_update_target_record",
        required=True,
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", string="Company")
    mapping_ids = fields.One2many("ob.ocr.mapping", "document_type_id", string="Mappings")
    document_count = fields.Integer(compute="_compute_document_count", string="Documents")

    _code_unique = models.Constraint(
        "UNIQUE(code)",
        "The OCR document type code must be unique.",
    )

    def _compute_document_count(self):
        for record in self:
            record.document_count = self.env["ob.ocr.document"].search_count([
                ("document_type_id", "=", record.id),
            ])

    @staticmethod
    def _validate_method_name(value, label):
        if value and not value.startswith("_"):
            raise ValidationError(_("%s must start with an underscore to point to a model method.") % label)

    @api.constrains("prepare_method_name", "create_method_name", "update_method_name")
    def _check_method_names(self):
        for record in self:
            record._validate_method_name(record.prepare_method_name, _("Prepare method"))
            record._validate_method_name(record.create_method_name, _("Create method"))
            record._validate_method_name(record.update_method_name, _("Update method"))
