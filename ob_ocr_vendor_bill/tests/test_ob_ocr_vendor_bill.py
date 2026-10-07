import base64

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestObOCRVendorBill(TransactionCase):

    def test_create_vendor_bill_from_reviewed_document(self):
        vendor = self.env["res.partner"].create({
            "name": "Vendor OCR Test",
            "supplier_rank": 1,
        })
        provider = self.env["ob.ocr.provider"].create({
            "name": "Vendor Stub",
            "code": "vendor_stub",
            "provider_key": "stub",
            "service_model": "ob.ocr.provider.service",
            "allowed_mimetypes": "text/plain",
        })
        document = self.env["ob.ocr.document"].create({
            "document_type_id": self.env.ref("ob_ocr_vendor_bill.document_type_vendor_bill").id,
            "ocr_provider_id": provider.id,
            "file": base64.b64encode(b"Vendor bill OCR"),
            "filename": "vendor_bill.txt",
            "mimetype": "text/plain",
            "extracted_json": {
                "vendor_name": vendor.name,
                "bill_number": "BILL-001",
                "bill_date": "2026-05-17",
                "currency": self.env.company.currency_id.name,
            },
        })
        document.action_mark_reviewed()
        document.action_create_target_record()
        move = self.env["account.move"].browse(document.related_res_id)
        self.assertEqual(move.move_type, "in_invoice")
        self.assertEqual(move.partner_id, vendor)

    def test_manual_partner_override_is_used(self):
        selected_vendor = self.env["res.partner"].create({
            "name": "Chosen Vendor",
            "supplier_rank": 1,
        })
        provider = self.env["ob.ocr.provider"].create({
            "name": "Vendor Stub 2",
            "code": "vendor_stub_2",
            "provider_key": "stub",
            "service_model": "ob.ocr.provider.service",
            "allowed_mimetypes": "text/plain",
        })
        document = self.env["ob.ocr.document"].create({
            "document_type_id": self.env.ref("ob_ocr_vendor_bill.document_type_vendor_bill").id,
            "ocr_provider_id": provider.id,
            "partner_override_id": selected_vendor.id,
            "file": base64.b64encode(b"Vendor bill OCR"),
            "filename": "vendor_bill_manual.txt",
            "mimetype": "text/plain",
            "extracted_json": {
                "vendor_name": "OCR Vendor That Does Not Exist",
                "bill_number": "BILL-002",
                "bill_date": "2026-05-17",
                "currency": self.env.company.currency_id.name,
            },
        })

        document.action_mark_reviewed()
        document.action_create_target_record()

        move = self.env["account.move"].browse(document.related_res_id)
        self.assertEqual(move.partner_id, selected_vendor)
