import uuid

from odoo import api, fields, models


class PurchaseOrderLine(models.Model):
    _inherit = "purchase.order.line"

    m_intercompany_transaction_id = fields.Many2one(
        "merucore.intercompany.transaction",
        related="order_id.m_intercompany_transaction_id",
        store=True,
        readonly=True,
        check_company=False,
    )
    m_intercompany_counterpart_line_id = fields.Many2one(
        "sale.order.line",
        copy=False,
        index=True,
        check_company=False,
    )
    m_intercompany_line_key = fields.Char(
        copy=False,
        index=True,
    )
    m_intercompany_sync_version = fields.Integer(default=0, copy=False)
    m_intercompany_last_sync_at = fields.Datetime(copy=False, readonly=True)
    m_intercompany_sync_state = fields.Selection(
        selection=[
            ("not_applicable", "Not Applicable"),
            ("pending", "Pending"),
            ("synced", "Synced"),
            ("warning", "Warning"),
            ("failed", "Failed"),
        ],
        default="not_applicable",
        copy=False,
        readonly=True,
    )
    m_intercompany_last_error = fields.Text(copy=False, readonly=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("m_intercompany_line_key"):
                vals["m_intercompany_line_key"] = uuid.uuid4().hex
        lines = super().create(vals_list)
        if not self.env.context.get("m_skip_intercompany_sync"):
            lines.m_mark_parent_orders_pending()
        return lines

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get("m_skip_intercompany_sync"):
            self.m_mark_parent_orders_pending()
        return result

    def unlink(self):
        orders = self.order_id
        result = super().unlink()
        if not self.env.context.get("m_skip_intercompany_sync"):
            orders.m_mark_intercompany_pending()
        return result

    def read(self, fields=None, load="_classic_read"):
        rows = super().read(fields=fields, load=load)
        protected = {
            "m_intercompany_transaction_id",
            "m_intercompany_counterpart_line_id",
            "m_intercompany_last_error",
        }
        record_map = {line.id: line for line in self.browse([row["id"] for row in rows])}
        for row in rows:
            record = record_map.get(row["id"])
            if record and not record.order_id.m_intercompany_dual_company_access:
                for field_name in protected & set(row):
                    row[field_name] = False
        return rows

    def m_mark_parent_orders_pending(self):
        self.mapped("order_id").m_mark_intercompany_pending()
