from odoo import _, api, fields, models


GRADE_THRESHOLDS = [
    (90, "A"),
    (75, "B"),
    (60, "C"),
    (45, "D"),
    (0, "F"),
]

DOMAIN_WEIGHTS = {
    "liquidity": 0.20,
    "growth": 0.20,
    "execution": 0.20,
    "pipeline": 0.15,
    "fulfillment": 0.15,
    "receivable": 0.10,
}


class OBAIHealthScore(models.Model):
    _name = "ob.ai.health.score"
    _description = "AI Business Health Score"
    _order = "score_date desc, id desc"

    name = fields.Char(compute="_compute_name", store=True)
    company_id = fields.Many2one(
        "res.company", required=True, default=lambda self: self.env.company
    )
    conversation_id = fields.Many2one("ob.ai.conversation", ondelete="set null")
    score_date = fields.Date(required=True, default=fields.Date.today)

    # Domain scores (0–100 each)
    liquidity_score = fields.Float(string="Liquidity", digits=(5, 1))
    growth_score = fields.Float(string="Growth", digits=(5, 1))
    execution_score = fields.Float(string="Execution", digits=(5, 1))
    pipeline_score = fields.Float(string="Pipeline Quality", digits=(5, 1))
    fulfillment_score = fields.Float(string="Fulfillment", digits=(5, 1))
    receivable_score = fields.Float(string="Receivables", digits=(5, 1))

    # Computed overall
    overall_score = fields.Float(
        string="Overall Score",
        compute="_compute_overall",
        store=True,
        digits=(5, 1),
    )
    overall_grade = fields.Char(
        compute="_compute_overall",
        store=True,
        string="Grade",
    )

    # Input metrics used to compute scores (JSON)
    metrics_payload = fields.Text(string="Input Metrics (JSON)")

    # AI-generated narrative
    analysis_text = fields.Text(string="Analysis")
    recommendations = fields.Text(string="Recommendations")
    benchmark_gap_text = fields.Text(string="Benchmark Gap Summary")

    # Early-warning flags (JSON list of {domain, message, severity})
    warnings_payload = fields.Text(string="Warnings (JSON)")

    status = fields.Selection(
        [
            ("draft", "Draft"),
            ("computed", "Computed"),
            ("reviewed", "Reviewed"),
        ],
        default="draft",
        required=True,
    )

    @api.depends("company_id", "score_date")
    def _compute_name(self):
        for rec in self:
            rec.name = _("Health Score — %(company)s %(date)s", company=rec.company_id.name or "", date=rec.score_date or "")

    @api.depends(
        "liquidity_score",
        "growth_score",
        "execution_score",
        "pipeline_score",
        "fulfillment_score",
        "receivable_score",
    )
    def _compute_overall(self):
        for rec in self:
            domain_values = {
                "liquidity": rec.liquidity_score,
                "growth": rec.growth_score,
                "execution": rec.execution_score,
                "pipeline": rec.pipeline_score,
                "fulfillment": rec.fulfillment_score,
                "receivable": rec.receivable_score,
            }
            weighted = sum(
                domain_values.get(domain, 0.0) * weight
                for domain, weight in DOMAIN_WEIGHTS.items()
            )
            rec.overall_score = round(min(max(weighted, 0.0), 100.0), 1)
            rec.overall_grade = next(
                (grade for threshold, grade in GRADE_THRESHOLDS if rec.overall_score >= threshold),
                "F",
            )

    def action_recompute(self):
        self.ensure_one()
        analytics_service = self.env["ob.ai.analytics.service"]
        analytics_service.recompute_health_score(self)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Health Score"),
                "message": _("Score recomputed: %(score).1f (%(grade)s)", score=self.overall_score, grade=self.overall_grade),
                "sticky": False,
            },
        }
