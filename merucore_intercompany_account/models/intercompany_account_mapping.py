from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class MeruCoreIntercompanyAccountMapping(models.Model):
    _name = "merucore.intercompany.account.mapping"
    _description = "MeruCore Intercompany Account Mapping"
    _order = "m_sequence, id"

    m_name = fields.Char(required=True, translate=True)
    m_active = fields.Boolean(default=True)
    m_rule_id = fields.Many2one(
        "merucore.intercompany.rule",
        required=True,
        ondelete="cascade",
        index=True,
    )
    m_source_company_id = fields.Many2one(
        "res.company",
        related="m_rule_id.m_source_company_id",
        store=True,
        readonly=True,
    )
    m_destination_company_id = fields.Many2one(
        "res.company",
        related="m_rule_id.m_destination_company_id",
        store=True,
        readonly=True,
    )
    m_source_account_id = fields.Many2one(
        "account.account",
        required=True,
        check_company=False,
        ondelete="restrict",
    )
    m_destination_account_id = fields.Many2one(
        "account.account",
        required=True,
        check_company=False,
        ondelete="restrict",
    )
    m_move_scope = fields.Selection(
        selection=[
            ("sale", "Sale"),
            ("purchase", "Purchase"),
            ("refund", "Refund"),
            ("all", "All"),
        ],
        default="all",
        required=True,
    )
    m_sequence = fields.Integer(default=10)
    m_notes = fields.Text()

    @api.constrains("m_source_account_id", "m_destination_account_id", "m_rule_id", "m_move_scope", "m_active")
    def m_check_account_mapping(self):
        blocked_types = {"asset_receivable", "liability_payable", "off_balance"}
        for mapping in self:
            if mapping.m_source_account_id.company_ids and mapping.m_source_company_id not in mapping.m_source_account_id.company_ids:
                raise ValidationError(_("The source account must belong to the rule source company."))
            if mapping.m_destination_account_id.company_ids and mapping.m_destination_company_id not in mapping.m_destination_account_id.company_ids:
                raise ValidationError(_("The destination account must belong to the rule destination company."))
            if mapping.m_source_account_id.account_type in blocked_types:
                raise ValidationError(_("Receivable, payable, and off-balance accounts cannot be mapped as commercial line accounts."))
            if mapping.m_destination_account_id.account_type in blocked_types:
                raise ValidationError(_("Receivable, payable, and off-balance accounts cannot be mapped as commercial line accounts."))
            duplicate = self.search(
                [
                    ("id", "!=", mapping.id),
                    ("m_active", "=", True),
                    ("m_rule_id", "=", mapping.m_rule_id.id),
                    ("m_source_account_id", "=", mapping.m_source_account_id.id),
                    ("m_move_scope", "=", mapping.m_move_scope),
                ],
                limit=1,
            )
            if mapping.m_active and duplicate:
                raise ValidationError(_("Only one active account mapping per source account and scope is allowed."))
