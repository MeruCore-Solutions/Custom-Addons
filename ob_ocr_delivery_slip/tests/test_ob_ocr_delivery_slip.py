import base64

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestObOCRDeliverySlip(TransactionCase):

    def test_create_picking_from_reviewed_document(self):
        partner = self.env["res.partner"].create({
            "name": "Delivery OCR Partner",
        })
        provider = self.env["ob.ocr.provider"].create({
            "name": "Delivery Stub",
            "code": "delivery_stub",
            "provider_key": "stub",
            "service_model": "ob.ocr.provider.service",
            "allowed_mimetypes": "text/plain",
        })
        document = self.env["ob.ocr.document"].create({
            "document_type_id": self.env.ref("ob_ocr_delivery_slip.document_type_delivery_slip").id,
            "ocr_provider_id": provider.id,
            "file": base64.b64encode(b"delivery slip"),
            "filename": "delivery_slip.txt",
            "mimetype": "text/plain",
            "extracted_json": {
                "partner_name": partner.name,
                "delivery_slip_number": "DS-001",
                "delivery_date": "2026-05-17",
            },
        })
        document.action_mark_reviewed()
        document.action_create_target_record()
        picking = self.env["stock.picking"].browse(document.related_res_id)
        self.assertEqual(picking.partner_id, partner)
        self.assertEqual(document.related_model, "stock.picking")
