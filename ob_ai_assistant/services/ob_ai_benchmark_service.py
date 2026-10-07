import json
import logging
from datetime import date

import requests

from odoo import _, fields, models

_logger = logging.getLogger(__name__)


class OBAIBenchmarkService(models.AbstractModel):
    _name = "ob.ai.benchmark.service"
    _description = "AI Benchmark Service"

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def get_benchmark_context(self, metric_categories, company=None, country_code=None, industry_code=None):
        """Return a list of benchmark dicts for the given metric categories.

        Used by the analytics and agent services to inject benchmark context
        into prompts and health-score calculations.
        """
        company = company or self.env.company
        if not country_code:
            country_code = company.country_id.code or False
        results = []
        for category in (metric_categories or []):
            series_list = self._find_series_for_category(category)
            for series in series_list:
                ctx = series.to_context_dict(country_code=country_code, industry_code=industry_code)
                if ctx.get("period"):
                    results.append(ctx)
        return results

    def get_internal_baselines(self, metric_categories, reference_company=None):
        """Compute this company's own trailing-12-month metrics for comparison."""
        reference_company = reference_company or self.env.company
        baselines = {}
        for category in (metric_categories or []):
            value = self._compute_internal_metric(category, reference_company)
            if value is not None:
                baselines[category] = {"value": value, "source": "internal", "company": reference_company.name}
        return baselines

    def compare_to_benchmarks(self, internal_baselines, metric_categories, company=None, country_code=None, industry_code=None):
        """Return a comparison dict: {category: {internal, benchmark_median, gap_pct, percentile_band}}."""
        benchmark_context = self.get_benchmark_context(
            metric_categories,
            company=company,
            country_code=country_code,
            industry_code=industry_code,
        )
        benchmark_by_category = {}
        for ctx in benchmark_context:
            cat = ctx.get("metric_category") or ctx.get("kpi_code")
            if cat and cat not in benchmark_by_category:
                benchmark_by_category[cat] = ctx

        comparison = {}
        for category in metric_categories:
            internal = internal_baselines.get(category)
            benchmark = benchmark_by_category.get(category)
            if internal is None or not benchmark:
                continue
            internal_value = internal.get("value") if isinstance(internal, dict) else internal
            median = benchmark.get("value_median") or benchmark.get("value") or 0
            gap_pct = ((internal_value - median) / median * 100) if median else None
            percentile_band = self._percentile_band(
                internal_value,
                benchmark.get("percentile_25", 0),
                benchmark.get("value_median", 0),
                benchmark.get("percentile_75", 0),
            )
            comparison[category] = {
                "internal": internal_value,
                "benchmark_median": median,
                "benchmark_p25": benchmark.get("percentile_25"),
                "benchmark_p75": benchmark.get("percentile_75"),
                "gap_pct": round(gap_pct, 1) if gap_pct is not None else None,
                "percentile_band": percentile_band,
                "period": benchmark.get("period"),
                "source": benchmark.get("source"),
                "unit": benchmark.get("unit", ""),
            }
        return comparison

    def sync_source(self, source):
        """Trigger a sync for a single benchmark source. Returns {count, error}."""
        if source.source_type == "public_api":
            return self._sync_public_api(source)
        if source.source_type == "internal":
            return self._sync_internal(source)
        return {"count": 0, "error": _("Source type '%s' does not support automatic sync.", source.source_type)}

    def sync_all_due(self):
        """Called by scheduled action — sync all active sources that are due."""
        today = fields.Date.today()
        sources = self.env["ob.ai.benchmark.source"].search([("active", "=", True), ("source_type", "in", ["public_api", "internal"])])
        total = 0
        for source in sources:
            if not self._is_sync_due(source, today):
                continue
            try:
                result = self.sync_source(source)
                total += result.get("count", 0)
                error = result.get("error")
                source.write({
                    "last_sync": fields.Datetime.now(),
                    "sync_error": error or False,
                })
            except Exception as exc:  # noqa: BLE001
                _logger.exception("Benchmark sync failed for source %s", source.name)
                source.write({"sync_error": str(exc)})
        return total

    def build_prompt_context(self, metric_categories, company=None, country_code=None, industry_code=None):
        """Return a compact JSON-serialisable dict for injecting into AI prompts."""
        baselines = self.get_internal_baselines(metric_categories, reference_company=company)
        comparison = self.compare_to_benchmarks(
            baselines,
            metric_categories,
            company=company,
            country_code=country_code,
            industry_code=industry_code,
        )
        return {
            "internal_baselines": baselines,
            "benchmark_comparison": comparison,
            "country_code": country_code,
            "industry_code": industry_code,
        }

    # ------------------------------------------------------------------ #
    # Internal helpers — sync
    # ------------------------------------------------------------------ #

    def _sync_public_api(self, source):
        api_key = source.get_api_key()
        headers = self._build_auth_headers(source, api_key)
        count = 0
        for series in source.series_ids.filtered("active"):
            if not series.external_series_id:
                continue
            try:
                snapshots = self._fetch_series_snapshots(source, series, headers)
                for snapshot_vals in snapshots:
                    self._upsert_snapshot(series, snapshot_vals)
                    count += 1
            except Exception as exc:  # noqa: BLE001
                _logger.warning("Failed to sync series %s from %s: %s", series.code, source.name, exc)
        return {"count": count}

    def _sync_internal(self, source):
        """Derive benchmark snapshots from multi-company data in this Odoo instance."""
        companies = self.env["res.company"].sudo().search([("id", "!=", self.env.company.id)])
        count = 0
        today = fields.Date.today()
        for series in source.series_ids.filtered("active"):
            values = []
            for company in companies:
                value = self._compute_internal_metric(series.metric_category, company)
                if value is not None:
                    values.append(value)
            if not values:
                continue
            values_sorted = sorted(values)
            n = len(values_sorted)
            snapshot_vals = {
                "period_date": date(today.year, today.month, 1),
                "period_type": "monthly",
                "value": sum(values_sorted) / n,
                "value_median": self._median(values_sorted),
                "percentile_25": self._percentile(values_sorted, 25),
                "percentile_75": self._percentile(values_sorted, 75),
                "sample_size": n,
                "is_internal": True,
                "confidence_level": "high" if n >= 5 else "medium" if n >= 2 else "low",
                "source_label": "Internal multi-company %s" % str(today)[:7],
            }
            self._upsert_snapshot(series, snapshot_vals)
            count += 1
        return {"count": count}

    def _fetch_series_snapshots(self, source, series, headers):
        """Generic HTTP fetch. Override or extend for specific APIs."""
        url = "%s/%s" % (source.api_url.rstrip("/"), series.external_series_id)
        try:
            response = requests.get(url, headers=headers, timeout=15)
            response.raise_for_status()
            data = response.json()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError("HTTP error fetching %s: %s" % (url, exc)) from exc
        return self._parse_generic_api_response(data, series)

    def _parse_generic_api_response(self, data, series):
        """Parse a generic {observations: [{date, value}]} API response."""
        if isinstance(data, dict):
            observations = data.get("observations") or data.get("data") or data.get("values") or []
        elif isinstance(data, list):
            observations = data
        else:
            return []
        snapshots = []
        for obs in observations:
            if isinstance(obs, dict):
                raw_date = obs.get("date") or obs.get("period") or obs.get("time")
                raw_value = obs.get("value") or obs.get("val") or obs.get("v")
            elif isinstance(obs, (list, tuple)) and len(obs) >= 2:
                raw_date, raw_value = str(obs[0]), obs[1]
            else:
                continue
            try:
                period_date = fields.Date.from_string(str(raw_date)[:10])
                value = float(raw_value)
            except Exception:  # noqa: BLE001
                continue
            snapshots.append({
                "period_date": period_date,
                "period_type": series.frequency,
                "value": value,
                "value_median": value,
                "confidence_level": "medium",
                "source_label": "%s %s" % (series.source_id.name, str(period_date)[:7]),
            })
        return snapshots

    def _upsert_snapshot(self, series, vals):
        domain = [
            ("series_id", "=", series.id),
            ("period_date", "=", vals["period_date"]),
            ("country_code", "=", vals.get("country_code", False)),
            ("industry_code", "=", vals.get("industry_code", False)),
            ("company_size_band", "=", vals.get("company_size_band", "all")),
            ("company_id", "=", vals.get("company_id", False)),
        ]
        existing = self.env["ob.ai.benchmark.snapshot"].sudo().search(domain, limit=1)
        write_vals = dict(vals)
        write_vals["series_id"] = series.id
        if "raw_data" not in write_vals:
            write_vals["raw_data"] = json.dumps(vals)
        if existing:
            existing.write(write_vals)
        else:
            self.env["ob.ai.benchmark.snapshot"].sudo().create(write_vals)

    # ------------------------------------------------------------------ #
    # Internal helpers — internal metric computation
    # ------------------------------------------------------------------ #

    def _compute_internal_metric(self, metric_category, company):
        env = self.env
        try:
            if metric_category == "revenue":
                return self._sum_field("sale.order", "amount_total", [("state", "=", "sale"), ("company_id", "=", company.id)], env)
            if metric_category == "margin":
                revenue = self._sum_field("sale.order", "amount_total", [("state", "=", "sale"), ("company_id", "=", company.id)], env)
                cost = self._sum_field("sale.order", "amount_tax", [("state", "=", "sale"), ("company_id", "=", company.id)], env) or 0
                return round((revenue - cost) / revenue * 100, 2) if revenue else None
            if metric_category == "ar_days":
                return self._compute_ar_days(company, env)
            if metric_category == "inventory_turns":
                return self._compute_inventory_turns(company, env)
            if metric_category == "employee_count":
                return env["hr.employee"].sudo().search_count([("company_id", "=", company.id), ("active", "=", True)]) if "hr.employee" in env else None
        except Exception:  # noqa: BLE001
            return None
        return None

    def _sum_field(self, model_name, field_name, domain, env):
        if model_name not in env:
            return None
        result = env[model_name].sudo().read_group(domain, [field_name], [])
        return result[0].get(field_name) if result else 0.0

    def _compute_ar_days(self, company, env):
        if "account.move" not in env:
            return None
        receivables = env["account.move"].sudo().search([
            ("move_type", "in", ["out_invoice", "out_refund"]),
            ("state", "=", "posted"),
            ("payment_state", "!=", "paid"),
            ("company_id", "=", company.id),
        ])
        if not receivables:
            return None
        today = fields.Date.today()
        ages = [(today - (rec.invoice_date or today)).days for rec in receivables]
        return round(sum(ages) / len(ages), 1)

    def _compute_inventory_turns(self, company, env):
        if "stock.quant" not in env or "stock.move" not in env:
            return None
        avg_inventory = self._sum_field("stock.quant", "value", [("company_id", "=", company.id)], env) or 0
        cogs = self._sum_field("stock.move", "price_unit", [("company_id", "=", company.id), ("state", "=", "done")], env) or 0
        return round(cogs / avg_inventory, 2) if avg_inventory else None

    # ------------------------------------------------------------------ #
    # Internal helpers — lookups / math
    # ------------------------------------------------------------------ #

    def _find_series_for_category(self, category):
        return self.env["ob.ai.benchmark.series"].search([
            ("metric_category", "=", category),
            ("active", "=", True),
            "|", ("source_id.company_id", "=", False), ("source_id.company_id", "=", self.env.company.id),
        ])

    def _is_sync_due(self, source, today):
        if not source.last_sync:
            return True
        last_sync_date = source.last_sync.date() if hasattr(source.last_sync, "date") else source.last_sync
        schedule = source.refresh_schedule
        if schedule == "daily":
            return (today - last_sync_date).days >= 1
        if schedule == "weekly":
            return (today - last_sync_date).days >= 7
        if schedule == "monthly":
            return (today - last_sync_date).days >= 30
        return False

    def _build_auth_headers(self, source, api_key):
        headers = {"Accept": "application/json"}
        if not api_key or source.auth_type == "none":
            return headers
        if source.auth_type == "api_key_header":
            headers[source.auth_header_name or "X-Api-Key"] = api_key
        elif source.auth_type == "bearer":
            headers["Authorization"] = "Bearer %s" % api_key
        return headers

    def _percentile_band(self, value, p25, median, p75):
        if value is None:
            return "unknown"
        if value >= p75:
            return "top_quartile"
        if value >= median:
            return "above_median"
        if value >= p25:
            return "below_median"
        return "bottom_quartile"

    def _median(self, sorted_values):
        n = len(sorted_values)
        if not n:
            return 0.0
        mid = n // 2
        return sorted_values[mid] if n % 2 else (sorted_values[mid - 1] + sorted_values[mid]) / 2

    def _percentile(self, sorted_values, pct):
        n = len(sorted_values)
        if not n:
            return 0.0
        index = int(pct / 100 * (n - 1))
        return sorted_values[min(index, n - 1)]
