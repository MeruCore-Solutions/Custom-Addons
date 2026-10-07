import base64
from unittest.mock import patch

from odoo.tests.common import TransactionCase, tagged

from odoo.addons.ob_ocr_base.services.ocr_provider_service import OCRProviderService


@tagged("post_install", "-at_install")
class TestObOCRBase(TransactionCase):

    def setUp(self):
        super().setUp()
        self.document_type = self.env["ob.ocr.document.type"].create({
            "name": "Test Generic OCR Document",
            "code": "test_generic_document",
            "target_model": "res.partner",
        })
        self.provider = self.env["ob.ocr.provider"].create({
            "name": "Test Stub",
            "code": "test_stub",
            "provider_key": "stub",
            "service_model": "ob.ocr.provider.service",
            "allowed_mimetypes": "text/plain",
        })
        self.mapping = self.env["ob.ocr.mapping"].create({
            "name": "Test Partner Mapping",
            "document_type_id": self.document_type.id,
            "target_model": "res.partner",
            "schema_json": {"fields": ["partner_name"]},
        })
        self.env["ob.ocr.mapping.field"].create({
            "mapping_id": self.mapping.id,
            "name": "Partner Name",
            "source_key": "partner_name",
            "target_field": "name",
            "transform_type": "strip",
        })
        self.env["ob.ocr.extraction.rule"].create({
            "name": "Partner Name",
            "document_type_id": self.document_type.id,
            "mapping_id": self.mapping.id,
            "target_key": "partner_name",
            "pattern": r"Partner:\s*(.+)",
            "flags": "IGNORECASE",
        })

    def test_document_queue_and_process(self):
        document = self.env["ob.ocr.document"].create({
            "document_type_id": self.document_type.id,
            "mapping_id": self.mapping.id,
            "ocr_provider_id": self.provider.id,
            "file": base64.b64encode(b"Partner: Test OCR Partner"),
            "filename": "test.txt",
            "mimetype": "text/plain",
        })
        document.action_process_ocr()
        self.assertEqual(document.state, "queued")
        document._process_ocr()
        self.assertEqual(document.state, "done")
        self.assertEqual(document.extracted_json.get("partner_name"), "Test OCR Partner")

    def test_process_ocr_button_queues_instead_of_running_inline(self):
        document = self.env["ob.ocr.document"].create({
            "document_type_id": self.document_type.id,
            "mapping_id": self.mapping.id,
            "ocr_provider_id": self.provider.id,
            "file": base64.b64encode(b"Partner: Queued OCR Partner"),
            "filename": "queued.txt",
            "mimetype": "text/plain",
        })

        with patch.object(type(document), "_process_ocr") as mocked_process:
            document.process_ocr()

        self.assertEqual(document.state, "queued")
        mocked_process.assert_not_called()

    def test_process_ocr_persists_layout_json(self):
        document = self.env["ob.ocr.document"].create({
            "document_type_id": self.document_type.id,
            "mapping_id": self.mapping.id,
            "ocr_provider_id": self.provider.id,
            "file": base64.b64encode(b"Partner: Layout OCR Partner"),
            "filename": "layout.txt",
            "mimetype": "text/plain",
        })
        with patch.object(type(document), "_extract_text", return_value={
            "text": "Partner: Layout OCR Partner",
            "confidence": 88.0,
            "page_count": 1,
            "detected_language": "eng",
            "layout_json": {"source": "stub", "pages": [{"page_num": 1, "lines": [{"text": "Partner: Layout OCR Partner"}]}]},
        }):
            document._process_ocr()

        self.assertTrue(document.ocr_layout_json)
        self.assertEqual(document.ocr_layout_json.get("source"), "stub")
        self.assertEqual(document.extracted_json.get("partner_name"), "Layout OCR Partner")

    def test_generic_target_record_creation(self):
        document = self.env["ob.ocr.document"].create({
            "document_type_id": self.document_type.id,
            "mapping_id": self.mapping.id,
            "ocr_provider_id": self.provider.id,
            "file": base64.b64encode(b"Partner: Created From OCR"),
            "filename": "create.txt",
            "mimetype": "text/plain",
        })
        document._process_ocr()
        document.action_mark_reviewed()
        document.action_create_target_record()
        self.assertEqual(document.related_model, "res.partner")
        self.assertTrue(document.related_res_id)

    def test_multilingual_vendor_bill_heuristics(self):
        raw_text = (
            "RECHNUNG LIEFERANT Wunschgutschein GmbH Rosental 6 RECHNUNG: 80331 Miinchen "
            "DE2334590 USt-IdNr: DE329263839 AUSSTELLUNGSDATUM: 10.05.2026 KUNDE "
            "Dach Schutzbekleidung GmbH & Co. KG RotackerstraRe 21 76437 Rastatt "
            "Artikel Beschreibung Menge Einzelpreis MwSt. Gesamt Happy Birthday - "
            "Wunderkerzen PDF 50 € - SKU: 11003511050 1 50,00 0% 50,.00€ GESAMT: 50,00 € "
            "AUSSTELLUNGSDATUM: 10.05.2026 BEZAHLT: 50,00 € ZAHLUNGSMETHODE PayPal "
            "BESTELLNUMMER #DE2334590 Wunschgutschein GmbH | Telefon: +49 (0)211- 781758 0 "
            "| E-Mail: impressum@wunschgutschein.com"
        )
        schema = {
            "fields": [
                "vendor_name",
                "vendor_vat",
                "vendor_email",
                "vendor_phone",
                "bill_date",
                "currency",
                "total_amount",
                "payment_reference",
            ],
            "collections": ["line_items"],
        }

        payload = self.env["ob.ocr.extraction.service"].extract_structured_json(
            raw_text,
            "vendor_bill",
            schema,
        )

        self.assertEqual(payload.get("vendor_name"), "Wunschgutschein GmbH")
        self.assertEqual(payload.get("vendor_email"), "impressum@wunschgutschein.com")
        self.assertEqual(payload.get("bill_date"), "10.05.2026")
        self.assertEqual(payload.get("currency"), "EUR")
        self.assertEqual(payload.get("total_amount"), "50,00")
        self.assertEqual(payload.get("payment_reference"), "DE2334590")
        self.assertTrue(payload.get("line_items"))
        self.assertEqual(payload["line_items"][0].get("product_code"), "11003511050")

    def test_flattened_vendor_bill_values_are_sanitized(self):
        raw_text = (
            "INVOICE Vendor: Atlas Supplies Ltd Invoice Number: INV-2026-1100 "
            "Invoice Date: 2026-05-10 Payment Reference: PO-5100 Code Description UOM Qty Unit Price VAT "
            "A-11 Blue Widget PCS 2.00 42.50 19% B-21 Steel Fastener Pack PCS 3.00 51.75 19% "
            "Net Total $ 240.25 Tax $ 45.65 Amount Due $ 285.90"
        )
        schema = {
            "fields": [
                "vendor_name",
                "bill_number",
                "bill_date",
                "payment_reference",
                "untaxed_amount",
                "tax_amount",
                "total_amount",
            ],
            "collections": ["line_items"],
        }
        document_type = self.env.ref("ob_ocr_vendor_bill.document_type_vendor_bill")
        mapping = self.env.ref("ob_ocr_vendor_bill.ocr_mapping_vendor_bill")
        document = self.env["ob.ocr.document"].create({
            "document_type_id": document_type.id,
            "mapping_id": mapping.id,
            "raw_text": raw_text,
            "file": base64.b64encode(b"flattened"),
            "filename": "flattened.txt",
            "mimetype": "text/plain",
        })

        payload = self.env["ob.ocr.extraction.service"].extract_structured_json(
            raw_text,
            "vendor_bill",
            schema,
            mapping=mapping,
            document=document,
        )

        self.assertEqual(payload.get("vendor_name"), "Atlas Supplies Ltd")
        self.assertEqual(payload.get("payment_reference"), "PO-5100")
        self.assertEqual(payload.get("untaxed_amount"), "240.25")
        self.assertEqual(payload.get("tax_amount"), "45.65")
        self.assertEqual(payload.get("total_amount"), "285.90")

    def test_reference_pattern_ignores_no_inside_vendor_name(self):
        raw_text = (
            "INVOICE\n"
            "Lieferant: Nordhandel GmbH\n"
            "Rechnung-Nr.: RG-2026-2100\n"
            "Rechnungsdatum: 11.05.2026\n"
            "Nettobetrag EUR 241,50\n"
            "MwSt. EUR 45,89\n"
            "Gesamtbetrag EUR 287,39"
        )
        schema = {
            "fields": ["vendor_name", "bill_number", "bill_date", "untaxed_amount", "tax_amount", "total_amount"],
            "collections": ["line_items"],
        }

        payload = self.env["ob.ocr.extraction.service"].extract_structured_json(
            raw_text,
            "vendor_bill",
            schema,
        )

        self.assertEqual(payload.get("vendor_name"), "Nordhandel GmbH")
        self.assertEqual(payload.get("bill_number"), "RG-2026-2100")

    def test_leading_company_name_beats_noisy_layout_company_name(self):
        raw_text = (
            "Lander, Kohlmann & Partner\n"
            "Mandant 53150\n"
            "Telefon: 07243 / 7645-417\n"
            "12.05.2026\n"
            "Rechnung-Nr. 2026/3200"
        )
        schema = {
            "fields": ["vendor_name", "bill_number", "bill_date"],
            "collections": ["line_items"],
        }
        document = self.env["ob.ocr.document"].create({
            "document_type_id": self.env.ref("ob_ocr_vendor_bill.document_type_vendor_bill").id,
            "file": base64.b64encode(b"service"),
            "filename": "service_invoice.txt",
            "mimetype": "text/plain",
            "raw_text": raw_text,
            "ocr_layout_json": {
                "source": "tesseract",
                "pages": [{
                    "page_num": 1,
                    "lines": [
                        {"text": "Lander, KohImann & Partner", "top": 40, "left": 40, "words": [{"text": "Lander,", "left": 40}, {"text": "KohImann", "left": 120}, {"text": "&", "left": 220}, {"text": "Partner", "left": 240}]},
                    ],
                }],
            },
        })

        payload = self.env["ob.ocr.extraction.service"].extract_structured_json(
            raw_text,
            "vendor_bill",
            schema,
            document=document,
        )

        self.assertEqual(payload.get("vendor_name"), "Lander, Kohlmann & Partner")

    def test_line_amount_is_recomputed_when_ocr_amount_is_implausible(self):
        service = self.env["ob.ocr.extraction.service"]
        amount = service._normalize_line_amount(1.0, 89.0, 198.0, taxes=False)
        self.assertEqual(amount, 89.0)

    def test_tesseract_language_falls_back_to_installed_language(self):
        service = self.env["ob.ocr.provider.service"]
        self.env["ir.config_parameter"].sudo().set_param("ob_ocr_base.default_language", "eng")

        with patch.object(OCRProviderService, "_get_available_tesseract_languages", return_value={"eng", "osd"}):
            self.assertEqual(service._resolve_tesseract_language("rus"), "eng")
            self.assertEqual(service._resolve_tesseract_language("en+rus"), "eng")
            self.assertEqual(service._get_default_tesseract_language(), "eng")

    def test_pdf_text_sources_are_merged_without_losing_native_text(self):
        service = self.env["ob.ocr.provider.service"]
        merged = service._merge_text_sources(
            "COMMERCIAL INVOICE N°2188A DATA\\DATE 11/05/26",
            "COMMERCIAL INVOICE N° DATA\\DATE 2188A 42.442",
        )

        self.assertIn("11/05/26", merged)
        self.assertTrue(merged.startswith("COMMERCIAL INVOICE N°2188A"))

    def test_layout_table_extraction_for_invoice_lines(self):
        document = self.env["ob.ocr.document"].create({
            "document_type_id": self.document_type.id,
            "file": base64.b64encode(b"layout"),
            "filename": "layout.txt",
            "mimetype": "text/plain",
            "ocr_layout_json": {
                "source": "tesseract",
                "pages": [{
                    "page_num": 1,
                    "lines": [
                        {
                            "text": "CoDIcE \\ CODE DESCRIZIONE \\ DESCRIPTION um | are\\ary | erezzo\\unrr price | «oisc]importo amount] VAT",
                            "top": 641,
                            "left": 83,
                            "words": [
                                {"text": "CoDIcE", "left": 83},
                                {"text": "CODE", "left": 139},
                                {"text": "DESCRIZIONE", "left": 327},
                                {"text": "DESCRIPTION", "left": 419},
                                {"text": "um", "left": 637},
                                {"text": "price", "left": 893},
                                {"text": "«oisc]importo", "left": 944},
                                {"text": "amount]", "left": 1055},
                                {"text": "VAT", "left": 1130},
                            ],
                        },
                        {
                            "text": "57 BLK NB IBLACK WAX INK - 1 KG MARKEM 5003 PZ 6,00 EUR 98,00 EUR 588,00} 0",
                            "top": 691,
                            "left": 57,
                            "words": [
                                {"text": "57", "left": 57},
                                {"text": "BLK", "left": 77},
                                {"text": "NB", "left": 107},
                                {"text": "IBLACK", "left": 207},
                                {"text": "WAX", "left": 256},
                                {"text": "INK", "left": 293},
                                {"text": "-", "left": 319},
                                {"text": "1", "left": 329},
                                {"text": "KG", "left": 339},
                                {"text": "MARKEM", "left": 367},
                                {"text": "5003", "left": 431},
                                {"text": "PZ", "left": 634},
                                {"text": "6,00", "left": 759},
                                {"text": "EUR", "left": 820},
                                {"text": "98,00", "left": 895},
                                {"text": "EUR", "left": 996},
                                {"text": "588,00}", "left": 1067},
                                {"text": "0", "left": 1129},
                            ],
                        },
                        {
                            "text": "SHIP- UE ISHIPPING COST - N.S. ART. 7 TER 1,00 EUR 22,00 EUR 22,00} 0",
                            "top": 727,
                            "left": 57,
                            "words": [
                                {"text": "SHIP-", "left": 57},
                                {"text": "UE", "left": 98},
                                {"text": "ISHIPPING", "left": 207},
                                {"text": "COST", "left": 277},
                                {"text": "-", "left": 319},
                                {"text": "N.S.", "left": 328},
                                {"text": "ART.", "left": 361},
                                {"text": "7", "left": 396},
                                {"text": "TER", "left": 407},
                                {"text": "1,00", "left": 760},
                                {"text": "EUR", "left": 820},
                                {"text": "22,00", "left": 895},
                                {"text": "EUR", "left": 996},
                                {"text": "22,00}", "left": 1074},
                                {"text": "0", "left": 1129},
                            ],
                        },
                        {
                            "text": "COLLI / PACKAGE TOTALE MERCE / TOTAL AMOUNT EUR 610,00",
                            "top": 1291,
                            "left": 70,
                            "words": [
                                {"text": "COLLI", "left": 70},
                                {"text": "PACKAGE", "left": 155},
                                {"text": "TOTAL", "left": 900},
                            ],
                        },
                    ],
                }],
            },
        })

        line_items = self.env["ob.ocr.extraction.service"]._extract_layout_line_items(document, "vendor_bill")

        self.assertEqual(len(line_items), 2)
        self.assertEqual(line_items[0].get("product_code"), "57 BLK NB")
        self.assertEqual(line_items[0].get("quantity"), 6.0)
        self.assertEqual(line_items[0].get("unit_price"), 98.0)
        self.assertEqual(line_items[0].get("amount"), 588.0)
        self.assertEqual(line_items[1].get("product_code"), "SHIP- UE")

    def test_layout_table_extraction_computes_amounts_and_skips_summary_rows(self):
        document = self.env["ob.ocr.document"].create({
            "document_type_id": self.document_type.id,
            "file": base64.b64encode(b"layout"),
            "filename": "compact_layout.txt",
            "mimetype": "text/plain",
            "ocr_layout_json": {
                "source": "tesseract",
                "pages": [{
                    "page_num": 1,
                    "lines": [
                        {
                            "text": "Code Description UOoM Qty Unit Price VAT",
                            "words": [
                                {"text": "Code", "left": 80},
                                {"text": "Description", "left": 231},
                                {"text": "UOoM", "left": 691},
                                {"text": "Qty", "left": 791},
                                {"text": "Unit", "left": 912},
                                {"text": "Price", "left": 958},
                                {"text": "VAT", "left": 1070},
                            ],
                        },
                        {
                            "text": "CS-61 Compact Sensor PCS 1.00 89.00 19%",
                            "words": [
                                {"text": "CS-61", "left": 80},
                                {"text": "Compact", "left": 231},
                                {"text": "Sensor", "left": 304},
                                {"text": "PCS", "left": 692},
                                {"text": "1.00", "left": 791},
                                {"text": "89.00", "left": 910},
                                {"text": "19%", "left": 1073},
                            ],
                        },
                        {
                            "text": "SB-71 Signal Board PCS 2.00 54.50 19%",
                            "words": [
                                {"text": "SB-71", "left": 80},
                                {"text": "Signal", "left": 231},
                                {"text": "Board", "left": 293},
                                {"text": "PCS", "left": 692},
                                {"text": "2.00", "left": 791},
                                {"text": "54.50", "left": 911},
                                {"text": "19%", "left": 1073},
                            ],
                        },
                        {
                            "text": "Subtotal $ 198.00",
                            "words": [
                                {"text": "Subtotal", "left": 771},
                                {"text": "$", "left": 1010},
                                {"text": "198.00", "left": 1028},
                            ],
                        },
                        {
                            "text": "Amount Due $ 227.70",
                            "words": [
                                {"text": "Amount", "left": 771},
                                {"text": "Due", "left": 850},
                                {"text": "$", "left": 1010},
                                {"text": "227.70", "left": 1028},
                            ],
                        },
                    ],
                }],
            },
        })

        line_items = self.env["ob.ocr.extraction.service"]._extract_layout_line_items(document, "vendor_bill")

        self.assertEqual(len(line_items), 2)
        self.assertEqual(line_items[0].get("product_code"), "CS-61")
        self.assertEqual(line_items[0].get("product_name"), "Compact Sensor")
        self.assertEqual(line_items[0].get("quantity"), 1.0)
        self.assertEqual(line_items[0].get("unit_price"), 89.0)
        self.assertEqual(line_items[0].get("amount"), 89.0)
        self.assertEqual(line_items[1].get("amount"), 109.0)

    def test_layout_narrative_service_invoice_extraction(self):
        raw_text = (
            "Lander, Kohlmann & Partner 4& 53150 -R 2026/2218 Frau Ming Gutsche Falkenweg 6 "
            "76275 Ettlingen 11.05.2026 Claudia Kugele Telefon: 07243 / 7645-417 53150 / ML "
            "ku@LKP.de Rechnung-Nr. 2026/2218 Far die in Ihrem Auftrag ausgefiihrten Leistungen "
            "erlauben wir uns zu berechnen: Gegenstandswert/ Gebiihrentext nach StBVV Einheiten Tab "
            "Steuerberater Rechtsanwälte Fachanwälte Diplom Kaufmann Heinz R. Lander bis 03/2021 "
            "Wirtschaftsprifer, Stouerberater Andreas Lander Rechtsanwalt, Steuerberater Joachim "
            "Kohimann Rechtsanwalt Markus Lander Rechtsanwalt, Steuerberater Diplom Betriebswirtin "
            "(BA) Manuela Lander ‘Stouerberaterin Thomas Schlesinger Rechtsanwalt Nicole Herzog "
            "‘Stouerberaterin Diplom Finanzwirtin (FH) Iris Beham ‘Stouerberaterin Bachelor of Arts "
            "Yvette Mayer ‘Stouerberaterin 76275 Ettlingen, Ottostrafe 1 Satz/ Euro Euro Auftrag: "
            "Einkommensteuer 2024 - Nr. 001947 (USt-Leistungsdatum bis 04.2026) Einkommensteuererklarung "
            "ohne Ermittlung der einzelnen Einkinfte (Steuerpflichtiger) § 24 Abs. 1 Nr. 1 StBVV "
            "1.148.573,00 EUR A Ermittlung des Uberschusses der Einnahmen uber die Werbungskosten bei "
            "Einkiinften aus Kapitalvermégen (Steuerpflichtiger) § 27 Abs. 1 StBVV 1.149.573,00 EUR A "
            "Summe Gebiihren (USt 19,00%) Summe Auslagen gem. §16 StBVV (USt 19,00%) USt 19,00% zu "
            "zahlender Betrag 2,50/10 1.260,75 5,00/20 1.260,75 2.521,50 40,00 2.561,50 486,69 3.048,19"
        )
        schema = {
            "fields": [
                "vendor_name",
                "bill_number",
                "bill_date",
                "tax_amount",
                "total_amount",
            ],
            "collections": ["line_items"],
        }
        document = self.env["ob.ocr.document"].create({
            "document_type_id": self.document_type.id,
            "file": base64.b64encode(b"layout"),
            "filename": "service_invoice.txt",
            "mimetype": "text/plain",
            "raw_text": raw_text,
            "ocr_layout_json": {
                "source": "tesseract",
                "pages": [{
                    "page_num": 1,
                    "lines": [
                        {"text": "Lander, Kohlmann & Partner 4&"},
                        {"text": "53150 -R 2026/2218"},
                        {"text": "Frau"},
                        {"text": "Ming Gutsche"},
                        {"text": "11.05.2026 Claudia Kugele Telefon: 07243 / 7645-417"},
                        {"text": "53150 / ML ku@LKP.de"},
                        {"text": "Rechnung-Nr. 2026/2218"},
                        {"text": "Far die in Ihrem Auftrag ausgefiihrten Leistungen erlauben wir uns zu berechnen:"},
                        {"text": "Gegenstandswert/"},
                        {"text": "Satz/"},
                        {"text": "Gebiihrentext nach StBVV Einheiten Tab"},
                        {"text": "Euro Euro"},
                        {"text": "Auftrag: Einkommensteuer 2024 - Nr. 001947 (USt-Leistungsdatum bis 04.2026)"},
                        {"text": "Einkommensteuererklarung ohne Ermittlung der"},
                        {"text": "einzelnen Einkinfte (Steuerpflichtiger)"},
                        {"text": "§ 24 Abs. 1 Nr. 1 StBVV 1.148.573,00 EUR A"},
                        {"text": "2,50/10 1.260,75"},
                        {"text": "Ermittlung des Uberschusses der Einnahmen uber die"},
                        {"text": "Werbungskosten bei Einkiinften aus Kapitalvermégen"},
                        {"text": "(Steuerpflichtiger)"},
                        {"text": "§ 27 Abs. 1 StBVV 1.149.573,00 EUR A"},
                        {"text": "5,00/20 1.260,75"},
                        {"text": "Summe Gebiihren (USt 19,00%)"},
                        {"text": "2.521,50"},
                        {"text": "Summe Auslagen gem. §16 StBVV (USt 19,00%)"},
                        {"text": "40,00"},
                        {"text": "2.561,50"},
                        {"text": "USt 19,00%"},
                        {"text": "486,69"},
                        {"text": "zu zahlender Betrag"},
                        {"text": "3.048,19"},
                    ],
                }],
            },
        })

        payload = self.env["ob.ocr.extraction.service"].extract_structured_json(
            raw_text,
            "vendor_bill",
            schema,
            document=document,
        )

        self.assertEqual(payload.get("bill_number"), "2026/2218")
        self.assertEqual(payload.get("bill_date"), "11.05.2026")
        self.assertEqual(payload.get("tax_amount"), "486,69")
        self.assertEqual(payload.get("total_amount"), "3.048,19")
        self.assertEqual(len(payload.get("line_items") or []), 2)
        self.assertIn("Einkommensteuer", payload["line_items"][0].get("name"))
        self.assertEqual(payload["line_items"][0].get("unit_price"), 1260.75)
        self.assertEqual(payload["line_items"][1].get("amount"), 1260.75)

    def test_native_pdf_text_layout_extracts_service_invoice_rows(self):
        raw_text = (
            "Lander, Kohlmann & Partner \n"
            "Rechtsanwälte\n"
            "Fachanwälte\n"
            "11.05.2026 Claudia Kugele Telefon : 07243 / 7645 -417\n"
            "53150 / ML ku@LKP.de\n"
            "Rechnung -Nr. 2026/2218\n"
            "Für die in Ihrem Auftrag ausgeführten Leistungen erlauben wir uns zu berechnen:\n"
            "Gebührentext nach StBVV Gegenstandswert/\n"
            "Einheiten\n"
            "Tab Satz/\n"
            "Euro\n"
            "Euro\n"
            "Auftrag : Einkommensteuer 2024 - Nr. 001947 (USt-Leistungsdatum bis 04.2026)\n"
            "Einkommensteuererklärung ohne Ermittlung der\n"
            "einzelnen Einkünfte (Steuerpflichtiger)\n"
            "§ 24 Abs. 1 Nr. 1 StBVV 1.148.573,00 EUR A 2,50/10 1.260,75\n"
            "Ermittlung des Überschusses der Einnahmen über die\n"
            "Werbungskosten bei Einkünften aus Kapitalvermögen\n"
            "(Steuerpflichtiger)\n"
            "§ 27 Abs. 1 StBVV 1.149.573,00 EUR A 5,00/20 1.260,75\n"
            "Summe Gebühren (USt 19,00%) 2.521,50\n"
            "Summe Auslagen gem. §16 StBVV (USt 19,00%) 40,00\n"
            "2.561,50\n"
            "USt 19,00% 486,69\n"
            "zu zahlender Betrag 3.048,19\n"
        )
        schema = {
            "fields": [
                "vendor_name",
                "bill_number",
                "bill_date",
                "untaxed_amount",
                "tax_amount",
                "total_amount",
            ],
            "collections": ["line_items"],
        }
        document = self.env["ob.ocr.document"].create({
            "document_type_id": self.env.ref("ob_ocr_vendor_bill.document_type_vendor_bill").id,
            "file": base64.b64encode(b"native-layout"),
            "filename": "native_layout_invoice.txt",
            "mimetype": "text/plain",
            "raw_text": raw_text,
            "ocr_layout_json": {
                "source": "native_pdf_text",
                "pages": [{
                    "page_num": 1,
                    "lines": [
                        {"text": "Lander, Kohlmann & Partner"},
                        {"text": "Rechtsanwälte"},
                        {"text": "Fachanwälte"},
                        {"text": "11.05.2026 Claudia Kugele Telefon : 07243 / 7645 -417"},
                        {"text": "53150 / ML ku@LKP.de"},
                        {"text": "Rechnung -Nr. 2026/2218"},
                        {"text": "Für die in Ihrem Auftrag ausgeführten Leistungen erlauben wir uns zu berechnen:"},
                        {"text": "Gebührentext nach StBVV Gegenstandswert/"},
                        {"text": "Einheiten"},
                        {"text": "Tab Satz/"},
                        {"text": "Euro"},
                        {"text": "Euro"},
                        {"text": "Auftrag : Einkommensteuer 2024 - Nr. 001947 (USt-Leistungsdatum bis 04.2026)"},
                        {"text": "Einkommensteuererklärung ohne Ermittlung der"},
                        {"text": "einzelnen Einkünfte (Steuerpflichtiger)"},
                        {"text": "§ 24 Abs. 1 Nr. 1 StBVV 1.148.573,00 EUR A 2,50/10 1.260,75"},
                        {"text": "Ermittlung des Überschusses der Einnahmen über die"},
                        {"text": "Werbungskosten bei Einkünften aus Kapitalvermögen"},
                        {"text": "(Steuerpflichtiger)"},
                        {"text": "§ 27 Abs. 1 StBVV 1.149.573,00 EUR A 5,00/20 1.260,75"},
                        {"text": "Summe Gebühren (USt 19,00%) 2.521,50"},
                        {"text": "Summe Auslagen gem. §16 StBVV (USt 19,00%) 40,00"},
                        {"text": "2.561,50"},
                        {"text": "USt 19,00% 486,69"},
                        {"text": "zu zahlender Betrag 3.048,19"},
                    ],
                }],
            },
        })

        payload = self.env["ob.ocr.extraction.service"].extract_structured_json(
            raw_text,
            "vendor_bill",
            schema,
            document=document,
        )

        self.assertEqual(payload.get("vendor_name"), "Lander, Kohlmann & Partner")
        self.assertEqual(payload.get("bill_number"), "2026/2218")
        self.assertEqual(payload.get("bill_date"), "11.05.2026")
        self.assertEqual(payload.get("tax_amount"), "486,69")
        self.assertEqual(payload.get("total_amount"), "3.048,19")
        self.assertEqual(len(payload.get("line_items") or []), 2)
        self.assertIn("Einkommensteuer", payload["line_items"][0].get("name"))

    def test_native_pdf_text_layout_extracts_stacked_amount_rows(self):
        raw_text = (
            "BMW Bank GmbH\n"
            "17.06.2024\n"
            "Leasingrate:\n"
            "Bezeichnung\n"
            "Finanzrate\n"
            "Sonstiges/ Zubehör\n"
            "Wartung und Reparatur\n"
            "Reifen\n"
            "Leasingrate\n"
            "19,00% USt von\n"
            "Gesamtsumme monatlichnetto\n"
            "Betrag EUR\n"
            "851,97\n"
            "33,39\n"
            "24,06\n"
            "67,80\n"
            "977,22\n"
            "185,67\n"
            "1.162,89\n"
        )
        schema = {
            "fields": ["vendor_name", "bill_date", "currency"],
            "collections": ["line_items"],
        }
        document = self.env["ob.ocr.document"].create({
            "document_type_id": self.env.ref("ob_ocr_vendor_bill.document_type_vendor_bill").id,
            "file": base64.b64encode(b"stacked-layout"),
            "filename": "stacked_layout_invoice.txt",
            "mimetype": "text/plain",
            "raw_text": raw_text,
            "ocr_layout_json": {
                "source": "native_pdf_text",
                "pages": [{
                    "page_num": 1,
                    "lines": [
                        {"text": "BMW Bank GmbH"},
                        {"text": "17.06.2024"},
                        {"text": "Leasingrate:"},
                        {"text": "Bezeichnung"},
                        {"text": "Finanzrate"},
                        {"text": "Sonstiges/ Zubehör"},
                        {"text": "Wartung und Reparatur"},
                        {"text": "Reifen"},
                        {"text": "Leasingrate"},
                        {"text": "19,00% USt von"},
                        {"text": "Gesamtsumme monatlichnetto"},
                        {"text": "Betrag EUR"},
                        {"text": "851,97"},
                        {"text": "33,39"},
                        {"text": "24,06"},
                        {"text": "67,80"},
                        {"text": "977,22"},
                        {"text": "185,67"},
                        {"text": "1.162,89"},
                    ],
                }],
            },
        })

        payload = self.env["ob.ocr.extraction.service"].extract_structured_json(
            raw_text,
            "vendor_bill",
            schema,
            document=document,
        )

        self.assertEqual(len(payload.get("line_items") or []), 4)
        self.assertEqual(payload["line_items"][0].get("name"), "Finanzrate")
        self.assertEqual(payload["line_items"][0].get("unit_price"), 851.97)
        self.assertEqual(payload["line_items"][3].get("name"), "Reifen")
        self.assertEqual(payload["line_items"][3].get("amount"), 67.8)

    def test_commercial_invoice_layout_extraction(self):
        raw_text = (
            "Fam Srl (Fam Favata Advanced Marking Srl) VAT NUMBER: IT02784700961 "
            "SPETTABILE To DACH SCHUTZBEKLEIDUNG GmbH & Co. KG COMMERCIAL INVOICE "
            "FATTURA ACCOMPAGNATORIA N° 2188A DATA\\DATE 11/05/26 "
            "57 BLK NB BLACK WAX INK - 1 KG MARKEM 5003 PZ 6,00 EUR 98,00 EUR 588,00 0 "
            "SHIP- UE SHIPPING COST - N.S. ART 7 TER 1,00 EUR 22,00 EUR 22,00 0 "
            "TOTALE MERCE TOTAL AMOUNT EUR 610,00 TOTALE NETTO NET AMOUNT EUR 610,00 "
            "TOTALE FATTURA TOTAL INVOICE 0,00 EUR 610,00"
        )
        schema = {
            "fields": [
                "vendor_name",
                "vendor_vat",
                "bill_number",
                "bill_date",
                "untaxed_amount",
                "tax_amount",
                "total_amount",
            ],
            "collections": ["line_items"],
        }
        document = self.env["ob.ocr.document"].create({
            "document_type_id": self.env.ref("ob_ocr_vendor_bill.document_type_vendor_bill").id,
            "file": base64.b64encode(b"commercial"),
            "filename": "commercial_invoice.txt",
            "mimetype": "text/plain",
            "raw_text": raw_text,
            "ocr_layout_json": {
                "source": "tesseract",
                "pages": [{
                    "page_num": 1,
                    "lines": [
                        {"text": "Fam Srl", "top": 68, "left": 76, "words": [{"text": "Fam", "left": 76, "width": 81}, {"text": "Srl", "left": 173, "width": 52}]},
                        {"text": "(Fam Favata Advanced Marking Srl)", "top": 124, "left": 75, "words": [{"text": "(Fam", "left": 75, "width": 56}, {"text": "Favata", "left": 141, "width": 75}, {"text": "Advanced", "left": 224, "width": 110}, {"text": "Marking", "left": 345, "width": 86}, {"text": "Srl)", "left": 440, "width": 38}]},
                        {"text": "VAT NUMBER: IT02784700961", "top": 257, "left": 76, "words": [{"text": "VAT", "left": 76, "width": 43}, {"text": "NUMBER:", "left": 127, "width": 100}, {"text": "IT02784700961", "left": 237, "width": 151}]},
                        {"text": "SPETTABILE \\ To", "top": 408, "left": 939, "words": [{"text": "SPETTABILE", "left": 939, "width": 135}, {"text": "To", "left": 1093, "width": 26}]},
                        {"text": "COMMERCIAL INVOICE \\ FATTURA ACCOMPAGNATORIA", "top": 653, "left": 79, "words": [{"text": "COMMERCIAL", "left": 79, "width": 209}, {"text": "INVOICE", "left": 300, "width": 124}, {"text": "FATTURA", "left": 453, "width": 142}, {"text": "ACCOMPAGNATORIA", "left": 602, "width": 321}]},
                        {"text": "N° 2188A DATA\\DATE 11/05/26 42.442 42.442", "top": 734, "left": 108, "words": [{"text": "N°", "left": 108, "width": 13}, {"text": "2188A", "left": 149, "width": 73}, {"text": "DATA\\DATE", "left": 270, "width": 108}, {"text": "11/05/26", "left": 401, "width": 96}, {"text": "42.442", "left": 560, "width": 74}]},
                        {"text": "CODICE \\ CODE DESCRIZIONE \\ DESCRIPTION uM QTA'\\ QTY PREZZO\\ UNIT PRICE IMPORTO / AMOUNT V.A.T.", "top": 898, "left": 116, "words": [{"text": "CODICE", "left": 116, "width": 64}, {"text": "CODE", "left": 195, "width": 47}, {"text": "DESCRIZIONE", "left": 457, "width": 113}, {"text": "DESCRIPTION", "left": 586, "width": 113}, {"text": "uM", "left": 892, "width": 24}, {"text": "QTY", "left": 1033, "width": 34}, {"text": "PREZZO\\", "left": 1123, "width": 77}, {"text": "UNIT", "left": 1206, "width": 38}, {"text": "PRICE", "left": 1250, "width": 49}, {"text": "IMPORTO", "left": 1390, "width": 76}, {"text": "AMOUNT", "left": 1481, "width": 72}, {"text": "V.A.T.", "left": 1565, "width": 46}]},
                        {"text": "57 BLK NB BLACK WAX INK - 1 KG MARKEM 5003 PZ 6,00 EUR 98,00 EUR 588,00 0", "top": 968, "left": 80, "words": [{"text": "57", "left": 80, "width": 20}, {"text": "BLK", "left": 108, "width": 35}, {"text": "NB", "left": 150, "width": 25}, {"text": "BLACK", "left": 290, "width": 63}, {"text": "WAX", "left": 359, "width": 44}, {"text": "INK", "left": 410, "width": 30}, {"text": "1", "left": 464, "width": 8}, {"text": "KG", "left": 475, "width": 26}, {"text": "MARKEM", "left": 514, "width": 83}, {"text": "5003", "left": 604, "width": 41}, {"text": "PZ", "left": 887, "width": 24}, {"text": "6,00", "left": 1062, "width": 36}, {"text": "EUR", "left": 1148, "width": 39}, {"text": "98,00", "left": 1254, "width": 46}, {"text": "EUR", "left": 1394, "width": 39}, {"text": "588,00", "left": 1493, "width": 57}, {"text": "0", "left": 1581, "width": 9}]},
                        {"text": "SHIP- UE SHIPPING COST - N.S. ART. 7 TER 1,00 EUR 22,00 EUR 22,00 0", "top": 1028, "left": 80, "words": [{"text": "SHIP-", "left": 80, "width": 58}, {"text": "UE", "left": 148, "width": 26}, {"text": "SHIPPING", "left": 290, "width": 92}, {"text": "COST", "left": 391, "width": 50}, {"text": "1,00", "left": 1061, "width": 36}, {"text": "EUR", "left": 1148, "width": 39}, {"text": "22,00", "left": 1254, "width": 46}, {"text": "EUR", "left": 1394, "width": 39}, {"text": "22,00", "left": 1493, "width": 57}, {"text": "0", "left": 1581, "width": 9}]},
                        {"text": "TOTALE MERCE / TOTAL AMOUNT EUR 610,00", "top": 1809, "left": 1051, "words": [{"text": "TOTALE", "left": 1051, "width": 64}, {"text": "MERCE", "left": 1122, "width": 58}, {"text": "TOTAL", "left": 1195, "width": 54}, {"text": "AMOUNT", "left": 1254, "width": 72}, {"text": "EUR", "left": 1379, "width": 40}, {"text": "610,00", "left": 1529, "width": 67}]},
                        {"text": "TOTALE NETTO / NET AMOUNT EUR 610,00", "top": 1926, "left": 1051, "words": [{"text": "TOTALE", "left": 1051, "width": 64}, {"text": "NETTO", "left": 1122, "width": 55}, {"text": "NET", "left": 1193, "width": 32}, {"text": "AMOUNT", "left": 1230, "width": 73}, {"text": "EUR", "left": 1379, "width": 40}, {"text": "610,00", "left": 1529, "width": 67}]},
                        {"text": "V.A.T. EXEMPTION TOTALE FATTURA / TOTAL INVOICE", "top": 2002, "left": 650, "words": [{"text": "V.A.T.", "left": 650, "width": 49}, {"text": "EXEMPTION", "left": 708, "width": 111}, {"text": "TOTALE", "left": 1207, "width": 87}, {"text": "FATTURA/", "left": 1303, "width": 115}, {"text": "TOTAL", "left": 1424, "width": 73}, {"text": "INVOICE", "left": 1505, "width": 90}]},
                        {"text": "0,00 EUR 610,00", "top": 2092, "left": 962, "words": [{"text": "0,00", "left": 962, "width": 48}, {"text": "EUR", "left": 1396, "width": 51}, {"text": "610,00", "left": 1521, "width": 75}]},
                    ],
                }],
            },
        })

        payload = self.env["ob.ocr.extraction.service"].extract_structured_json(
            raw_text,
            "vendor_bill",
            schema,
            document=document,
        )

        self.assertEqual(payload.get("vendor_name"), "Fam Favata Advanced Marking Srl")
        self.assertEqual(payload.get("vendor_vat"), "IT02784700961")
        self.assertEqual(payload.get("bill_number"), "2188A")
        self.assertEqual(payload.get("bill_date"), "11/05/26")
        self.assertEqual(payload.get("untaxed_amount"), "610,00")
        self.assertEqual(payload.get("tax_amount"), "0,00")
        self.assertEqual(payload.get("total_amount"), "610,00")
        self.assertEqual(len(payload.get("line_items") or []), 2)
        self.assertEqual(payload["line_items"][0].get("product_code"), "57 BLK NB")
        self.assertEqual(payload["line_items"][1].get("amount"), 22.0)

    def test_vendor_bill_prefers_native_pdf_reference_over_noisy_layout_header(self):
        raw_text = (
            "Fam Srl\n"
            "(Fam Favata Advanced Marking Srl)\n"
            "VAT NUMBER: IT02784700961\n"
            "COMMERCIAL INVOICE \\ FATTURA ACCOMPAGNATORIA\n"
            "N°2188A DATA\\DATE 11/05/26P.IVA / VAT No.\n"
            "4.2.442COD. CLIENTE / CUSTOMER CODE\n"
            "4.2.442PAG.1 di 1\n"
            "TOTALE NETTO / NET AMOUNT EUR 610,00\n"
            "TOTALE FATTURA / TOTAL INVOICE UE 0,00 EUR 610,00"
        )
        schema = {
            "fields": [
                "vendor_name",
                "vendor_vat",
                "bill_number",
                "bill_date",
                "untaxed_amount",
                "tax_amount",
                "total_amount",
            ],
            "collections": ["line_items"],
        }
        document = self.env["ob.ocr.document"].create({
            "document_type_id": self.env.ref("ob_ocr_vendor_bill.document_type_vendor_bill").id,
            "file": base64.b64encode(b"native-pdf"),
            "filename": "native_pdf_invoice.pdf",
            "mimetype": "application/pdf",
            "raw_text": raw_text,
            "ocr_layout_json": {
                "source": "tesseract",
                "pages": [{
                    "page_num": 1,
                    "lines": [
                        {"text": "VAT NUMBER: IT02784700961", "top": 183, "left": 54, "words": [{"text": "VAT", "left": 54}, {"text": "NUMBER:", "left": 110}, {"text": "IT02784700961", "left": 220}]},
                        {"text": "COMMERCIAL INVOICE \\ FATTURA ACCOMPAGNATORIA", "top": 466, "left": 56, "words": [{"text": "COMMERCIAL", "left": 56}, {"text": "INVOICE", "left": 214}]},
                        {"text": "2188A 11108126 | 45 P.IVA 44p / VAT No. 42.442 COD. CLIENTE / CUSTOMER CODE PAGA dit", "top": 506, "left": 106, "words": [{"text": "2188A", "left": 106}, {"text": "11108126", "left": 286}, {"text": "42.442", "left": 774}]},
                        {"text": "N° DATA\\DATE .", "top": 520, "left": 77, "words": [{"text": "N°", "left": 77}, {"text": "DATA\\DATE", "left": 193}]},
                        {"text": "PORTO\\ DELIVERY TERMS —_INCOTERM: DAP(ddu) pae* TOTALE NETTO/ NET AMOUNT EUR 610,00", "top": 1370, "left": 71, "words": [{"text": "TOTALE", "left": 871}, {"text": "NETTO", "left": 942}, {"text": "610,00", "left": 1280}]},
                        {"text": "IMPONIBILE / AMOUNT % VAI % VAT. |V.A.T. EXEMPTION WVAIVAT. TOTALE FATTURA/ TOTAL INVOICE", "top": 1429, "left": 73, "words": [{"text": "TOTALE", "left": 1020}, {"text": "FATTURA/", "left": 1091}, {"text": "TOTAL", "left": 1202}, {"text": "INVOICE", "left": 1273}]},
                        {"text": "22,00 Ue 0,00 EUR _610,00", "top": 1480, "left": 167, "words": [{"text": "22,00", "left": 167}, {"text": "0,00", "left": 340}, {"text": "EUR", "left": 430}, {"text": "610,00", "left": 520}]},
                    ],
                }],
            },
        })

        payload = self.env["ob.ocr.extraction.service"].extract_structured_json(
            raw_text,
            "vendor_bill",
            schema,
            document=document,
        )

        self.assertEqual(payload.get("bill_number"), "2188A")
        self.assertEqual(payload.get("bill_date"), "11/05/26")
        self.assertEqual(payload.get("vendor_vat"), "IT02784700961")

    def test_commercial_invoice_native_text_parser_handles_dach_invoice(self):
        raw_text = (
            "Fam Srl\n"
            "(Fam Favata Advanced Marking Srl)\n"
            "Operational Headquarters: VIA LEONCAVALLO, 55 - 20832 - DESIO (MB) ITALY\n"
            "Registered Office: Via Briantina,6 - 20831 Seregno (MB) Italy\n"
            "VAT NUMBER: IT02784700961\n"
            "TEL. 0039 0362 302877\n"
            "EMAIL: info@fam-printing.com\n"
            "COMMERCIAL INVOICE \\ FATTURA ACCOMPAGNATORIA\n"
            "N°2188A DATA\\DATE 11/05/26P.IVA / VAT No.\n"
            "4.2.442COD. CLIENTE / CUSTOMER CODE\n"
            "CODICE \\ CODE DESCRIZIONE \\ DESCRIPTION UM QTA' \\ QTY PREZZO \\ UNIT PRICE %DISC IMPORTO / AMOUNT V.A.T.\n"
            "OUR REF N° 1170 CUSTOMER REF N:\n"
            "57 BLK NB BLACK WAX INK - 1 KG MARKEM 5003\n"
            "LOT: 092524F1PZ 6,00 EUR 98,00 EUR 588,00 0\n"
            "SHIP- UE SHIPPING COST - N.S. ART. 7 TER\n"
            "BY DHL1,00 EUR 22,00 EUR 22,00 0\n"
            "EUR COLLI / PACKAGE 1 SPESE TRASPORTO / FREIGHT COST TOTALE MERCE / TOTAL AMOUNT 610,00\n"
            "PORTO \\ DELIVERY TERMS INCOTERM: DAP(ddu)EUR DHL * TOTALE NETTO / NET AMOUNT 610,00\n"
            "% IVA / % V.A.T. IVA / V.A.T. V.A.T. EXEMPTION TOTALE FATTURA / TOTAL INVOICE IMPONIBILE / AMOUNT\n"
            "588,00 41 ART.41 CEE\n"
            "22,00 N.S ART.7TER\n"
            "UE0,00 EUR 610,00\n"
        )
        schema = {
            "fields": [
                "vendor_name",
                "vendor_vat",
                "vendor_email",
                "vendor_phone",
                "bill_number",
                "bill_date",
                "due_date",
                "untaxed_amount",
                "tax_amount",
                "total_amount",
            ],
            "collections": ["line_items"],
        }
        document = self.env["ob.ocr.document"].create({
            "document_type_id": self.env.ref("ob_ocr_vendor_bill.document_type_vendor_bill").id,
            "file": base64.b64encode(b"dach"),
            "filename": "DACH.pdf",
            "mimetype": "application/pdf",
            "raw_text": raw_text,
            "ocr_layout_json": {
                "source": "native_pdf_text",
                "pages": [{
                    "page_num": 1,
                    "lines": [{"text": line, "top": (index + 1) * 18, "left": 40} for index, line in enumerate(raw_text.splitlines()) if line],
                }],
            },
        })

        payload = self.env["ob.ocr.extraction.service"].extract_structured_json(
            raw_text,
            "vendor_bill",
            schema,
            document=document,
        )

        self.assertEqual(payload.get("vendor_name"), "Fam Favata Advanced Marking Srl")
        self.assertEqual(payload.get("vendor_vat"), "IT02784700961")
        self.assertEqual(payload.get("bill_number"), "2188A")
        self.assertEqual(payload.get("bill_date"), "11/05/26")
        self.assertFalse(payload.get("due_date"))
        self.assertEqual(payload.get("untaxed_amount"), "610,00")
        self.assertEqual(payload.get("tax_amount"), "0,00")
        self.assertEqual(payload.get("total_amount"), "610,00")
        self.assertEqual(len(payload.get("line_items") or []), 2)
        self.assertEqual(payload["line_items"][0].get("product_code"), "57 BLK")
        self.assertEqual(payload["line_items"][0].get("quantity"), 6.0)
        self.assertEqual(payload["line_items"][0].get("unit_price"), 98.0)
        self.assertEqual(payload["line_items"][1].get("product_code"), "SHIP- UE")
        self.assertEqual(payload["line_items"][1].get("unit_price"), 22.0)
