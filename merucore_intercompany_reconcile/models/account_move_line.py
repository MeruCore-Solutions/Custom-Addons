from odoo import fields, models


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    m_intercompany_settlement_line_ids = fields.One2many(
        "merucore.intercompany.settlement.line",
        "m_move_line_id",
        string="Intercompany Settlement Lines",
    )
