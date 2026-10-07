from odoo import _, models
from odoo.exceptions import UserError


class OcrDocument(models.Model):
    _inherit = "ob.ocr.document"

    def _prepare_vendor_bill_values(self):
        self.ensure_one()
        payload = self.extracted_json or {}
        vendor = self._resolve_partner_match({
            "vendor_name": payload.get("vendor_name"),
            "vendor_vat": payload.get("vendor_vat") or payload.get("vendor_tax_id"),
            "email": payload.get("vendor_email"),
            "phone": payload.get("vendor_phone"),
            "address": payload.get("vendor_address"),
        }, role="vendor")
        if not vendor:
            raise UserError(_("No vendor could be matched from the OCR result. Review the document or enable partner creation."))
        payment_term = self._match_payment_term(payload.get("payment_terms"))

        values = {
            "move_type": "in_invoice",
            "partner_id": vendor.id,
            "currency_id": self._match_currency(payload.get("currency")).id,
            "ref": payload.get("bill_number"),
            "payment_reference": payload.get("payment_reference") or payload.get("bill_number"),
            "invoice_date": self._parse_date_value(payload.get("bill_date")),
            "invoice_date_due": self._parse_date_value(payload.get("due_date")),
            "invoice_payment_term_id": payment_term.id if payment_term else False,
            "narration": payload.get("notes"),
        }

        line_commands = []
        for line_payload in self._get_line_payloads():
            line_vals = self._prepare_vendor_bill_line_values(line_payload)
            if line_vals:
                line_commands.append((0, 0, line_vals))
        if line_commands:
            values["invoice_line_ids"] = line_commands
        return {key: value for key, value in values.items() if value not in (False, None, "", [])}

    def _prepare_vendor_bill_line_values(self, line_payload):
        product = self.env["ob.ocr.product.matcher"].match_product(line_payload)
        if not product and not (line_payload.get("name") or line_payload.get("product_name")):
            return False
        taxes = self._match_taxes(line_payload.get("taxes"), "purchase")
        values = {
            "name": line_payload.get("product_name") or line_payload.get("name") or product.display_name,
            "product_id": product.id if product else False,
            "quantity": line_payload.get("quantity") or 1.0,
            "price_unit": self._parse_float_value(line_payload.get("unit_price") or 0.0),
            "discount": self._parse_float_value(line_payload.get("discount") or 0.0),
            "tax_ids": [(6, 0, taxes.ids)] if taxes else False,
        }
        return {key: value for key, value in values.items() if value not in (False, None, "")}

    def _create_vendor_bill_record(self, values=None):
        self.ensure_one()
        values = values or self._prepare_vendor_bill_values()
        record = self.env["account.move"].create(values)
        self._set_related_record(record)
        self._attach_original_file(record)
        return record

    def _update_vendor_bill_record(self, values=None):
        self.ensure_one()
        values = values or self._prepare_vendor_bill_values()
        record = self.env[self.related_model].browse(self.related_res_id).exists()
        if not record:
            raise UserError(_("The linked vendor bill no longer exists."))
        record.write(values)
        self._attach_original_file(record)
        return record
