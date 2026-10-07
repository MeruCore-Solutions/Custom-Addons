from odoo import _, models
from odoo.exceptions import UserError


class OCRPartnerMatcher(models.AbstractModel):
    _name = "ob.ocr.partner.matcher"
    _description = "OCR Partner Matcher"

    def match_partner(self, payload, role="partner", allow_create=None):
        partner_model = self.env["res.partner"]
        allow_create = self._resolve_allow_create(allow_create)
        search_candidates = [
            ("vat", payload.get("vat") or payload.get("%s_vat" % role) or payload.get("%s_tax_id" % role)),
            ("email", payload.get("email") or payload.get("%s_email" % role)),
            ("phone", payload.get("phone") or payload.get("%s_phone" % role)),
            ("name", payload.get("name") or payload.get("%s_name" % role) or payload.get("partner_name")),
        ]
        partner = partner_model.browse()
        for field_name, value in search_candidates:
            if not value:
                continue
            operator = "=" if field_name in ("vat", "email", "phone") else "ilike"
            partner = partner_model.search([(field_name, operator, value)], limit=1)
            if partner:
                return partner
        street = payload.get("address") or payload.get("%s_address" % role)
        if street:
            partner = partner_model.search([("street", "ilike", street)], limit=1)
            if partner:
                return partner
        if not allow_create:
            return partner
        partner_name = payload.get("name") or payload.get("%s_name" % role) or payload.get("partner_name")
        if not partner_name:
            raise UserError(_("A partner name is required before a new partner can be created from OCR data."))
        vals = {
            "name": partner_name,
            "vat": payload.get("vat") or payload.get("%s_vat" % role) or payload.get("%s_tax_id" % role),
            "email": payload.get("email") or payload.get("%s_email" % role),
            "phone": payload.get("phone") or payload.get("%s_phone" % role),
            "street": street,
        }
        if role in ("vendor", "supplier"):
            vals["supplier_rank"] = 1
        if role in ("customer",):
            vals["customer_rank"] = 1
        return partner_model.create(vals)

    def _resolve_allow_create(self, allow_create):
        if allow_create is not None:
            return allow_create
        return self.env["ir.config_parameter"].sudo().get_param(
            "ob_ocr_base.allow_create_partners",
            default="False",
        ) == "True"
