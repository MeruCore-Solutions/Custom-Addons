from odoo import _, api, fields, models
from odoo.exceptions import ValidationError
from odoo.tools.float_utils import float_compare


class MeruCoreIntercompanySettlementLine(models.Model):
    _name = "merucore.intercompany.settlement.line"
    _description = "MeruCore Intercompany Settlement Line"
    _order = "m_company_role, id"

    m_settlement_id = fields.Many2one(
        "merucore.intercompany.settlement",
        required=True,
        index=True,
        ondelete="cascade",
    )
    m_match_id = fields.Many2one(
        related="m_settlement_id.m_match_id",
        store=True,
        readonly=True,
    )
    m_company_role = fields.Selection(
        selection=[
            ("source", "Source"),
            ("destination", "Destination"),
        ],
        required=True,
        index=True,
    )
    m_company_id = fields.Many2one(
        "res.company",
        required=True,
        index=True,
        ondelete="restrict",
    )
    m_move_id = fields.Many2one(
        "account.move",
        related="m_move_line_id.move_id",
        store=True,
        readonly=True,
    )
    m_move_line_id = fields.Many2one(
        "account.move.line",
        required=True,
        index=True,
        ondelete="restrict",
        check_company=False,
    )
    m_posting_move_line_id = fields.Many2one(
        "account.move.line",
        copy=False,
        index=True,
        ondelete="set null",
        check_company=False,
    )
    m_account_id = fields.Many2one(
        "account.account",
        related="m_move_line_id.account_id",
        store=True,
        readonly=True,
    )
    m_partner_id = fields.Many2one(
        "res.partner",
        related="m_move_line_id.partner_id",
        store=True,
        readonly=True,
    )
    m_currency_id = fields.Many2one(
        "res.currency",
        related="m_move_line_id.currency_id",
        store=True,
        readonly=True,
        string="Document Currency",
    )
    m_company_currency_id = fields.Many2one(
        "res.currency",
        related="m_company_id.currency_id",
        store=True,
        readonly=True,
        string="Company Currency",
    )
    m_open_amount = fields.Monetary(
        compute="m_compute_amounts",
        currency_field="m_company_currency_id",
        string="Open Amount",
    )
    m_allocated_amount = fields.Monetary(
        currency_field="m_company_currency_id",
        required=True,
    )
    m_allocated_amount_currency = fields.Monetary(
        compute="m_compute_amounts",
        currency_field="m_currency_id",
        string="Allocated In Document Currency",
    )
    m_is_reconciled = fields.Boolean(
        compute="m_compute_amounts",
    )
    m_note = fields.Char()

    @api.depends(
        "m_move_line_id.amount_residual",
        "m_move_line_id.amount_residual_currency",
        "m_move_line_id.reconciled",
        "m_allocated_amount",
    )
    def m_compute_amounts(self):
        for line in self:
            line.m_open_amount = abs(line.m_move_line_id.amount_residual)
            line.m_allocated_amount_currency = min(
                abs(line.m_move_line_id.amount_residual_currency),
                abs(line.m_allocated_amount),
            )
            line.m_is_reconciled = line.m_move_line_id.reconciled

    @api.constrains("m_company_id", "m_move_line_id", "m_allocated_amount")
    def m_check_settlement_line(self):
        for line in self:
            if line.m_company_id != line.m_move_line_id.company_id:
                raise ValidationError(_("The settlement line company must match the move line company."))
            if line.m_move_line_id.parent_state != "posted":
                raise ValidationError(_("Settlement lines can only target posted move lines."))
            if line.m_move_line_id.account_type not in {"asset_receivable", "liability_payable"}:
                raise ValidationError(_("Settlement lines can only target receivable or payable move lines."))
            if line.m_allocated_amount <= 0:
                raise ValidationError(_("Allocated amounts must be strictly positive."))
            if (
                float_compare(
                    line.m_allocated_amount,
                    abs(line.m_move_line_id.amount_residual),
                    precision_rounding=line.m_company_currency_id.rounding,
                )
                > 0
            ):
                raise ValidationError(_("Allocated amounts cannot exceed the current residual amount."))
