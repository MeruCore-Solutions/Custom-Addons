from odoo import _, fields, models
from odoo.exceptions import UserError


class OcrDocument(models.Model):
    _inherit = "ob.ocr.document"

    def _prepare_customer_purchase_order_values(self):
        self.ensure_one()
        payload = self.extracted_json or {}
        customer = self._resolve_partner_match({
            "customer_name": payload.get("customer_name"),
            "customer_vat": payload.get("customer_vat") or payload.get("customer_tax_id"),
            "email": payload.get("customer_email"),
            "phone": payload.get("customer_phone"),
            "address": payload.get("customer_address"),
        }, role="customer")
        if not customer:
            raise UserError(_("No customer could be matched from the OCR result. Review the document or enable partner creation."))
        payment_term = self._match_payment_term(payload.get("payment_terms"))
        incoterm = self._match_incoterm(payload.get("incoterm"))

        values = {
            "partner_id": customer.id,
            "partner_invoice_id": customer.address_get(["invoice"]).get("invoice", customer.id),
            "partner_shipping_id": customer.address_get(["delivery"]).get("delivery", customer.id),
            "client_order_ref": payload.get("customer_reference") or payload.get("po_number"),
            "date_order": self._parse_date_value(payload.get("order_date")) or fields.Date.today(),
            "currency_id": self._match_currency(payload.get("currency")).id,
            "payment_term_id": payment_term.id if payment_term else False,
            "note": payload.get("notes"),
        }
        if "validity_date" in self.env["sale.order"]._fields and payload.get("expected_delivery_date"):
            values["validity_date"] = self._parse_date_value(payload.get("expected_delivery_date"))
        if "commitment_date" in self.env["sale.order"]._fields and payload.get("expected_delivery_date"):
            values["commitment_date"] = self._parse_date_value(payload.get("expected_delivery_date"))
        if incoterm and "incoterm" in self.env["sale.order"]._fields:
            values["incoterm"] = incoterm.id
        if incoterm and "incoterm_id" in self.env["sale.order"]._fields:
            values["incoterm_id"] = incoterm.id

        order_lines = []
        for line_payload in self._get_line_payloads():
            line_vals = self._prepare_sale_order_line_values(line_payload)
            if line_vals:
                order_lines.append((0, 0, line_vals))
        if order_lines:
            values["order_line"] = order_lines
        return {key: value for key, value in values.items() if value not in (False, None, "", [])}

    def _prepare_sale_order_line_values(self, line_payload):
        product = self.env["ob.ocr.product.matcher"].match_product(line_payload)
        taxes = self._match_taxes(line_payload.get("taxes"), "sale")
        unit_uom = self.env.ref("uom.product_uom_unit", raise_if_not_found=False)
        values = {
            "product_id": product.id if product else False,
            "name": line_payload.get("product_name") or line_payload.get("name") or product.display_name,
            "product_uom_qty": line_payload.get("quantity") or 1.0,
            "price_unit": self._parse_float_value(line_payload.get("unit_price") or 0.0),
            "discount": self._parse_float_value(line_payload.get("discount") or 0.0),
            "tax_id": [(6, 0, taxes.ids)] if taxes else False,
            "product_uom": product.uom_id.id if product and "product_uom" in self.env["sale.order.line"]._fields else unit_uom.id if unit_uom and "product_uom" in self.env["sale.order.line"]._fields else False,
        }
        if not values["name"]:
            return False
        return {key: value for key, value in values.items() if value not in (False, None, "")}

    def _create_customer_purchase_order_sale_record(self, values=None):
        self.ensure_one()
        values = values or self._prepare_customer_purchase_order_values()
        record = self.env["sale.order"].create(values)
        self._set_related_record(record)
        self._attach_original_file(record)
        if self.reviewed and self.env["ir.config_parameter"].sudo().get_param(
            "ob_ocr_base.auto_confirm_sale_orders",
            default="False",
        ) == "True":
            record.action_confirm()
        return record

    def _update_customer_purchase_order_sale_record(self, values=None):
        self.ensure_one()
        values = values or self._prepare_customer_purchase_order_values()
        record = self.env[self.related_model].browse(self.related_res_id).exists()
        if not record:
            raise UserError(_("The linked sale order no longer exists."))
        record.write(values)
        self._attach_original_file(record)
        if self.reviewed and self.env["ir.config_parameter"].sudo().get_param(
            "ob_ocr_base.auto_confirm_sale_orders",
            default="False",
        ) == "True" and record.state in ("draft", "sent"):
            record.action_confirm()
        return record
