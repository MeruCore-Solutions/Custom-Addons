from odoo import _, api, fields, models


class ExcelImportLog(models.Model):
    _name = "ob.excel.import.log"
    _description = "Excel Import Log"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "started_at desc, id desc"

    template_id = fields.Many2one(
        "ob.excel.import.template",
        required=True,
        ondelete="cascade",
    )
    filename = fields.Char()
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("running", "Running"),
            ("done", "Done"),
            ("failed", "Failed"),
            ("partial", "Partial"),
        ],
        default="draft",
        tracking=True,
    )
    total_rows = fields.Integer()
    success_count = fields.Integer()
    failed_count = fields.Integer()
    skipped_count = fields.Integer()
    started_at = fields.Datetime()
    finished_at = fields.Datetime()
    message = fields.Text()
    line_ids = fields.One2many(
        "ob.excel.import.log.line",
        "log_id",
        string="Log Lines",
    )
    failed_line_ids = fields.One2many(
        "ob.excel.import.failed.line",
        "import_log_id",
        string="Not Imported Lines",
    )
    failed_line_count = fields.Integer(
        compute="_compute_failed_line_count",
    )

    @api.depends("failed_line_ids")
    def _compute_failed_line_count(self):
        for log in self:
            log.failed_line_count = len(log.failed_line_ids)

    def action_view_failed_lines(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Not Imported Lines"),
            "res_model": "ob.excel.import.failed.line",
            "view_mode": "list,form",
            "domain": [("import_log_id", "=", self.id)],
            "context": {"default_import_log_id": self.id},
        }


class ExcelImportLogLine(models.Model):
    _name = "ob.excel.import.log.line"
    _description = "Excel Import Log Line"
    _order = "row_number asc"

    log_id = fields.Many2one(
        "ob.excel.import.log",
        required=True,
        ondelete="cascade",
    )
    row_number = fields.Integer()
    state = fields.Selection(
        [
            ("success", "Success"),
            ("failed", "Failed"),
            ("skipped", "Skipped"),
        ],
        required=True,
    )
    target_model = fields.Char()
    target_record_id = fields.Integer()
    source_values = fields.Json()
    mapped_values = fields.Json()
    message = fields.Text()
