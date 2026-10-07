import base64
import warnings
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestObOCRAILocal(TransactionCase):

    def test_paddle_provider_is_default_for_new_documents(self):
        paddle_provider = self.env.ref("ob_ocr_ai_local.ocr_provider_local_ai")
        tesseract_provider = self.env.ref("ob_ocr_base.ocr_provider_tesseract")

        self.assertTrue(paddle_provider.is_default)
        self.assertFalse(tesseract_provider.is_default)

        document = self.env["ob.ocr.document"].create({
            "document_type_id": self.env.ref("ob_ocr_base.document_type_generic_document").id,
            "file": base64.b64encode(b"default provider"),
            "filename": "default.txt",
            "mimetype": "text/plain",
        })

        self.assertEqual(document.ocr_provider_id, paddle_provider)

    def test_reviewed_document_creates_feedback_example(self):
        provider = self.env.ref("ob_ocr_ai_local.ocr_provider_local_ai")
        document = self.env["ob.ocr.document"].create({
            "document_type_id": self.env.ref("ob_ocr_base.document_type_generic_document").id,
            "ocr_provider_id": provider.id,
            "file": base64.b64encode(b"invoice"),
            "filename": "invoice.txt",
            "mimetype": "text/plain",
            "raw_text": "Invoice # INV-001 Vendor: Example Supplier Total: 10.00",
            "extracted_json": {
                "vendor_name": "Example Supplier",
                "bill_number": "INV-001",
                "total_amount": "10.00",
            },
        })

        document.action_mark_reviewed()

        example = self.env["ob.ocr.feedback.example"].search([("document_id", "=", document.id)], limit=1)
        self.assertTrue(example)
        self.assertEqual(example.partner_name, "Example Supplier")
        self.assertEqual(example.reference_text, "INV-001")

    def test_stub_backend_reuses_feedback_example(self):
        provider = self.env.ref("ob_ocr_ai_local.ocr_provider_local_ai")
        provider.write({
            "ai_backend": "stub",
            "ai_feedback_enabled": True,
            "ai_example_limit": 1,
        })

        source_document = self.env["ob.ocr.document"].create({
            "document_type_id": self.env.ref("ob_ocr_base.document_type_generic_document").id,
            "ocr_provider_id": provider.id,
            "file": base64.b64encode(b"invoice source"),
            "filename": "invoice_source.txt",
            "mimetype": "text/plain",
            "raw_text": "Vendor: Wunschgutschein GmbH Invoice # WG-001 Total: 50.00 EUR",
            "extracted_json": {
                "vendor_name": "Wunschgutschein GmbH",
                "bill_number": "WG-001",
                "currency": "EUR",
                "total_amount": "50.00",
            },
        })
        source_document.action_mark_reviewed()

        new_document = self.env["ob.ocr.document"].create({
            "document_type_id": self.env.ref("ob_ocr_base.document_type_generic_document").id,
            "ocr_provider_id": provider.id,
            "file": base64.b64encode(b"invoice target"),
            "filename": "invoice_target.txt",
            "mimetype": "text/plain",
            "raw_text": "RECHNUNG Wunschgutschein GmbH GESAMT 50,00 EUR",
        })

        payload = provider.extract_json(new_document, {"fields": ["vendor_name", "bill_number", "currency", "total_amount"]})

        self.assertEqual(payload.get("vendor_name"), "Wunschgutschein GmbH")
        self.assertEqual(payload.get("bill_number"), "WG-001")

    def test_runtime_diagnostics_accept_paddleocr_on_macos_arm64(self):
        provider = self.env.ref("ob_ocr_ai_local.ocr_provider_local_ai")
        provider.write({
            "ai_ocr_backend": "paddleocr",
            "ai_backend": "stub",
        })
        runtime_service = self.env["ob.ocr.ai.runtime.service"]

        with patch("odoo.addons.ob_ocr_ai_local.services.ocr_ai_runtime_service.platform.system", return_value="Darwin"):
            with patch("odoo.addons.ob_ocr_ai_local.services.ocr_ai_runtime_service.platform.machine", return_value="arm64"):
                with patch.object(type(runtime_service), "_missing_modules", return_value=[]):
                    diagnostics = runtime_service.get_provider_runtime_status(provider)

        self.assertEqual(diagnostics.get("status"), "ready")
        self.assertIn("ready", diagnostics.get("message").lower())

    def test_runtime_diagnostics_flag_unsupported_paddleocr_platform(self):
        provider = self.env.ref("ob_ocr_ai_local.ocr_provider_local_ai")
        provider.write({
            "ai_ocr_backend": "paddleocr",
            "ai_backend": "stub",
        })
        runtime_service = self.env["ob.ocr.ai.runtime.service"]

        with patch("odoo.addons.ob_ocr_ai_local.services.ocr_ai_runtime_service.platform.system", return_value="Darwin"):
            with patch("odoo.addons.ob_ocr_ai_local.services.ocr_ai_runtime_service.platform.machine", return_value="x86_64"):
                diagnostics = runtime_service.get_provider_runtime_status(provider)

        self.assertEqual(diagnostics.get("status"), "unsupported_platform")
        self.assertIn("x86_64", diagnostics.get("message"))

    def test_runtime_diagnostics_explain_optional_transformers_gap_on_python_313(self):
        provider = self.env.ref("ob_ocr_ai_local.ocr_provider_local_ai")
        provider.write({
            "ai_ocr_backend": "paddleocr",
            "ai_backend": "transformers_text",
        })
        runtime_service = self.env["ob.ocr.ai.runtime.service"]

        with patch.object(type(runtime_service), "_check_paddleocr_runtime", return_value=("ready", False, False)):
            with patch("odoo.addons.ob_ocr_ai_local.services.ocr_ai_runtime_service.platform.system", return_value="Darwin"):
                with patch("odoo.addons.ob_ocr_ai_local.services.ocr_ai_runtime_service.sys.version_info", (3, 13, 0)):
                    diagnostics = runtime_service.get_provider_runtime_status(provider)

        self.assertEqual(diagnostics.get("status"), "ready")
        self.assertIn("PaddleOCR text extraction is ready", diagnostics.get("message"))
        self.assertIn("Python 3.13.0", diagnostics.get("message"))
        self.assertIn("optional", diagnostics.get("message").lower())
        self.assertIn("fallback extraction path", diagnostics.get("message"))

    def test_paddleocr_provider_maps_language_and_builds_layout(self):
        provider = self.env.ref("ob_ocr_ai_local.ocr_provider_local_ai")
        service = self.env["ob.ocr.provider.local.ai.service"]
        provider.write({
            "ai_ocr_backend": "paddleocr",
            "ai_paddleocr_lang": "latin",
        })
        document = self.env["ob.ocr.document"].create({
            "document_type_id": self.env.ref("ob_ocr_base.document_type_generic_document").id,
            "ocr_provider_id": provider.id,
            "file": base64.b64encode(b"paddle"),
            "filename": "paddle.txt",
            "mimetype": "text/plain",
            "detected_language": "deu",
        })

        resolved_language = service._resolve_paddleocr_language(provider, document=document)
        texts, scores, layout_page = service._coerce_paddle_page_result({
            "rec_texts": ["Rechnung RG-2026-2100"],
            "rec_scores": [0.98],
            "dt_polys": [[[10, 20], [210, 20], [210, 44], [10, 44]]],
        }, page_number=1)

        self.assertEqual(resolved_language, "de")
        self.assertEqual(texts, ["Rechnung RG-2026-2100"])
        self.assertEqual(scores, [0.98])
        self.assertEqual(layout_page.get("page_num"), 1)
        self.assertTrue(layout_page.get("lines"))
        self.assertTrue(layout_page["lines"][0].get("words"))

    def test_paddleocr_searchable_pdf_uses_native_text_layout(self):
        provider = self.env.ref("ob_ocr_ai_local.ocr_provider_local_ai")
        service = self.env["ob.ocr.provider.local.ai.service"]
        provider.write({
            "ai_ocr_backend": "paddleocr",
            "ai_paddleocr_use_native_pdf_text": True,
        })
        document = self.env["ob.ocr.document"].create({
            "document_type_id": self.env.ref("ob_ocr_base.document_type_generic_document").id,
            "ocr_provider_id": provider.id,
            "file": base64.b64encode(b"%PDF-1.4 fake"),
            "filename": "searchable.pdf",
            "mimetype": "application/pdf",
        })
        searchable_pages = [
            "Lander, Kohlmann & Partner\n"
            "Rechnung -Nr. 2026/2218\n"
            "Gebuehrentext nach StBVV\n"
            "Einkommensteuererklaerung 1.260,75\n"
            "Pauschale 1.260,75\n"
            "Zwischensumme netto 2.521,50 EUR\n"
            "Umsatzsteuer 486,69 EUR\n"
            "Rechnungsbetrag 3.048,19 EUR\n"
        ] * 3

        with patch.object(type(service), "_extract_native_pdf_pages", return_value=searchable_pages):
            with patch.object(type(service), "_build_paddleocr_pipeline") as mocked_pipeline:
                result = service._extract_text_paddleocr(provider, document)

        self.assertEqual(result.get("text"), "\n\n".join(searchable_pages).strip())
        self.assertEqual(result.get("layout_json", {}).get("source"), "native_pdf_text")
        self.assertTrue(result.get("layout_json", {}).get("pages"))
        self.assertTrue(result["layout_json"]["pages"][0].get("lines"))
        mocked_pipeline.assert_not_called()

    def test_paddleocr_searchable_pdf_rejects_garbled_native_text(self):
        service = self.env["ob.ocr.provider.local.ai.service"]
        garbled_pages = [
            "\"\";<fl-']?JX!f!!F'!f-\\l(!!Ur!'t-'f'l\"(!S'1!S(orr'V\"t]'C= ,!o'\n"
            "BMW %nk CimbH, 8u787 Munchen\n"
            "DACH Schutzbekleidung CimbH & Co. KCi\n"
            "13882966 vom 03.02.2024\n"
            "Leasingrate 19,00'/o USt von Gesamtsumme monatlichnetto 977,22 brutto\n"
            "Betrag EUR 851,97 33,39 24,06 67,80 977,22 185,67 1.162,89\n"
            "Weitere Vertragsinformationen und footer text\n"
            "Noch eine Zeile mit genug Lange fur den Schwellwert.\n"
        ] * 3

        self.assertFalse(service._should_use_native_pdf_text_only("\n\n".join(garbled_pages), garbled_pages))

    def test_validate_runtime_action_returns_notification(self):
        provider = self.env.ref("ob_ocr_ai_local.ocr_provider_local_ai")
        action = provider.action_validate_ai_runtime()
        self.assertEqual(action.get("type"), "ir.actions.client")
        self.assertEqual(action.get("tag"), "display_notification")

    def test_runtime_missing_modules_suppresses_paddle_ccache_warning(self):
        runtime_service = self.env["ob.ocr.ai.runtime.service"]

        def _fake_import(module_name):
            warnings.warn(
                "No ccache found. Please be aware that recompiling all source files may be required.",
                UserWarning,
            )
            return object()

        with patch("odoo.addons.ob_ocr_ai_local.services.ocr_ai_runtime_service.importlib.import_module", side_effect=_fake_import):
            with warnings.catch_warnings(record=True) as captured:
                warnings.simplefilter("always")
                missing = runtime_service._missing_modules(["paddle"])

        self.assertEqual(missing, [])
        self.assertFalse(captured)
