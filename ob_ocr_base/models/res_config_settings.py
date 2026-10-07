from odoo import _, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    ocr_default_provider_id = fields.Many2one("ob.ocr.provider", string="Default OCR Provider")
    ocr_enable_handwriting = fields.Boolean(string="Enable Handwriting OCR")
    ocr_default_language = fields.Char(string="Default OCR Language", default="eng")
    ocr_auto_detect_language = fields.Boolean(string="Auto Detect Language", default=True)
    ocr_allow_create_partners = fields.Boolean(string="Allow Creating Partners")
    ocr_allow_create_products = fields.Boolean(string="Allow Creating Products")
    ocr_auto_create_target_records = fields.Boolean(string="Auto Create Target Records")
    ocr_require_manual_review = fields.Boolean(string="Require Manual Review", default=True)
    ocr_auto_confirm_sale_orders = fields.Boolean(string="Auto Confirm Sale Orders")
    ocr_auto_confirm_purchase_orders = fields.Boolean(string="Auto Confirm Purchase Orders")
    ocr_auto_validate_delivery_orders = fields.Boolean(string="Auto Validate Delivery Orders")
    ocr_confidence_threshold = fields.Float(string="Confidence Threshold", default=70.0)

    def get_values(self):
        values = super().get_values()
        params = self.env["ir.config_parameter"].sudo()
        provider_id = params.get_param("ob_ocr_base.default_provider_id", default=False)
        values.update({
            "ocr_default_provider_id": int(provider_id) if provider_id else False,
            "ocr_enable_handwriting": params.get_param("ob_ocr_base.enable_handwriting", default="False") == "True",
            "ocr_default_language": params.get_param("ob_ocr_base.default_language", default="eng"),
            "ocr_auto_detect_language": params.get_param("ob_ocr_base.auto_detect_language", default="True") == "True",
            "ocr_allow_create_partners": params.get_param("ob_ocr_base.allow_create_partners", default="False") == "True",
            "ocr_allow_create_products": params.get_param("ob_ocr_base.allow_create_products", default="False") == "True",
            "ocr_auto_create_target_records": params.get_param("ob_ocr_base.auto_create_target_records", default="False") == "True",
            "ocr_require_manual_review": params.get_param("ob_ocr_base.require_manual_review", default="True") == "True",
            "ocr_auto_confirm_sale_orders": params.get_param("ob_ocr_base.auto_confirm_sale_orders", default="False") == "True",
            "ocr_auto_confirm_purchase_orders": params.get_param("ob_ocr_base.auto_confirm_purchase_orders", default="False") == "True",
            "ocr_auto_validate_delivery_orders": params.get_param("ob_ocr_base.auto_validate_delivery_orders", default="False") == "True",
            "ocr_confidence_threshold": float(params.get_param("ob_ocr_base.confidence_threshold", default="70.0")),
        })
        return values

    def set_values(self):
        super().set_values()
        params = self.env["ir.config_parameter"].sudo()
        params.set_param("ob_ocr_base.default_provider_id", self.ocr_default_provider_id.id or False)
        params.set_param("ob_ocr_base.enable_handwriting", self.ocr_enable_handwriting)
        params.set_param("ob_ocr_base.default_language", self.ocr_default_language or "eng")
        params.set_param("ob_ocr_base.auto_detect_language", self.ocr_auto_detect_language)
        params.set_param("ob_ocr_base.allow_create_partners", self.ocr_allow_create_partners)
        params.set_param("ob_ocr_base.allow_create_products", self.ocr_allow_create_products)
        params.set_param("ob_ocr_base.auto_create_target_records", self.ocr_auto_create_target_records)
        params.set_param("ob_ocr_base.require_manual_review", self.ocr_require_manual_review)
        params.set_param("ob_ocr_base.auto_confirm_sale_orders", self.ocr_auto_confirm_sale_orders)
        params.set_param("ob_ocr_base.auto_confirm_purchase_orders", self.ocr_auto_confirm_purchase_orders)
        params.set_param("ob_ocr_base.auto_validate_delivery_orders", self.ocr_auto_validate_delivery_orders)
        params.set_param("ob_ocr_base.confidence_threshold", self.ocr_confidence_threshold or 0.0)

    def action_open_ocr_providers(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("OCR Providers"),
            "res_model": "ob.ocr.provider",
            "view_mode": "list,form",
        }
