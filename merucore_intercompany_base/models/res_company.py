from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ResCompany(models.Model):
    _inherit = "res.company"

    m_intercompany_enabled = fields.Boolean(default=False)
    m_intercompany_default_responsible_user_id = fields.Many2one(
        "res.users",
        string="Default Intercompany Responsible",
        ondelete="set null",
    )
    m_intercompany_rule_ids = fields.Many2many(
        "merucore.intercompany.rule",
        compute="m_compute_intercompany_rules",
    )
    m_intercompany_rule_count = fields.Integer(
        compute="m_compute_intercompany_rules",
    )

    @api.depends("m_intercompany_enabled")
    def m_compute_intercompany_rules(self):
        rules = self.env["merucore.intercompany.rule"].search(
            [
                "|",
                ("m_source_company_id", "in", self.ids),
                ("m_destination_company_id", "in", self.ids),
            ]
        )
        rules_by_company = {company.id: self.env["merucore.intercompany.rule"] for company in self}
        for rule in rules:
            if rule.m_source_company_id.id in rules_by_company:
                rules_by_company[rule.m_source_company_id.id] |= rule
            if rule.m_destination_company_id.id in rules_by_company:
                rules_by_company[rule.m_destination_company_id.id] |= rule
        for company in self:
            company.m_intercompany_rule_ids = rules_by_company[company.id]
            company.m_intercompany_rule_count = len(rules_by_company[company.id])

    @api.constrains("m_intercompany_default_responsible_user_id")
    def m_check_intercompany_default_responsible(self):
        for company in self.filtered("m_intercompany_default_responsible_user_id"):
            if company not in company.m_intercompany_default_responsible_user_id.company_ids:
                raise ValidationError(
                    _("The default intercompany responsible user must have access to the company.")
                )

    def m_action_open_intercompany_rules(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "merucore_intercompany_base.m_action_intercompany_rules"
        )
        action["domain"] = [
            "|",
            ("m_source_company_id", "=", self.id),
            ("m_destination_company_id", "=", self.id),
        ]
        action["context"] = {
            "default_m_source_company_id": self.id,
            "allowed_company_ids": self.ids,
        }
        return action
