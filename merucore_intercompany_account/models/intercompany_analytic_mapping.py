from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class MeruCoreIntercompanyAnalyticMapping(models.Model):
    _name = "merucore.intercompany.analytic.mapping"
    _description = "MeruCore Intercompany Analytic Mapping"
    _order = "m_sequence, id"

    m_name = fields.Char(required=True, translate=True)
    m_active = fields.Boolean(default=True)
    m_rule_id = fields.Many2one(
        "merucore.intercompany.rule",
        required=True,
        ondelete="cascade",
        index=True,
    )
    m_source_analytic_account_id = fields.Many2one(
        "account.analytic.account",
        required=True,
        check_company=False,
        ondelete="restrict",
    )
    m_destination_analytic_account_id = fields.Many2one(
        "account.analytic.account",
        required=True,
        check_company=False,
        ondelete="restrict",
    )
    m_source_analytic_plan_id = fields.Many2one(
        "account.analytic.plan",
        string="Source Plan",
        related="m_source_analytic_account_id.plan_id",
        store=True,
        readonly=True,
    )
    m_destination_analytic_plan_id = fields.Many2one(
        "account.analytic.plan",
        string="Destination Plan",
        related="m_destination_analytic_account_id.plan_id",
        store=True,
        readonly=True,
    )
    m_sequence = fields.Integer(default=10)

    @api.constrains("m_source_analytic_account_id", "m_destination_analytic_account_id", "m_rule_id", "m_active")
    def m_check_analytic_mapping(self):
        for mapping in self:
            if (
                mapping.m_source_analytic_account_id.company_id
                and mapping.m_source_analytic_account_id.company_id != mapping.m_rule_id.m_source_company_id
            ):
                raise ValidationError(_("The source analytic account must belong to the rule source company or be shared."))
            if (
                mapping.m_destination_analytic_account_id.company_id
                and mapping.m_destination_analytic_account_id.company_id != mapping.m_rule_id.m_destination_company_id
            ):
                raise ValidationError(_("The destination analytic account must belong to the rule destination company or be shared."))
            duplicate = self.search(
                [
                    ("id", "!=", mapping.id),
                    ("m_active", "=", True),
                    ("m_rule_id", "=", mapping.m_rule_id.id),
                    ("m_source_analytic_account_id", "=", mapping.m_source_analytic_account_id.id),
                ],
                limit=1,
            )
            if mapping.m_active and duplicate:
                raise ValidationError(_("Only one active analytic mapping per source analytic account is allowed."))
