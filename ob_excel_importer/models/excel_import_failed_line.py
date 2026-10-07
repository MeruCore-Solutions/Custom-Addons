import json

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ExcelImportFailedLine(models.Model):
    _name = "ob.excel.import.failed.line"
    _description = "Excel Import Failed / Not Imported Line"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "import_log_id desc, row_number asc"

    import_log_id = fields.Many2one(
        "ob.excel.import.log",
        required=True,
        ondelete="cascade",
    )
    template_id = fields.Many2one(
        related="import_log_id.template_id",
        store=True,
        readonly=True,
    )
    row_number = fields.Integer(required=True)
    filename = fields.Char()
    state = fields.Selection(
        [
            ("new", "New"),
            ("fixed", "Fixed"),
            ("reimported", "Re-imported"),
            ("ignored", "Ignored"),
            ("failed_again", "Failed Again"),
        ],
        default="new",
        required=True,
        tracking=True,
    )
    target_model = fields.Char()
    source_values = fields.Json(
        help="Original Excel row values.",
    )
    fixed_source_values = fields.Json(
        help="Corrected row values. If empty, original source values are retried.",
    )
    mapped_values = fields.Json()
    error_type = fields.Selection(
        [
            ("validation", "Validation Error"),
            ("missing_required", "Missing Required Field"),
            ("missing_relation", "Missing Related Record"),
            ("duplicate", "Duplicate Record"),
            ("python", "Python Hook Error"),
            ("access", "Access Error"),
            ("system", "System Error"),
            ("blocked", "Blocked"),
        ],
        default="validation",
    )
    error_message = fields.Text(required=True)
    fix_note = fields.Text()
    target_record_id = fields.Integer()
    reimported_at = fields.Datetime()
    activity_created = fields.Boolean(default=False)
    source_values_text = fields.Text(
        compute="_compute_json_text_fields",
    )
    fixed_source_values_text = fields.Text(
        compute="_compute_json_text_fields",
        inverse="_inverse_fixed_source_values_text",
    )
    mapped_values_text = fields.Text(
        compute="_compute_json_text_fields",
    )
    target_record_name = fields.Char(
        compute="_compute_target_record_name",
    )

    @api.depends("source_values", "fixed_source_values", "mapped_values")
    def _compute_json_text_fields(self):
        for line in self:
            line.source_values_text = json.dumps(line.source_values or {}, indent=2, sort_keys=True)
            line.fixed_source_values_text = json.dumps(line.fixed_source_values or {}, indent=2, sort_keys=True)
            line.mapped_values_text = json.dumps(line.mapped_values or {}, indent=2, sort_keys=True)

    def _inverse_fixed_source_values_text(self):
        for line in self:
            raw_text = (line.fixed_source_values_text or "").strip()
            if not raw_text:
                line.fixed_source_values = False
                continue
            try:
                line.fixed_source_values = json.loads(raw_text)
            except json.JSONDecodeError as exc:
                raise ValidationError(_("Invalid JSON value: %s") % exc) from exc

    @api.depends("target_model", "target_record_id")
    def _compute_target_record_name(self):
        for line in self:
            name = False
            if line.target_model and line.target_record_id and line.env.registry.get(line.target_model):
                record = line.env[line.target_model].browse(line.target_record_id).exists()
                if record:
                    name = record.display_name
            line.target_record_name = name

    def action_mark_fixed(self):
        self.write({"state": "fixed"})

    def action_ignore(self):
        self.write({"state": "ignored"})

    def action_reimport_line(self):
        for line in self:
            line.template_id._reimport_failed_line(line)

    def action_reimport_selected_lines(self):
        for template in self.mapped("template_id"):
            lines = self.filtered(lambda line: line.template_id == template)
            template._reimport_failed_lines(lines)

    def action_create_activity(self):
        for line in self:
            line.template_id._notify_import_blockage(
                log=line.import_log_id,
                message=line.error_message,
                failed_line=line,
            )

    def action_open_target_record(self):
        self.ensure_one()
        if not (self.target_model and self.target_record_id):
            return False
        return {
            "type": "ir.actions.act_window",
            "name": _("Target Record"),
            "res_model": self.target_model,
            "res_id": self.target_record_id,
            "view_mode": "form",
            "target": "current",
        }
