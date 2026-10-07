from odoo import _, models
from odoo.exceptions import ValidationError


class ResCompany(models.Model):
    _inherit = "res.company"

    def m_get_intercompany_general_journal(self):
        self.ensure_one()
        journal = self.env["account.journal"].search(
            [
                ("company_id", "=", self.id),
                ("type", "=", "general"),
            ],
            order="sequence, id",
            limit=1,
        )
        if not journal:
            raise ValidationError(
                _("No general journal is configured for company %(company)s.", company=self.display_name)
            )
        return journal

    def m_get_intercompany_payment_journal(self):
        self.ensure_one()
        journal = self.env["account.journal"].search(
            [
                ("company_id", "=", self.id),
                ("type", "in", ("bank", "cash")),
            ],
            order="sequence, id",
            limit=1,
        )
        if not journal:
            raise ValidationError(
                _("No bank or cash journal is configured for company %(company)s.", company=self.display_name)
            )
        return journal
