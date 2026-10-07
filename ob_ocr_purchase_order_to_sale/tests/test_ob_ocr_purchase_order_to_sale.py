import base64

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestObOCRPurchaseOrderToSale(TransactionCase):

    def test_create_sale_order_from_reviewed_document(self):
        customer = self.env["res.partner"].create({
            "name": "Customer OCR Test",
            "customer_rank": 1,
        })
        provider = self.env["ob.ocr.provider"].create({
            "name": "Sale Stub",
            "code": "sale_stub",
            "provider_key": "stub",
            "service_model": "ob.ocr.provider.service",
            "allowed_mimetypes": "text/plain",
        })
        document = self.env["ob.ocr.document"].create({
            "document_type_id": self.env.ref("ob_ocr_purchase_order_to_sale.document_type_customer_purchase_order").id,
            "ocr_provider_id": provider.id,
            "file": base64.b64encode(b"customer po"),
            "filename": "customer_po.txt",
            "mimetype": "text/plain",
            "extracted_json": {
                "customer_name": customer.name,
                "po_number": "PO-001",
                "order_date": "2026-05-17",
                "currency": self.env.company.currency_id.name,
            },
        })
        document.action_mark_reviewed()
        document.action_create_target_record()
        order = self.env["sale.order"].browse(document.related_res_id)
        self.assertEqual(order.partner_id, customer)
        self.assertEqual(order.client_order_ref, "PO-001")
