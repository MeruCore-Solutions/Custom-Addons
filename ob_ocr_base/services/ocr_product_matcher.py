from odoo import _, models
from odoo.exceptions import UserError


class OCRProductMatcher(models.AbstractModel):
    _name = "ob.ocr.product.matcher"
    _description = "OCR Product Matcher"

    def match_product(self, payload, allow_create=None):
        if not self.env.registry.get("product.product"):
            raise UserError(_("The Product application must be installed before OCR can match products."))
        product_model = self.env["product.product"]
        allow_create = self._resolve_allow_create(allow_create)
        search_values = [
            ("default_code", payload.get("product_code") or payload.get("default_code") or payload.get("vendor_product_code") or payload.get("customer_product_code")),
            ("barcode", payload.get("barcode")),
            ("name", payload.get("product_name") or payload.get("name")),
        ]
        for field_name, value in search_values:
            if not value:
                continue
            operator = "=" if field_name in ("default_code", "barcode") else "ilike"
            product = product_model.search([(field_name, operator, value)], limit=1)
            if product:
                return product
        if not allow_create:
            return product_model.browse()
        product_name = payload.get("product_name") or payload.get("name")
        if not product_name:
            raise UserError(_("A product name is required before a new product can be created from OCR data."))
        template = self.env["product.template"].create({
            "name": product_name,
            "default_code": payload.get("product_code") or payload.get("default_code"),
            "barcode": payload.get("barcode"),
            "type": "consu",
        })
        return template.product_variant_id

    def _resolve_allow_create(self, allow_create):
        if allow_create is not None:
            return allow_create
        return self.env["ir.config_parameter"].sudo().get_param(
            "ob_ocr_base.allow_create_products",
            default="False",
        ) == "True"
