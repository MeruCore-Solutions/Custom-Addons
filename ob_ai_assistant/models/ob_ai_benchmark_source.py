from odoo import _, api, fields, models
from odoo.exceptions import UserError


class OBAIBenchmarkSource(models.Model):
    _name = "ob.ai.benchmark.source"
    _description = "AI Benchmark Source"
    _order = "source_type, name"

    name = fields.Char(required=True)
    source_type = fields.Selection(
        [
            ("public_api", "Public API"),
            ("internal", "Internal Multi-Company"),
            ("manual", "Manually Entered"),
            ("file_upload", "File Upload"),
        ],
        required=True,
        default="manual",
    )
    description = fields.Text()
    api_url = fields.Char(string="API Base URL")
    api_key_param = fields.Char(
        string="API Key Parameter",
        help="Name of the ir.config_parameter key that stores the API key for this source.",
    )
    auth_type = fields.Selection(
        [
            ("none", "No Auth"),
            ("api_key_query", "API Key (Query Param)"),
            ("api_key_header", "API Key (Header)"),
            ("bearer", "Bearer Token"),
        ],
        default="none",
    )
    auth_header_name = fields.Char(
        string="Auth Header Name",
        default="Authorization",
        help="Header name for API key / bearer auth, e.g. 'Authorization' or 'X-Api-Key'.",
    )
    industry_scope = fields.Char(
        help="Comma-separated industry codes this source covers, e.g. 'manufacturing,retail'. Leave blank for all.",
    )
    country_scope = fields.Char(
        help="Comma-separated ISO-3166-1 alpha-2 country codes this source covers, e.g. 'US,GB'. Leave blank for all.",
    )
    refresh_schedule = fields.Selection(
        [
            ("daily", "Daily"),
            ("weekly", "Weekly"),
            ("monthly", "Monthly"),
            ("manual", "Manual Only"),
        ],
        default="weekly",
    )
    last_sync = fields.Datetime(readonly=True, string="Last Synchronized")
    sync_error = fields.Text(readonly=True, string="Last Sync Error")
    company_id = fields.Many2one(
        "res.company",
        default=lambda self: self.env.company,
        help="Leave blank to share across all companies.",
    )
    series_ids = fields.One2many("ob.ai.benchmark.series", "source_id", string="Series")
    series_count = fields.Integer(compute="_compute_series_count", string="# Series")
    active = fields.Boolean(default=True)
    notes = fields.Text()

    @api.depends("series_ids")
    def _compute_series_count(self):
        for rec in self:
            rec.series_count = len(rec.series_ids)

    def get_api_key(self):
        self.ensure_one()
        if not self.api_key_param:
            return False
        return self.env["ir.config_parameter"].sudo().get_param(self.api_key_param)

    def action_sync_now(self):
        self.ensure_one()
        benchmark_service = self.env["ob.ai.benchmark.service"]
        result = benchmark_service.sync_source(self)
        if result.get("error"):
            raise UserError(_("Sync failed: %s", result["error"]))
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Benchmark Sync"),
                "message": _("Synchronised %(count)s snapshots from '%(source)s'.", count=result.get("count", 0), source=self.name),
                "sticky": False,
            },
        }
