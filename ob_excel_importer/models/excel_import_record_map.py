from odoo import api, fields, models


class ExcelImportRecordMap(models.Model):
    _name = "ob.excel.import.record.map"
    _description = "Excel Import Record Mapping"
    _order = "id desc"

    template_id = fields.Many2one(
        "ob.excel.import.template",
        required=True,
        ondelete="cascade",
    )
    source_key = fields.Char(required=True, index=True)
    target_model = fields.Char(required=True)
    target_record_id = fields.Integer(required=True)
    active = fields.Boolean(default=True)
    display_name = fields.Char(
        compute="_compute_display_name",
        store=True,
    )

    _sql_constraints = [
        (
            "template_source_key_unique",
            "unique(template_id, source_key, target_model)",
            "The source key is already mapped for this template and target model.",
        )
    ]

    @api.depends("source_key", "target_model", "target_record_id")
    def _compute_display_name(self):
        for record in self:
            record.display_name = "%s -> %s,%s" % (
                record.source_key or "",
                record.target_model or "",
                record.target_record_id or 0,
            )
