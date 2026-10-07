from odoo import models, api


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    @api.depends('product_id', 'product_uom_id', 'product_uom_qty')
    def _compute_price_unit(self):
        if self.env.context.get('skip_compute_price_unit'):
            for line in self:
                line.price_unit = line.price_unit
        else:
            super()._compute_price_unit()
