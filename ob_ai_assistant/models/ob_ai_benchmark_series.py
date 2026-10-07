from odoo import api, fields, models


class OBAIBenchmarkSeries(models.Model):
    _name = "ob.ai.benchmark.series"
    _description = "AI Benchmark Series"
    _order = "source_id, metric_category, name"

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    source_id = fields.Many2one("ob.ai.benchmark.source", required=True, ondelete="cascade")
    kpi_id = fields.Many2one(
        "ob.ai.kpi.definition",
        string="Mapped KPI",
        help="Our internal KPI definition this series maps to.",
    )
    metric_category = fields.Selection(
        [
            ("revenue", "Revenue / Sales"),
            ("margin", "Gross Margin %"),
            ("growth", "Growth Rate"),
            ("ar_days", "Accounts Receivable Days"),
            ("ap_days", "Accounts Payable Days"),
            ("inventory_turns", "Inventory Turnover"),
            ("current_ratio", "Current Ratio"),
            ("employee_count", "Employee Count"),
            ("revenue_per_employee", "Revenue per Employee"),
            ("customer_acquisition_cost", "Customer Acquisition Cost"),
            ("churn_rate", "Churn Rate %"),
            ("custom", "Custom"),
        ],
        required=True,
        default="custom",
    )
    unit = fields.Char(help="e.g. USD, %, days, ratio")
    frequency = fields.Selection(
        [
            ("monthly", "Monthly"),
            ("quarterly", "Quarterly"),
            ("annual", "Annual"),
        ],
        required=True,
        default="annual",
    )
    normalization_method = fields.Selection(
        [
            ("none", "No Normalization"),
            ("currency_usd", "Convert to USD"),
            ("percentage", "As Percentage"),
            ("per_employee", "Per Employee"),
            ("per_revenue_unit", "Per Revenue Unit"),
            ("index", "Index (base = 100)"),
        ],
        default="none",
    )
    industry_filter = fields.Char(
        help="Industry code this series is specific to. Leave blank if universal.",
    )
    country_filter = fields.Char(
        help="ISO-3166-1 alpha-2 code this series is specific to. Leave blank if universal.",
    )
    external_series_id = fields.Char(
        string="External Series ID",
        help="API-side identifier used when fetching snapshots from the source.",
    )
    snapshot_ids = fields.One2many("ob.ai.benchmark.snapshot", "series_id", string="Snapshots")
    snapshot_count = fields.Integer(compute="_compute_snapshot_count", string="# Snapshots")
    latest_value = fields.Float(compute="_compute_latest", string="Latest Value", store=False)
    latest_period = fields.Date(compute="_compute_latest", string="Latest Period", store=False)
    active = fields.Boolean(default=True)
    notes = fields.Text()

    _sql_constraints = [
        ("code_source_uniq", "unique(code, source_id)", "Series code must be unique within a source."),
    ]

    @api.depends("snapshot_ids")
    def _compute_snapshot_count(self):
        for rec in self:
            rec.snapshot_count = len(rec.snapshot_ids)

    def _compute_latest(self):
        for rec in self:
            latest = rec.snapshot_ids.sorted("period_date", reverse=True)[:1]
            rec.latest_value = latest.value if latest else 0.0
            rec.latest_period = latest.period_date if latest else False

    def get_latest_snapshot(self, country_code=None, industry_code=None):
        self.ensure_one()
        domain = [("series_id", "=", self.id)]
        if country_code:
            domain += ["|", ("country_code", "=", country_code), ("country_code", "=", False)]
        if industry_code:
            domain += ["|", ("industry_code", "=", industry_code), ("industry_code", "=", False)]
        return self.env["ob.ai.benchmark.snapshot"].search(domain, order="period_date desc", limit=1)

    def to_context_dict(self, country_code=None, industry_code=None):
        self.ensure_one()
        snapshot = self.get_latest_snapshot(country_code=country_code, industry_code=industry_code)
        result = {
            "series_name": self.name,
            "metric_category": self.metric_category,
            "unit": self.unit or "",
            "source": self.source_id.name,
            "kpi_code": self.kpi_id.code if self.kpi_id else False,
        }
        if snapshot:
            result.update({
                "period": str(snapshot.period_date),
                "value": snapshot.value,
                "value_median": snapshot.value_median,
                "percentile_25": snapshot.percentile_25,
                "percentile_75": snapshot.percentile_75,
                "confidence": snapshot.confidence_level,
                "source_label": snapshot.source_label,
            })
        return result
