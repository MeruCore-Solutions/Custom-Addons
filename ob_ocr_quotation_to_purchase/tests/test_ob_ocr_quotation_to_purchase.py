import base64

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestObOCRQuotationToPurchase(TransactionCase):

    def test_create_purchase_order_from_reviewed_document(self):
        vendor = self.env["res.partner"].create({
            "name": "Vendor OCR Quote",
            "supplier_rank": 1,
        })
        provider = self.env["ob.ocr.provider"].create({
            "name": "Purchase Stub",
            "code": "purchase_stub",
            "provider_key": "stub",
            "service_model": "ob.ocr.provider.service",
            "allowed_mimetypes": "text/plain",
        })
        document = self.env["ob.ocr.document"].create({
            "document_type_id": self.env.ref("ob_ocr_quotation_to_purchase.document_type_supplier_quotation").id,
            "ocr_provider_id": provider.id,
            "file": base64.b64encode(b"supplier quote"),
            "filename": "supplier_quote.txt",
            "mimetype": "text/plain",
            "extracted_json": {
                "vendor_name": vendor.name,
                "quotation_number": "SUP-QUO-001",
                "quotation_date": "2026-05-17",
                "currency": self.env.company.currency_id.name,
            },
        })
        document.action_mark_reviewed()
        document.action_create_target_record()
        order = self.env["purchase.order"].browse(document.related_res_id)
        self.assertEqual(order.partner_id, vendor)
        self.assertEqual(order.partner_ref, "SUP-QUO-001")

    def test_extract_supplier_quotation_from_flattened_ocr_text(self):
        document = self.env["ob.ocr.document"].create({
            "document_type_id": self.env.ref("ob_ocr_quotation_to_purchase.document_type_supplier_quotation").id,
            "file": base64.b64encode(b"supplier quote"),
            "filename": "supplier_quote.txt",
            "mimetype": "text/plain",
            "raw_text": (
                "® Your logo My Company United States Test Customer Quotation # S00001 "
                "Quotation Date Expiration Salesperson 05/17/2026 06/16/2026 Administrator "
                "Description Quantity Unit Price Taxes Amount "
                "Test Product 1.00 Units 120.00 15% $ 120.00 "
                "Untaxed Amount $ 120.00 Tax 15% $ 18.00 Total $ 138.00 Page 1/1"
            ),
        })

        payload = document._extract_structured_data()

        self.assertEqual(payload.get("vendor_name"), "Test Customer")
        self.assertEqual(payload.get("quotation_number"), "S00001")
        self.assertEqual(payload.get("quotation_date"), "05/17/2026")
        self.assertEqual(payload.get("validity_date"), "06/16/2026")
        self.assertEqual(payload.get("currency"), "USD")
        self.assertEqual(len(payload.get("line_items", [])), 1)
        self.assertEqual(payload["line_items"][0]["product_name"], "Test Product")
        self.assertEqual(payload["line_items"][0]["quantity"], 1.0)
        self.assertEqual(payload["line_items"][0]["uom"], "Units")
        self.assertEqual(payload["line_items"][0]["unit_price"], 120.0)
        self.assertEqual(payload["line_items"][0]["taxes"], "15%")
