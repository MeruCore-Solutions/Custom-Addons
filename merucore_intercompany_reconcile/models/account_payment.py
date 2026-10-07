from odoo import fields, models


class AccountPayment(models.Model):
    _inherit = "account.payment"

    m_intercompany_settlement_id = fields.Many2one(
        "merucore.intercompany.settlement",
        copy=False,
        index=True,
        ondelete="set null",
    )
