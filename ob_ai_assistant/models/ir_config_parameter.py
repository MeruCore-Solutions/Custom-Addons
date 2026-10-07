from odoo import models


class IrConfigParameter(models.Model):
    _inherit = "ir.config_parameter"

    def setdefault_param(self, key, value):
        params = self.sudo()
        if not params.search([("key", "=", key)], limit=1):
            params.set_param(key, value)
        return True
