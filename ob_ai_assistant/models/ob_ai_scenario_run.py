import json

from odoo import _, api, fields, models


class OBAIScenarioRun(models.Model):
    _name = "ob.ai.scenario.run"
    _description = "AI Scenario Simulation"
    _order = "create_date desc, id desc"

    name = fields.Char(required=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
    conversation_id = fields.Many2one("ob.ai.conversation", ondelete="set null")

    scenario_type = fields.Selection(
        [
            ("price_change", "Price Change Impact"),
            ("volume_change", "Volume Change"),
            ("cost_change", "Cost / COGS Change"),
            ("customer_churn", "Customer Churn"),
            ("new_customer_segment", "New Customer Segment"),
            ("headcount_change", "Headcount Change"),
            ("payment_terms_change", "Payment Terms Change"),
            ("custom", "Custom Scenario"),
        ],
        required=True,
        default="custom",
    )

    # Scenario definition — JSON object with scenario-type-specific keys
    # e.g. {"change_pct": 10, "target": "all_products", "direction": "increase"}
    parameter_payload = fields.Text(string="Scenario Parameters (JSON)")

    # Baseline metrics at time of simulation (JSON)
    baseline_payload = fields.Text(string="Baseline Metrics (JSON)")

    # Impact projection — JSON: {metric: {baseline, projected, delta, delta_pct}}
    impact_payload = fields.Text(string="Impact Projection (JSON)")

    # Sensitivity table — JSON: [{param_value, metric_value}]
    sensitivity_payload = fields.Text(string="Sensitivity Analysis (JSON)")

    result_text = fields.Text(string="AI Narrative")
    assumptions = fields.Text()

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

    def get_parameters(self):
        self.ensure_one()
        if not self.parameter_payload:
            return {}
        try:
            return json.loads(self.parameter_payload)
        except Exception:  # noqa: BLE001
            return {}

    def get_impact(self):
        self.ensure_one()
        if not self.impact_payload:
            return {}
        try:
            return json.loads(self.impact_payload)
        except Exception:  # noqa: BLE001
            return {}

    def impact_summary_text(self):
        self.ensure_one()
        impact = self.get_impact()
        if not impact:
            return _("No impact data available.")
        lines = [_("Scenario: %(name)s (%(stype)s)", name=self.name, stype=self.get_scenario_type_label())]
        for metric, values in impact.items():
            if isinstance(values, dict):
                lines.append(
                    _("  %(metric)s: %(baseline).2f → %(projected).2f  (%(delta_pct)+.1f%%)",
                      metric=metric,
                      baseline=values.get("baseline", 0),
                      projected=values.get("projected", 0),
                      delta_pct=values.get("delta_pct", 0))
                )
        if self.assumptions:
            lines.append(_("Assumptions: %s", self.assumptions))
        return "\n".join(lines)

    def get_scenario_type_label(self):
        self.ensure_one()
        return dict(self._fields["scenario_type"].selection).get(self.scenario_type, self.scenario_type)

    @api.model
    def _gc_old_runs(self, days=90):
        cutoff = fields.Date.subtract(fields.Date.today(), days=days)
        old = self.search([("create_date", "<", cutoff), ("status", "in", ["done", "failed"])])
        old.unlink()
