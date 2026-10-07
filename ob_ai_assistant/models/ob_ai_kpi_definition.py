from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class OBAIKpiDefinition(models.Model):
    _name = "ob.ai.kpi.definition"
    _description = "AI KPI Definition"
    _order = "category, name"

    name = fields.Char(required=True)
    code = fields.Char(required=True, index=True)
    description = fields.Text()
    category = fields.Selection(
        [
            ("sales", "Sales"),
            ("finance", "Finance"),
            ("operations", "Operations"),
            ("crm", "CRM / Pipeline"),
            ("hr", "Human Resources"),
            ("procurement", "Procurement"),
            ("inventory", "Inventory"),
            ("custom", "Custom"),
        ],
        required=True,
        default="custom",
    )
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
    model_id = fields.Many2one("ir.model", string="Primary Model", ondelete="cascade")
    field_name = fields.Char(string="Primary Field")
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
    unit = fields.Char(help="e.g. USD, %, days")
    synonyms = fields.Text(help="Comma-separated alternative names used for semantic matching")
    formula_ids = fields.One2many("ob.ai.metric.formula", "kpi_id", string="Metric Formulas")
    dimension_map_ids = fields.Many2many(
        "ob.ai.dimension.map",
        "ob_ai_kpi_dimension_rel",
        "kpi_id",
        "dimension_id",
        string="Applicable Dimensions",
    )
    benchmark_series_ids = fields.One2many("ob.ai.benchmark.series", "kpi_id", string="Benchmark Series")
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ("code_company_uniq", "unique(code, company_id)", "KPI code must be unique per company."),
    ]

    @api.constrains("field_name", "model_id")
    def _check_field_exists(self):
        for rec in self:
            if rec.field_name and rec.model_id:
                model_name = rec.model_id.model
                if model_name in self.env and rec.field_name not in self.env[model_name]._fields:
                    raise ValidationError(
                        _("Field '%(field)s' does not exist on model '%(model)s'.", field=rec.field_name, model=model_name)
                    )

    def get_synonym_list(self):
        self.ensure_one()
        if not self.synonyms:
            return []
        return [s.strip().lower() for s in self.synonyms.split(",") if s.strip()]

    def build_tool_request(self, domain=None, date_from=None, date_to=None):
        self.ensure_one()
        if not self.model_id or not self.field_name:
            return {}
        request = {
            "model": self.model_id.model,
            "operation": self.aggregation if self.aggregation in ("count", "count_distinct") else "aggregate",
            "field_name": self.field_name,
            "operator": self.aggregation,
        }
        base_domain = list(domain or [])
        if date_from and self.field_name:
            base_domain.append(["create_date", ">=", str(date_from)])
        if date_to and self.field_name:
            base_domain.append(["create_date", "<=", str(date_to)])
        if base_domain:
            request["domain"] = base_domain
        return request
