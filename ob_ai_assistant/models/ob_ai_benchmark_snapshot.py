from odoo import fields, models


class OBAIBenchmarkSnapshot(models.Model):
    _name = "ob.ai.benchmark.snapshot"
    _description = "AI Benchmark Snapshot"
    _order = "series_id, period_date desc"

    series_id = fields.Many2one("ob.ai.benchmark.series", required=True, ondelete="cascade")
    source_id = fields.Many2one(
        "ob.ai.benchmark.source",
        related="series_id.source_id",
        store=True,
        readonly=True,
    )
    period_date = fields.Date(required=True, string="Period Start")
    period_type = fields.Selection(
        [
            ("monthly", "Monthly"),
            ("quarterly", "Quarterly"),
            ("annual", "Annual"),
        ],
        required=True,
        default="annual",
    )

    # Statistical values — median is the primary benchmark reference point
    value = fields.Float(string="Mean Value")
    value_median = fields.Float(string="Median Value")
    percentile_10 = fields.Float(string="P10")
    percentile_25 = fields.Float(string="P25")
    percentile_75 = fields.Float(string="P75")
    percentile_90 = fields.Float(string="P90")
    sample_size = fields.Integer(string="Sample Size")

    country_code = fields.Char(string="Country Code", index=True)
    industry_code = fields.Char(string="Industry Code", index=True)
    company_size_band = fields.Selection(
        [
            ("micro", "Micro (<10 employees)"),
            ("small", "Small (10-49)"),
            ("medium", "Medium (50-249)"),
            ("large", "Large (250+)"),
            ("all", "All Sizes"),
        ],
        default="all",
    )
    currency_code = fields.Char(default="USD", string="Currency Code")
    source_label = fields.Char(string="Source Label", help="e.g. 'World Bank 2024', 'FRED Q3 2024'")
    confidence_level = fields.Selection(
        [("high", "High"), ("medium", "Medium"), ("low", "Low")],
        default="medium",
    )
    is_internal = fields.Boolean(
        default=False,
        help="True for snapshots derived from this Odoo instance's own multi-company data.",
    )
    company_id = fields.Many2one(
        "res.company",
        help="Set when this snapshot belongs to a specific internal company baseline.",
    )
    raw_data = fields.Text(string="Raw Response (JSON)")
    fetch_date = fields.Datetime(string="Fetched At", default=fields.Datetime.now)

    _sql_constraints = [
        (
            "series_period_country_industry_uniq",
            "unique(series_id, period_date, country_code, industry_code, company_size_band, company_id)",
            "A snapshot for this series/period/country/industry/size combination already exists.",
        ),
    ]

    def percentile_label(self):
        self.ensure_one()
        return {
            "p10": self.percentile_10,
            "p25": self.percentile_25,
            "median": self.value_median,
            "p75": self.percentile_75,
            "p90": self.percentile_90,
        }
