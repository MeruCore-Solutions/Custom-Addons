import json
import logging
from datetime import date
from dateutil.relativedelta import relativedelta

from odoo import _, fields, models

_logger = logging.getLogger(__name__)

BENCHMARK_CATEGORIES = [
    "revenue",
    "margin",
    "growth",
    "ar_days",
    "inventory_turns",
    "employee_count",
]


class OBAIAnalyticsService(models.AbstractModel):
    _name = "ob.ai.analytics.service"
    _description = "AI Strategic Analytics Service"

    # ------------------------------------------------------------------ #
    # Health Scoring
    # ------------------------------------------------------------------ #

    def compute_health_score(self, conversation=None, company=None, provider=None, model=None):
        """Compute and persist a health score for the given company.

        Returns the ob.ai.health.score record.
        """
        company = company or (conversation.company_id if conversation else self.env.company)
        metrics = self._gather_health_metrics(company)
        domain_scores = self._score_domains(metrics, company)
        health = self.env["ob.ai.health.score"].create({
            "company_id": company.id,
            "conversation_id": conversation.id if conversation else False,
            "score_date": fields.Date.today(),
            "liquidity_score": domain_scores.get("liquidity", 0.0),
            "growth_score": domain_scores.get("growth", 0.0),
            "execution_score": domain_scores.get("execution", 0.0),
            "pipeline_score": domain_scores.get("pipeline", 0.0),
            "fulfillment_score": domain_scores.get("fulfillment", 0.0),
            "receivable_score": domain_scores.get("receivable", 0.0),
            "metrics_payload": json.dumps(metrics, default=str),
            "status": "computed",
        })
        warnings = self._detect_warnings(metrics, domain_scores)
        if warnings:
            health.warnings_payload = json.dumps(warnings)
        if provider and model:
            self._generate_health_narrative(health, metrics, domain_scores, provider, model)
        return health

    def recompute_health_score(self, health_record):
        company = health_record.company_id
        metrics = self._gather_health_metrics(company)
        domain_scores = self._score_domains(metrics, company)
        health_record.write({
            "liquidity_score": domain_scores.get("liquidity", 0.0),
            "growth_score": domain_scores.get("growth", 0.0),
            "execution_score": domain_scores.get("execution", 0.0),
            "pipeline_score": domain_scores.get("pipeline", 0.0),
            "fulfillment_score": domain_scores.get("fulfillment", 0.0),
            "receivable_score": domain_scores.get("receivable", 0.0),
            "metrics_payload": json.dumps(metrics, default=str),
            "warnings_payload": json.dumps(self._detect_warnings(metrics, domain_scores)),
            "status": "computed",
        })

    # ------------------------------------------------------------------ #
    # Forecasting
    # ------------------------------------------------------------------ #

    def run_forecast(self, conversation=None, forecast_type="revenue", periods=3, period_unit="month", company=None, provider=None, model=None):
        company = company or (conversation.company_id if conversation else self.env.company)
        historical_data = self._gather_historical_data(forecast_type, company, lookback_months=12)
        forecast_data, methodology, assumptions = self._compute_forecast(
            historical_data, periods, period_unit
        )
        forecast_run = self.env["ob.ai.forecast.run"].create({
            "name": _("%(ftype)s Forecast — %(company)s %(date)s", ftype=forecast_type.replace("_", " ").title(), company=company.name, date=str(fields.Date.today())[:7]),
            "company_id": company.id,
            "conversation_id": conversation.id if conversation else False,
            "forecast_type": forecast_type,
            "forecast_periods": periods,
            "period_unit": period_unit,
            "historical_from": historical_data[0]["period"] if historical_data else False,
            "historical_to": historical_data[-1]["period"] if historical_data else False,
            "methodology": methodology,
            "assumptions": assumptions,
            "forecast_payload": json.dumps(forecast_data, default=str),
            "status": "done",
        })
        if provider and model:
            self._generate_forecast_narrative(forecast_run, historical_data, forecast_data, provider, model)
        return forecast_run

    # ------------------------------------------------------------------ #
    # Scenario Simulation
    # ------------------------------------------------------------------ #

    def run_scenario(self, conversation=None, scenario_type="custom", parameters=None, company=None, provider=None, model=None):
        company = company or (conversation.company_id if conversation else self.env.company)
        baseline = self._gather_scenario_baseline(company)
        impact, sensitivity = self._simulate_scenario(scenario_type, parameters or {}, baseline)
        scenario_run = self.env["ob.ai.scenario.run"].create({
            "name": _("%(stype)s Scenario — %(company)s %(date)s", stype=scenario_type.replace("_", " ").title(), company=company.name, date=str(fields.Date.today())),
            "company_id": company.id,
            "conversation_id": conversation.id if conversation else False,
            "scenario_type": scenario_type,
            "parameter_payload": json.dumps(parameters or {}, default=str),
            "baseline_payload": json.dumps(baseline, default=str),
            "impact_payload": json.dumps(impact, default=str),
            "sensitivity_payload": json.dumps(sensitivity, default=str),
            "status": "done",
        })
        if provider and model:
            self._generate_scenario_narrative(scenario_run, baseline, impact, provider, model)
        return scenario_run

    # ------------------------------------------------------------------ #
    # Narrative generation (calls AI provider)
    # ------------------------------------------------------------------ #

    def _generate_health_narrative(self, health_record, metrics, domain_scores, provider, model):
        benchmark_service = self.env["ob.ai.benchmark.service"]
        company = health_record.company_id
        baselines = {cat: {"value": metrics.get(cat)} for cat in BENCHMARK_CATEGORIES if metrics.get(cat) is not None}
        comparison = benchmark_service.compare_to_benchmarks(
            baselines, BENCHMARK_CATEGORIES, company=company
        )
        system_prompt = "\n".join([
            "You are a senior business analyst. Generate a concise executive health report.",
            "Use the supplied domain scores, raw metrics, and benchmark comparison.",
            "Structure: 1) Overall assessment 2) Domain highlights 3) Early warnings 4) Top 3 recommended actions.",
            "Be data-driven. Reference specific numbers. Keep it under 400 words.",
            "Today: %s" % fields.Date.today(),
        ])
        user_content = json.dumps({
            "overall_score": health_record.overall_score,
            "overall_grade": health_record.overall_grade,
            "domain_scores": domain_scores,
            "metrics": metrics,
            "benchmark_comparison": comparison,
        }, default=str)
        try:
            result = self.env["ob.ai.provider.service"].generate_text(
                provider, model, system_prompt, [{"role": "user", "content": user_content}]
            )
            text = (result.get("text") or "").strip()
            health_record.write({
                "analysis_text": text,
                "recommendations": self._extract_recommendations(text),
                "benchmark_gap_text": self._format_benchmark_gap(comparison),
            })
        except Exception as exc:  # noqa: BLE001
            _logger.warning("Health score narrative failed: %s", exc)

    def _generate_forecast_narrative(self, forecast_run, historical_data, forecast_data, provider, model):
        system_prompt = "\n".join([
            "You are a financial analyst. Summarise this forecast clearly and concisely.",
            "Include: trend observed, projected values by period, key assumptions, confidence caveats.",
            "Keep it under 200 words.",
        ])
        user_content = json.dumps({
            "forecast_type": forecast_run.forecast_type,
            "methodology": forecast_run.methodology,
            "historical": historical_data[-6:],
            "forecast": forecast_data,
            "assumptions": forecast_run.assumptions,
        }, default=str)
        try:
            result = self.env["ob.ai.provider.service"].generate_text(
                provider, model, system_prompt, [{"role": "user", "content": user_content}]
            )
            forecast_run.result_text = (result.get("text") or "").strip()
        except Exception as exc:  # noqa: BLE001
            _logger.warning("Forecast narrative failed: %s", exc)

    def _generate_scenario_narrative(self, scenario_run, baseline, impact, provider, model):
        system_prompt = "\n".join([
            "You are a business strategist. Summarise this scenario analysis.",
            "Include: what changed, projected impact per metric, key risks, recommended mitigation.",
            "Keep it under 200 words.",
        ])
        user_content = json.dumps({
            "scenario_type": scenario_run.scenario_type,
            "parameters": scenario_run.get_parameters(),
            "baseline": baseline,
            "impact": impact,
        }, default=str)
        try:
            result = self.env["ob.ai.provider.service"].generate_text(
                provider, model, system_prompt, [{"role": "user", "content": user_content}]
            )
            scenario_run.result_text = (result.get("text") or "").strip()
        except Exception as exc:  # noqa: BLE001
            _logger.warning("Scenario narrative failed: %s", exc)

    # ------------------------------------------------------------------ #
    # Health metric gathering
    # ------------------------------------------------------------------ #

    def _gather_health_metrics(self, company):
        env = self.env
        today = fields.Date.today()
        month_start = date(today.year, today.month, 1)
        year_start = date(today.year, 1, 1)
        metrics = {}

        # Revenue — current month and year-to-date
        if "sale.order" in env:
            metrics["revenue_mtd"] = self._agg("sale.order", "amount_total", [
                ("state", "=", "sale"), ("company_id", "=", company.id),
                ("date_order", ">=", month_start),
            ], env)
            metrics["revenue_ytd"] = self._agg("sale.order", "amount_total", [
                ("state", "=", "sale"), ("company_id", "=", company.id),
                ("date_order", ">=", year_start),
            ], env)
            # Revenue same month last year (for growth calc)
            last_year_month_start = month_start - relativedelta(years=1)
            last_year_month_end = month_start - relativedelta(days=1)
            metrics["revenue_same_month_last_year"] = self._agg("sale.order", "amount_total", [
                ("state", "=", "sale"), ("company_id", "=", company.id),
                ("date_order", ">=", last_year_month_start),
                ("date_order", "<=", last_year_month_end),
            ], env)

        # Open invoices / receivables
        if "account.move" in env:
            metrics["overdue_ar"] = self._count("account.move", [
                ("move_type", "in", ["out_invoice"]),
                ("state", "=", "posted"),
                ("payment_state", "!=", "paid"),
                ("invoice_date_due", "<", today),
                ("company_id", "=", company.id),
            ], env)
            metrics["ar_total"] = self._agg("account.move", "amount_residual", [
                ("move_type", "in", ["out_invoice"]),
                ("state", "=", "posted"),
                ("payment_state", "!=", "paid"),
                ("company_id", "=", company.id),
            ], env)

        # Deliveries
        if "stock.picking" in env:
            metrics["late_deliveries"] = self._count("stock.picking", [
                ("picking_type_code", "=", "outgoing"),
                ("state", "not in", ["done", "cancel"]),
                ("scheduled_date", "<", today),
                ("company_id", "=", company.id),
            ], env)
            metrics["deliveries_today"] = self._count("stock.picking", [
                ("picking_type_code", "=", "outgoing"),
                ("state", "not in", ["done", "cancel"]),
                ("scheduled_date", "=", today),
                ("company_id", "=", company.id),
            ], env)

        # CRM pipeline
        if "crm.lead" in env:
            metrics["open_opportunities"] = self._count("crm.lead", [
                ("type", "=", "opportunity"),
                ("stage_id.is_won", "=", False),
                ("active", "=", True),
                ("company_id", "=", company.id),
            ], env)
            metrics["pipeline_value"] = self._agg("crm.lead", "expected_revenue", [
                ("type", "=", "opportunity"),
                ("stage_id.is_won", "=", False),
                ("active", "=", True),
                ("company_id", "=", company.id),
            ], env)

        # Overdue activities
        if "mail.activity" in env:
            metrics["overdue_activities"] = self._count("mail.activity", [
                ("date_deadline", "<", today),
                ("user_id.company_ids", "in", [company.id]),
            ], env)

        return metrics

    def _score_domains(self, metrics, company):
        scores = {}

        # Liquidity score — based on overdue AR ratio
        ar_total = metrics.get("ar_total") or 0
        overdue_ar = metrics.get("overdue_ar") or 0
        if ar_total > 0:
            overdue_ratio = overdue_ar / max(ar_total, 1)
            scores["liquidity"] = max(0.0, 100.0 - overdue_ratio * 200)
        else:
            scores["liquidity"] = 75.0

        # Growth score — MTD vs same month last year
        rev_mtd = metrics.get("revenue_mtd") or 0
        rev_ly = metrics.get("revenue_same_month_last_year") or 0
        if rev_ly > 0:
            growth_pct = (rev_mtd - rev_ly) / rev_ly * 100
            scores["growth"] = min(100.0, max(0.0, 50.0 + growth_pct))
        else:
            scores["growth"] = 50.0 if rev_mtd > 0 else 30.0

        # Execution score — late delivery ratio
        late = metrics.get("late_deliveries") or 0
        today_del = metrics.get("deliveries_today") or 0
        total_del = late + today_del
        if total_del > 0:
            scores["execution"] = max(0.0, 100.0 - (late / total_del * 100))
        else:
            scores["execution"] = 80.0

        # Pipeline score — open opportunities with value
        pipeline_value = metrics.get("pipeline_value") or 0
        open_opps = metrics.get("open_opportunities") or 0
        if open_opps > 0 and pipeline_value > 0:
            scores["pipeline"] = min(100.0, 50.0 + (open_opps / 10.0) + (pipeline_value / 10000.0))
        else:
            scores["pipeline"] = 30.0

        # Fulfillment score — inverse of late deliveries count
        scores["fulfillment"] = max(0.0, 100.0 - min(late, 50) * 2)

        # Receivable score — overdue count penalty
        overdue_count = metrics.get("overdue_ar") or 0
        scores["receivable"] = max(0.0, 100.0 - min(overdue_count, 50) * 2)

        return {k: round(v, 1) for k, v in scores.items()}

    def _detect_warnings(self, metrics, domain_scores):
        warnings = []
        if domain_scores.get("liquidity", 100) < 40:
            warnings.append({"domain": "liquidity", "message": "High overdue AR ratio — cash flow at risk.", "severity": "high"})
        if domain_scores.get("growth", 100) < 30:
            warnings.append({"domain": "growth", "message": "Revenue declining vs same period last year.", "severity": "high"})
        if (metrics.get("late_deliveries") or 0) > 5:
            warnings.append({"domain": "fulfillment", "message": "More than 5 late deliveries — customer satisfaction risk.", "severity": "medium"})
        if (metrics.get("overdue_activities") or 0) > 10:
            warnings.append({"domain": "execution", "message": "Over 10 overdue activities — follow-up backlog building.", "severity": "low"})
        if domain_scores.get("pipeline", 100) < 35:
            warnings.append({"domain": "pipeline", "message": "Low pipeline value — future revenue risk.", "severity": "medium"})
        return warnings

    # ------------------------------------------------------------------ #
    # Forecasting internals
    # ------------------------------------------------------------------ #

    def _gather_historical_data(self, forecast_type, company, lookback_months=12):
        today = fields.Date.today()
        data = []
        for i in range(lookback_months, 0, -1):
            period_start = today - relativedelta(months=i)
            period_end = period_start + relativedelta(months=1) - relativedelta(days=1)
            period_date = date(period_start.year, period_start.month, 1)
            value = self._get_period_value(forecast_type, company, period_start, period_end)
            data.append({"period": str(period_date), "value": value or 0.0})
        return data

    def _get_period_value(self, forecast_type, company, period_start, period_end):
        env = self.env
        if forecast_type == "revenue" and "sale.order" in env:
            return self._agg("sale.order", "amount_total", [
                ("state", "=", "sale"),
                ("company_id", "=", company.id),
                ("date_order", ">=", period_start),
                ("date_order", "<=", period_end),
            ], env)
        if forecast_type == "cashflow" and "account.move" in env:
            return self._agg("account.move", "amount_total", [
                ("move_type", "=", "out_invoice"),
                ("state", "=", "posted"),
                ("invoice_date", ">=", period_start),
                ("invoice_date", "<=", period_end),
                ("company_id", "=", company.id),
            ], env)
        return 0.0

    def _compute_forecast(self, historical_data, periods, period_unit):
        values = [p["value"] for p in historical_data if p.get("value") is not None]
        if len(values) < 2:
            return [], "insufficient_data", "Not enough historical data for a statistical forecast."
        # Linear trend via least-squares
        n = len(values)
        x_mean = (n - 1) / 2.0
        y_mean = sum(values) / n
        numerator = sum((i - x_mean) * (values[i] - y_mean) for i in range(n))
        denominator = sum((i - x_mean) ** 2 for i in range(n))
        slope = numerator / denominator if denominator else 0.0
        intercept = y_mean - slope * x_mean
        std_dev = (sum((v - (intercept + slope * i)) ** 2 for i, v in enumerate(values)) / max(n - 2, 1)) ** 0.5
        forecast_data = []
        last_period = fields.Date.from_string(historical_data[-1]["period"])
        for i in range(1, periods + 1):
            next_period = last_period + relativedelta(**{period_unit + "s": i})
            projected = intercept + slope * (n - 1 + i)
            projected = max(projected, 0.0)
            forecast_data.append({
                "period": str(date(next_period.year, next_period.month, 1)),
                "value": round(projected, 2),
                "confidence_low": round(max(projected - 1.96 * std_dev, 0), 2),
                "confidence_high": round(projected + 1.96 * std_dev, 2),
            })
        assumptions = "Linear trend projection over %d historical %ss. Slope: %.2f per period." % (n, period_unit, slope)
        return forecast_data, "linear_trend", assumptions

    # ------------------------------------------------------------------ #
    # Scenario internals
    # ------------------------------------------------------------------ #

    def _gather_scenario_baseline(self, company):
        metrics = self._gather_health_metrics(company)
        return {
            "revenue_mtd": metrics.get("revenue_mtd", 0),
            "revenue_ytd": metrics.get("revenue_ytd", 0),
            "ar_total": metrics.get("ar_total", 0),
            "pipeline_value": metrics.get("pipeline_value", 0),
            "open_opportunities": metrics.get("open_opportunities", 0),
            "late_deliveries": metrics.get("late_deliveries", 0),
        }

    def _simulate_scenario(self, scenario_type, parameters, baseline):
        change_pct = parameters.get("change_pct", 10)
        direction = parameters.get("direction", "increase")
        multiplier = (1 + change_pct / 100) if direction == "increase" else (1 - change_pct / 100)
        impact = {}
        if scenario_type == "price_change":
            new_revenue = baseline.get("revenue_mtd", 0) * multiplier
            impact["revenue_mtd"] = {"baseline": baseline.get("revenue_mtd", 0), "projected": round(new_revenue, 2), "delta": round(new_revenue - baseline.get("revenue_mtd", 0), 2), "delta_pct": change_pct if direction == "increase" else -change_pct}
            new_pipeline = baseline.get("pipeline_value", 0) * multiplier
            impact["pipeline_value"] = {"baseline": baseline.get("pipeline_value", 0), "projected": round(new_pipeline, 2), "delta": round(new_pipeline - baseline.get("pipeline_value", 0), 2), "delta_pct": change_pct if direction == "increase" else -change_pct}
        elif scenario_type == "volume_change":
            for key in ("revenue_mtd", "revenue_ytd", "pipeline_value"):
                base_val = baseline.get(key, 0)
                new_val = base_val * multiplier
                impact[key] = {"baseline": base_val, "projected": round(new_val, 2), "delta": round(new_val - base_val, 2), "delta_pct": change_pct if direction == "increase" else -change_pct}
        elif scenario_type == "customer_churn":
            churn_pct = change_pct / 100
            for key in ("revenue_mtd", "pipeline_value"):
                base_val = baseline.get(key, 0)
                new_val = base_val * (1 - churn_pct)
                impact[key] = {"baseline": base_val, "projected": round(new_val, 2), "delta": round(new_val - base_val, 2), "delta_pct": -change_pct}
        else:
            for key, base_val in baseline.items():
                if isinstance(base_val, (int, float)) and base_val:
                    new_val = base_val * multiplier
                    impact[key] = {"baseline": base_val, "projected": round(new_val, 2), "delta": round(new_val - base_val, 2), "delta_pct": change_pct if direction == "increase" else -change_pct}
        # Simple sensitivity table — vary change_pct from half to double
        sensitivity = []
        for factor in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0):
            factor_pct = change_pct * factor
            factor_mult = (1 + factor_pct / 100) if direction == "increase" else (1 - factor_pct / 100)
            sensitivity.append({"change_pct": round(factor_pct, 1), "revenue_impact": round(baseline.get("revenue_mtd", 0) * factor_mult, 2)})
        return impact, sensitivity

    # ------------------------------------------------------------------ #
    # Utility
    # ------------------------------------------------------------------ #

    def _agg(self, model_name, field_name, domain, env):
        if model_name not in env:
            return 0.0
        result = env[model_name].sudo().read_group(domain, [field_name], [])
        return result[0].get(field_name) or 0.0 if result else 0.0

    def _count(self, model_name, domain, env):
        if model_name not in env:
            return 0
        return env[model_name].sudo().search_count(domain)

    def _extract_recommendations(self, text):
        if not text:
            return ""
        lines = text.split("\n")
        rec_lines = []
        in_rec = False
        for line in lines:
            if any(kw in line.lower() for kw in ["recommend", "action", "suggest"]):
                in_rec = True
            if in_rec:
                rec_lines.append(line)
        return "\n".join(rec_lines) if rec_lines else text[-300:]

    def _format_benchmark_gap(self, comparison):
        if not comparison:
            return ""
        lines = []
        for category, data in comparison.items():
            if data.get("gap_pct") is not None:
                direction = "above" if data["gap_pct"] >= 0 else "below"
                lines.append("• %s: %+.1f%% %s industry median (%s band)" % (
                    category.replace("_", " ").title(),
                    abs(data["gap_pct"]),
                    direction,
                    (data.get("percentile_band") or "").replace("_", " "),
                ))
        return "\n".join(lines)
