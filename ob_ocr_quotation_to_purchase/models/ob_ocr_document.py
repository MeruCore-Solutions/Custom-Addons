from odoo import _, fields, models
from odoo.exceptions import UserError


class OcrDocument(models.Model):
    _inherit = "ob.ocr.document"

    def _prepare_supplier_quotation_values(self):
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
        incoterm = self._match_incoterm(payload.get("incoterm"))

        values = {
            "partner_id": vendor.id,
            "partner_ref": payload.get("quotation_number"),
            "date_order": self._parse_date_value(payload.get("quotation_date")) or fields.Date.today(),
            "currency_id": self._match_currency(payload.get("currency")).id,
            "payment_term_id": payment_term.id if payment_term else False,
            "incoterm_id": incoterm.id if incoterm else False,
            "notes": payload.get("notes"),
        }

        order_lines = []
        for line_payload in self._get_line_payloads():
            line_vals = self._prepare_purchase_order_line_values(line_payload, payload)
            if line_vals:
                order_lines.append((0, 0, line_vals))
        if order_lines:
            values["order_line"] = order_lines
        return {key: value for key, value in values.items() if value not in (False, None, "", [])}

    def _prepare_purchase_order_line_values(self, line_payload, header_payload):
        product = self.env["ob.ocr.product.matcher"].match_product(line_payload)
        taxes = self._match_taxes(line_payload.get("taxes"), "purchase")
        unit_uom = self.env.ref("uom.product_uom_unit", raise_if_not_found=False)
        values = {
            "product_id": product.id if product else False,
            "name": line_payload.get("product_name") or line_payload.get("name") or product.display_name,
            "product_qty": line_payload.get("quantity") or 1.0,
            "price_unit": self._parse_float_value(line_payload.get("unit_price") or 0.0),
            "discount": self._parse_float_value(line_payload.get("discount") or 0.0),
            "taxes_id": [(6, 0, taxes.ids)] if taxes else False,
            "date_planned": self._parse_date_value(
                line_payload.get("delivery_date") or header_payload.get("delivery_date")
            ) or fields.Date.today(),
            "product_uom": product.uom_po_id.id if product else unit_uom.id if unit_uom else False,
        }
        if not values["name"]:
            return False
        return {key: value for key, value in values.items() if value not in (False, None, "")}

    def _create_supplier_quotation_purchase_record(self, values=None):
        self.ensure_one()
        values = values or self._prepare_supplier_quotation_values()
        record = self.env["purchase.order"].create(values)
        self._set_related_record(record)
        self._attach_original_file(record)
        if self.reviewed and self.env["ir.config_parameter"].sudo().get_param(
            "ob_ocr_base.auto_confirm_purchase_orders",
            default="False",
        ) == "True" and record.state in ("draft", "sent", "to approve"):
            record.button_confirm()
        return record

    def _update_supplier_quotation_purchase_record(self, values=None):
        self.ensure_one()
        values = values or self._prepare_supplier_quotation_values()
        record = self.env[self.related_model].browse(self.related_res_id).exists()
        if not record:
            raise UserError(_("The linked purchase order no longer exists."))
        record.write(values)
        self._attach_original_file(record)
        if self.reviewed and self.env["ir.config_parameter"].sudo().get_param(
            "ob_ocr_base.auto_confirm_purchase_orders",
            default="False",
        ) == "True" and record.state in ("draft", "sent", "to approve"):
            record.button_confirm()
        return record
