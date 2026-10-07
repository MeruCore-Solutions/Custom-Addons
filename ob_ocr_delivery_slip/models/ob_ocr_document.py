from odoo import _, fields, models
from odoo.exceptions import UserError


class OcrDocument(models.Model):
    _inherit = "ob.ocr.document"

    def _prepare_delivery_slip_values(self):
        self.ensure_one()
        payload = self.extracted_json or {}
        source_sale_order = self._find_sale_order_from_payload(payload)
        source_purchase_order = self._find_purchase_order_from_payload(payload)
        partner = self._match_delivery_partner(payload, source_sale_order, source_purchase_order)
        picking_type = self._resolve_delivery_picking_type(source_sale_order, source_purchase_order)
        if not picking_type:
            raise UserError(_("No suitable picking type could be resolved for this delivery slip."))
        source_location = self._resolve_stock_location(
            payload.get("source_location"),
            fallback=picking_type.default_location_src_id,
        )
        destination_location = self._resolve_stock_location(
            payload.get("destination_location"),
            fallback=picking_type.default_location_dest_id,
        )
        values = {
            "partner_id": partner.id if partner else False,
            "origin": payload.get("source_document") or payload.get("delivery_slip_number"),
            "scheduled_date": self._parse_date_value(payload.get("scheduled_date") or payload.get("delivery_date")) or fields.Date.today(),
            "picking_type_id": picking_type.id,
            "location_id": source_location.id,
            "location_dest_id": destination_location.id,
            "note": payload.get("notes"),
        }
        if "carrier_id" in self.env["stock.picking"]._fields:
            carrier = self._match_delivery_carrier(payload.get("carrier"))
            if carrier:
                values["carrier_id"] = carrier.id
        if "carrier_tracking_ref" in self.env["stock.picking"]._fields and payload.get("tracking_number"):
            values["carrier_tracking_ref"] = payload.get("tracking_number")
        return {key: value for key, value in values.items() if value not in (False, None, "", [])}

    def _create_delivery_slip_record(self, values=None):
        self.ensure_one()
        payload = self.extracted_json or {}
        existing_picking = self._find_existing_delivery_picking(payload)
        if existing_picking:
            self._set_related_record(existing_picking)
            self._apply_delivery_slip_updates(existing_picking, payload)
            self._attach_original_file(existing_picking)
            self._auto_validate_delivery_picking(existing_picking)
            return existing_picking

        values = values or self._prepare_delivery_slip_values()
        picking = self.env["stock.picking"].create(values)
        self._set_related_record(picking)
        self._apply_delivery_slip_updates(picking, payload)
        self._attach_original_file(picking)
        self._auto_validate_delivery_picking(picking)
        return picking

    def _update_delivery_slip_record(self, values=None):
        self.ensure_one()
        payload = self.extracted_json or {}
        picking = self.env[self.related_model].browse(self.related_res_id).exists() if self.related_model and self.related_res_id else self._find_existing_delivery_picking(payload)
        if not picking:
            raise UserError(_("No stock picking could be found to update from this delivery slip."))
        values = values or self._prepare_delivery_slip_values()
        picking.write(values)
        self._apply_delivery_slip_updates(picking, payload)
        self._attach_original_file(picking)
        self._auto_validate_delivery_picking(picking)
        return picking

    def _apply_delivery_slip_updates(self, picking, payload):
        line_payloads = self._get_line_payloads()
        for line_payload in line_payloads:
            self._apply_single_delivery_line(picking, line_payload)
        return True

    def _apply_single_delivery_line(self, picking, line_payload):
        product = self.env["ob.ocr.product.matcher"].match_product(line_payload)
        if not product:
            return False
        move = picking.move_ids.filtered(lambda move_line: move_line.product_id == product)[:1]
        quantity = line_payload.get("delivered_quantity") or line_payload.get("quantity") or 0.0
        quantity = self._parse_float_value(quantity or 0.0)
        if not move:
            move = self.env["stock.move"].create({
                "name": line_payload.get("product_name") or product.display_name,
                "product_id": product.id,
                "product_uom_qty": quantity or 0.0,
                "product_uom": product.uom_id.id,
                "picking_id": picking.id,
                "location_id": picking.location_id.id,
                "location_dest_id": picking.location_dest_id.id,
                "company_id": picking.company_id.id,
            })
        else:
            move.product_uom_qty = max(move.product_uom_qty, quantity)

        move_line = move.move_line_ids[:1]
        move_line_values = {
            "picking_id": picking.id,
            "move_id": move.id,
            "company_id": picking.company_id.id,
            "product_id": product.id,
            "product_uom_id": product.uom_id.id,
            "quantity": quantity,
            "location_id": picking.location_id.id,
            "location_dest_id": picking.location_dest_id.id,
            "picked": True,
        }
        if line_payload.get("lot_serial_number"):
            move_line_values["lot_name"] = line_payload.get("lot_serial_number")
        if move_line:
            move_line.write(move_line_values)
        else:
            self.env["stock.move.line"].create(move_line_values)
        return True

    def _find_existing_delivery_picking(self, payload):
        source_reference = payload.get("source_document") or payload.get("delivery_slip_number")
        if not source_reference:
            return self.env["stock.picking"]
        return self.env["stock.picking"].search([
            "|",
            ("name", "=", source_reference),
            ("origin", "=", source_reference),
        ], limit=1, order="scheduled_date desc, id desc")

    def _find_sale_order_from_payload(self, payload):
        source_reference = payload.get("source_document")
        if not source_reference:
            return self.env["sale.order"]
        return self.env["sale.order"].search([
            "|",
            ("name", "=", source_reference),
            ("client_order_ref", "=", source_reference),
        ], limit=1)

    def _find_purchase_order_from_payload(self, payload):
        source_reference = payload.get("source_document")
        if not source_reference:
            return self.env["purchase.order"]
        return self.env["purchase.order"].search([
            "|",
            ("name", "=", source_reference),
            ("partner_ref", "=", source_reference),
        ], limit=1)

    def _match_delivery_partner(self, payload, sale_order=False, purchase_order=False):
        if sale_order:
            return sale_order.partner_shipping_id or sale_order.partner_id
        if purchase_order:
            return purchase_order.partner_id
        return self._resolve_partner_match({
            "name": payload.get("partner_name"),
            "vat": payload.get("partner_vat") or payload.get("partner_tax_id"),
            "address": payload.get("delivery_address"),
        })

    def _resolve_delivery_picking_type(self, sale_order=False, purchase_order=False):
        picking_type_model = self.env["stock.picking.type"]
        code = "internal"
        if sale_order:
            code = "outgoing"
        elif purchase_order:
            code = "incoming"
        return picking_type_model.search([
            ("code", "=", code),
            ("company_id", "=", self.company_id.id),
        ], limit=1) or picking_type_model.search([("code", "=", code)], limit=1)

    def _resolve_stock_location(self, location_value, fallback=False):
        if location_value:
            location = self.env["stock.location"].search([
                "|",
                ("complete_name", "ilike", location_value),
                ("name", "ilike", location_value),
            ], limit=1)
            if location:
                return location
        return fallback

    def _match_delivery_carrier(self, carrier_value):
        if not carrier_value or not self.env.registry.get("delivery.carrier"):
            return False
        return self.env["delivery.carrier"].search([
            "|",
            ("name", "=", carrier_value),
            ("name", "ilike", carrier_value),
        ], limit=1)

    def _auto_validate_delivery_picking(self, picking):
        if not self.reviewed:
            return False
        if self.env["ir.config_parameter"].sudo().get_param(
            "ob_ocr_base.auto_validate_delivery_orders",
            default="False",
        ) != "True":
            return False
        try:
            picking.with_context(skip_immediate=True, skip_backorder=True).button_validate()
        except Exception as exc:  # pragma: no cover - validation depends on stock state
            self._log_event("warning", "Automatic delivery validation failed.", {"error": str(exc)})
        return True
