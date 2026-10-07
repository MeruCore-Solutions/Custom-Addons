from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class MeruCoreIntercompanyTaxMapping(models.Model):
    _name = "merucore.intercompany.tax.mapping"
    _description = "MeruCore Intercompany Tax Mapping"
    _order = "m_sequence, id"

    m_name = fields.Char(required=True, translate=True)
    m_active = fields.Boolean(default=True)
    m_rule_id = fields.Many2one(
        "merucore.intercompany.rule",
        required=True,
        ondelete="cascade",
        index=True,
    )
    m_source_tax_id = fields.Many2one(
        "account.tax",
        required=True,
        check_company=False,
        ondelete="restrict",
    )
    m_destination_tax_id = fields.Many2one(
        "account.tax",
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

    @api.constrains("m_source_tax_id", "m_destination_tax_id", "m_rule_id", "m_move_scope", "m_active")
    def m_check_tax_mapping(self):
        for mapping in self:
            if mapping.m_source_tax_id.company_id and mapping.m_source_tax_id.company_id != mapping.m_rule_id.m_source_company_id:
                raise ValidationError(_("The source tax must belong to the rule source company."))
            if mapping.m_destination_tax_id.company_id and mapping.m_destination_tax_id.company_id != mapping.m_rule_id.m_destination_company_id:
                raise ValidationError(_("The destination tax must belong to the rule destination company."))
            duplicate = self.search(
                [
                    ("id", "!=", mapping.id),
                    ("m_active", "=", True),
                    ("m_rule_id", "=", mapping.m_rule_id.id),
                    ("m_source_tax_id", "=", mapping.m_source_tax_id.id),
                    ("m_move_scope", "=", mapping.m_move_scope),
                ],
                limit=1,
            )
            if mapping.m_active and duplicate:
                raise ValidationError(_("Only one active tax mapping per source tax and scope is allowed."))
            if (
                mapping.m_destination_tax_id.type_tax_use != "none"
                and mapping.m_source_tax_id.type_tax_use != "none"
                and mapping.m_destination_tax_id.type_tax_use != mapping.m_source_tax_id.type_tax_use
                and mapping.m_move_scope != "refund"
            ):
                raise ValidationError(_("Sale taxes must map to sale taxes and purchase taxes must map to purchase taxes."))
