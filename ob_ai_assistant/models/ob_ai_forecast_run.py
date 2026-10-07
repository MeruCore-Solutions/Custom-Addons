import json

from odoo import _, api, fields, models


class OBAIForecastRun(models.Model):
    _name = "ob.ai.forecast.run"
    _description = "AI Forecast Run"
    _order = "create_date desc, id desc"

    name = fields.Char(required=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
    conversation_id = fields.Many2one("ob.ai.conversation", ondelete="set null")
    kpi_id = fields.Many2one("ob.ai.kpi.definition", string="Target KPI", ondelete="set null")
    forecast_type = fields.Selection(
        [
            ("revenue", "Revenue Forecast"),
            ("cashflow", "Cash Flow Forecast"),
            ("pipeline_conversion", "Pipeline to Revenue"),
            ("ar_collections", "AR Collections Timeline"),
            ("inventory_demand", "Inventory Demand"),
            ("custom", "Custom KPI Forecast"),
        ],
        required=True,
        default="revenue",
    )

    # Historical window
    historical_from = fields.Date(string="Historical From")
    historical_to = fields.Date(string="Historical To")

    # Forecast horizon
    forecast_periods = fields.Integer(default=3, string="Periods Ahead")
    period_unit = fields.Selection(
        [("month", "Months"), ("quarter", "Quarters"), ("year", "Years")],
        default="month",
    )

    # Method selected by analytics service
    methodology = fields.Char(
        string="Method",
        help="e.g. linear_trend, exponential_smoothing, pipeline_weighted",
    )
    assumptions = fields.Text(help="Key assumptions made during this forecast run.")

    # Output stored as JSON array: [{period, value, confidence_low, confidence_high}]
    forecast_payload = fields.Text(string="Forecast Data (JSON)")
    result_text = fields.Text(string="AI Narrative")

    # Accuracy tracking (filled after actuals are known)
    actual_payload = fields.Text(string="Actuals (JSON)")
    mape = fields.Float(string="MAPE %", digits=(5, 2), help="Mean Absolute Percentage Error vs actuals.")

    status = fields.Selection(
        [
            ("draft", "Draft"),
            ("running", "Running"),
            ("done", "Done"),
            ("failed", "Failed"),
        ],
        default="draft",
        required=True,
    )
    error_message = fields.Text()
    create_date = fields.Datetime(string="Created At", readonly=True)

    def get_forecast_data(self):
        self.ensure_one()
        if not self.forecast_payload:
            return []
        try:
            return json.loads(self.forecast_payload)
        except Exception:  # noqa: BLE001
            return []

    def forecast_summary_text(self):
        self.ensure_one()
        data = self.get_forecast_data()
        if not data:
            return _("No forecast data available.")
        lines = [_("Forecast — %(name)s (%(method)s):", name=self.name, method=self.methodology or "auto")]
        for point in data:
            lines.append(
                _("  %(period)s: %(value).2f  [%(low).2f – %(high).2f]",
                  period=point.get("period", ""),
                  value=point.get("value", 0),
                  low=point.get("confidence_low", 0),
                  high=point.get("confidence_high", 0))
            )
        if self.assumptions:
            lines.append(_("Assumptions: %s", self.assumptions))
        return "\n".join(lines)

    @api.model
    def _gc_old_runs(self, days=90):
        cutoff = fields.Date.subtract(fields.Date.today(), days=days)
        old = self.search([("create_date", "<", cutoff), ("status", "in", ["done", "failed"])])
        old.unlink()
