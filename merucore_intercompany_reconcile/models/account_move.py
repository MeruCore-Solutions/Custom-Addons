from odoo import fields, models


class AccountMove(models.Model):
    _inherit = "account.move"

    m_intercompany_match_count = fields.Integer(
        compute="m_compute_intercompany_reconcile_counts",
    )
    m_intercompany_settlement_count = fields.Integer(
        compute="m_compute_intercompany_reconcile_counts",
    )

    def m_compute_intercompany_reconcile_counts(self):
        match_counts = {}
        settlement_counts = {}
        if self.ids:
            self.env.cr.execute(
                """
                SELECT move_id, COUNT(*)
                  FROM (
                        SELECT m_source_move_id AS move_id FROM merucore_intercompany_match WHERE m_source_move_id IN %s
                        UNION ALL
                        SELECT m_destination_move_id AS move_id FROM merucore_intercompany_match WHERE m_destination_move_id IN %s
                  ) matches
              GROUP BY move_id
                """,
                [tuple(self.ids), tuple(self.ids)],
            )
            match_counts = dict(self.env.cr.fetchall())
            self.env.cr.execute(
                """
                SELECT move_id, COUNT(*)
                  FROM (
                        SELECT m_source_move_id AS move_id
                          FROM merucore_intercompany_match match
                          JOIN merucore_intercompany_settlement settlement ON settlement.m_match_id = match.id
                         WHERE match.m_source_move_id IN %s
                        UNION ALL
                        SELECT m_destination_move_id AS move_id
                          FROM merucore_intercompany_match match
                          JOIN merucore_intercompany_settlement settlement ON settlement.m_match_id = match.id
                         WHERE match.m_destination_move_id IN %s
                  ) settlements
              GROUP BY move_id
                """,
                [tuple(self.ids), tuple(self.ids)],
            )
            settlement_counts = dict(self.env.cr.fetchall())
        for move in self:
            move.m_intercompany_match_count = match_counts.get(move.id, 0)
            move.m_intercompany_settlement_count = settlement_counts.get(move.id, 0)

    def m_action_open_intercompany_matches(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "merucore_intercompany_reconcile.m_action_intercompany_matches"
        )
        action["domain"] = [
            "|",
            ("m_source_move_id", "=", self.id),
            ("m_destination_move_id", "=", self.id),
        ]
        action["context"] = {"allowed_company_ids": [self.company_id.id]}
        return action

    def m_action_open_intercompany_settlements(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "merucore_intercompany_reconcile.m_action_intercompany_settlements"
        )
        action["domain"] = [
            "|",
            ("m_match_id.m_source_move_id", "=", self.id),
            ("m_match_id.m_destination_move_id", "=", self.id),
        ]
        action["context"] = {"allowed_company_ids": [self.company_id.id]}
        return action
