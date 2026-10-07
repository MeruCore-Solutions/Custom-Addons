from odoo import fields, models


class MeruCoreIntercompanyTransaction(models.Model):
    _inherit = "merucore.intercompany.transaction"

    m_match_ids = fields.One2many(
        "merucore.intercompany.match",
        "m_transaction_id",
        string="Reconciliation Matches",
    )
    m_settlement_ids = fields.One2many(
        "merucore.intercompany.settlement",
        "m_transaction_id",
        string="Reconciliation Settlements",
    )
    m_match_count = fields.Integer(
        compute="m_compute_reconcile_document_counts",
    )
    m_settlement_count = fields.Integer(
        compute="m_compute_reconcile_document_counts",
    )

    def m_compute_reconcile_document_counts(self):
        match_grouped = self.env["merucore.intercompany.match"]._read_group(
            [("m_transaction_id", "in", self.ids)],
            ["m_transaction_id"],
            ["__count"],
        )
        settlement_grouped = self.env["merucore.intercompany.settlement"]._read_group(
            [("m_transaction_id", "in", self.ids)],
            ["m_transaction_id"],
            ["__count"],
        )
        match_counts = {transaction.id: count for transaction, count in match_grouped}
        settlement_counts = {transaction.id: count for transaction, count in settlement_grouped}
        for transaction in self:
            transaction.m_match_count = match_counts.get(transaction.id, 0)
            transaction.m_settlement_count = settlement_counts.get(transaction.id, 0)

    def m_action_open_matches(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "merucore_intercompany_reconcile.m_action_intercompany_matches"
        )
        action["domain"] = [("m_transaction_id", "=", self.id)]
        action["context"] = {
            "default_m_transaction_id": self.id,
            "default_m_rule_id": self.m_rule_id.id,
            "allowed_company_ids": self.m_company_ids.ids,
        }
        return action

    def m_action_open_settlements(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "merucore_intercompany_reconcile.m_action_intercompany_settlements"
        )
        action["domain"] = [("m_transaction_id", "=", self.id)]
        action["context"] = {
            "default_m_transaction_id": self.id,
            "default_m_rule_id": self.m_rule_id.id,
            "allowed_company_ids": self.m_company_ids.ids,
        }
        return action
