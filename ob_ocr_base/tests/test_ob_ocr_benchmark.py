import base64
import os
import re
import unicodedata
from collections import Counter, defaultdict
from unittest import SkipTest

from odoo.tests.common import TransactionCase, tagged

from odoo.addons.ob_ocr_base.tests.benchmark_support import OCRBenchmarkFactory


@tagged("post_install", "-at_install")
class TestObOCRBenchmark(TransactionCase):
    """Opt-in OCR benchmark corpus for broad regression coverage."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        if not os.getenv("OB_OCR_BENCHMARK"):
            raise SkipTest("Set OB_OCR_BENCHMARK=1 to run the 100-document OCR benchmark.")
        cls.document_type = cls.env.ref("ob_ocr_vendor_bill.document_type_vendor_bill")
        cls.provider = cls.env.ref("ob_ocr_base.ocr_provider_tesseract")
        cls.factory = OCRBenchmarkFactory()

    def test_vendor_bill_benchmark_corpus(self):
        cases = self.factory.build_cases()
        self.assertEqual(len(cases), 100)

        results = []
        for case in cases:
            document = self.env["ob.ocr.document"].create({
                "document_type_id": self.document_type.id,
                "ocr_provider_id": self.provider.id,
                "file": base64.b64encode(case.content),
                "filename": case.filename,
                "mimetype": case.mimetype,
            })
            document._process_ocr()
            results.append(self._evaluate_case(case, document))

        report, summary = self._build_report(results)
        self.assertGreaterEqual(summary["field_accuracy"], 0.96, report)
        self.assertGreaterEqual(summary["document_pass_rate"], 0.90, report)

    def _evaluate_case(self, case, document):
        payload = document.extracted_json or {}
        line_items = payload.get("line_items") or []
        extracted_amounts = sorted(round(self._to_float(item.get("amount")), 2) for item in line_items)
        expected_amounts = sorted(round(value, 2) for value in case.expected.line_amounts)
        first_line_name = line_items[0].get("name") if line_items else ""

        checks = {
            "state": document.state == "done",
            "vendor_name": self._match_text(payload.get("vendor_name"), case.expected.vendor_name),
            "bill_number": self._match_text(payload.get("bill_number"), case.expected.bill_number),
            "bill_date": self._match_text(payload.get("bill_date"), case.expected.bill_date),
            "untaxed_amount": self._match_amount(payload.get("untaxed_amount"), case.expected.untaxed_amount),
            "tax_amount": self._match_amount(payload.get("tax_amount"), case.expected.tax_amount),
            "total_amount": self._match_amount(payload.get("total_amount"), case.expected.total_amount),
            "line_count": len(line_items) == case.expected.line_count and len(document.line_ids) == case.expected.line_count,
            "line_amounts": extracted_amounts == expected_amounts,
            "first_line_hint": self._match_text(first_line_name, case.expected.first_line_hint),
        }
        return {
            "case_id": case.case_id,
            "family": case.family,
            "checks": checks,
        }

    def _build_report(self, results):
        per_family = defaultdict(list)
        total_checks = 0
        passed_checks = 0
        passed_documents = 0

        for result in results:
            per_family[result["family"]].append(result)
            checks = result["checks"]
            total_checks += len(checks)
            passed_checks += sum(1 for value in checks.values() if value)
            if all(checks.values()):
                passed_documents += 1

        lines = [
            "OCR benchmark summary",
            "documents: %s" % len(results),
            "document_pass_rate: %.2f%%" % ((passed_documents / len(results)) * 100.0),
            "field_accuracy: %.2f%%" % ((passed_checks / total_checks) * 100.0),
            "family breakdown:",
        ]
        for family in sorted(per_family):
            family_results = per_family[family]
            family_total = len(family_results)
            family_pass = sum(1 for item in family_results if all(item["checks"].values()))
            counter = Counter()
            for item in family_results:
                for check_name, value in item["checks"].items():
                    if not value:
                        counter[check_name] += 1
            detail = ", ".join("%s=%s" % (name, count) for name, count in counter.most_common()) or "no failures"
            lines.append("%s: %s/%s passed, failures: %s" % (family, family_pass, family_total, detail))

        failed_cases = []
        for result in results:
            failed = [name for name, value in result["checks"].items() if not value]
            if failed:
                failed_cases.append("%s -> %s" % (result["case_id"], ", ".join(failed)))
        if failed_cases:
            lines.append("failed cases:")
            lines.extend(failed_cases[:25])

        summary = {
            "field_accuracy": passed_checks / total_checks if total_checks else 0.0,
            "document_pass_rate": passed_documents / len(results) if results else 0.0,
        }
        return "\n".join(lines), summary

    def _match_text(self, actual, expected):
        actual_norm = self._normalize_text(actual)
        expected_norm = self._normalize_text(expected)
        return bool(actual_norm and expected_norm and (actual_norm == expected_norm or expected_norm in actual_norm or actual_norm in expected_norm))

    def _match_amount(self, actual, expected):
        return abs(self._to_float(actual) - self._to_float(expected)) < 0.01

    def _normalize_text(self, value):
        if not value:
            return ""
        normalized = unicodedata.normalize("NFKD", str(value))
        normalized = normalized.encode("ascii", "ignore").decode("ascii")
        normalized = re.sub(r"[^a-z0-9]+", "", normalized.lower())
        return normalized

    def _to_float(self, value):
        if value in (False, None, ""):
            return 0.0
        cleaned = str(value).strip().replace(" ", "")
        cleaned = cleaned.replace("EUR", "").replace("USD", "").replace("GBP", "").replace("$", "").replace("€", "").replace("£", "")
        if cleaned.count(",") == 1 and cleaned.count(".") == 0:
            cleaned = cleaned.replace(",", ".")
        elif cleaned.count(",") > 0 and cleaned.count(".") > 0:
            cleaned = cleaned.replace(".", "").replace(",", ".")
        return float(cleaned)
