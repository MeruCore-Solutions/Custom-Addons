import json

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class OBAIMetricFormula(models.Model):
    _name = "ob.ai.metric.formula"
    _description = "AI Metric Formula"
    _order = "kpi_id, sequence, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    kpi_id = fields.Many2one("ob.ai.kpi.definition", required=True, ondelete="cascade")
    formula_type = fields.Selection(
        [
            ("odoo_aggregate", "Odoo Domain + Aggregate"),
            ("cross_model", "Cross-Model Calculation"),
            ("ratio", "Ratio of Two KPIs"),
            ("delta", "Period-over-Period Delta"),
            ("custom_expression", "Custom Expression"),
        ],
        required=True,
        default="odoo_aggregate",
    )
    model_id = fields.Many2one("ir.model", string="Source Model")
    field_name = fields.Char(string="Aggregate Field")
    aggregation = fields.Selection(
        [
            ("sum", "Sum"),
            ("avg", "Average"),
            ("count", "Count"),
            ("count_distinct", "Count Distinct"),
            ("min", "Minimum"),
            ("max", "Maximum"),
        ],
        default="sum",
    )
    domain_json = fields.Text(
        string="Domain (JSON)",
        help="Odoo domain as a JSON array, e.g. [[\"state\",\"=\",\"sale\"]]",
    )
    groupby_field = fields.Char(string="Group By Field")
    numerator_kpi_id = fields.Many2one(
        "ob.ai.kpi.definition",
        string="Numerator KPI",
        help="For ratio formulas: the top KPI.",
    )
    denominator_kpi_id = fields.Many2one(
        "ob.ai.kpi.definition",
        string="Denominator KPI",
        help="For ratio formulas: the bottom KPI.",
    )
    delta_kpi_id = fields.Many2one(
        "ob.ai.kpi.definition",
        string="Delta KPI",
        help="For delta formulas: KPI to compare across periods.",
    )
    custom_expression = fields.Text(
        help="Python-safe expression evaluated server-side. Use 'env' and 'company'."
    )
    condition_json = fields.Text(
        string="Condition (JSON)",
        help="Optional additional filter applied on top of domain.",
    )
    active = fields.Boolean(default=True)
    notes = fields.Text()

    @api.constrains("domain_json")
    def _check_domain_json(self):
        for rec in self:
            if rec.domain_json:
                try:
                    parsed = json.loads(rec.domain_json)
                    if not isinstance(parsed, list):
                        raise ValidationError(_("Domain must be a JSON array."))
                except json.JSONDecodeError as exc:
                    raise ValidationError(_("Invalid JSON in Domain: %s", exc)) from exc

    def get_domain(self):
        self.ensure_one()
        if not self.domain_json:
            return []
        try:
            return json.loads(self.domain_json)
        except Exception:  # noqa: BLE001
            return []

    def to_tool_request(self, extra_domain=None):
        self.ensure_one()
        if self.formula_type not in ("odoo_aggregate", "cross_model"):
            return {}
        if not self.model_id or not self.field_name:
            return {}
        domain = list(self.get_domain())
        if extra_domain:
            domain.extend(extra_domain)
        request = {
            "model": self.model_id.model,
            "operation": "aggregate" if self.aggregation not in ("count", "count_distinct") else "count",
            "field_name": self.field_name,
            "operator": self.aggregation,
        }
        if domain:
            request["domain"] = domain
        if self.groupby_field:
            request["operation"] = "group"
            request["groupby_field"] = self.groupby_field
        return request
