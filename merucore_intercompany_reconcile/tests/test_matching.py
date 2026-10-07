from .common import IntercompanyReconcileCommon


class TestIntercompanyMatching(IntercompanyReconcileCommon):
    def test_match_creates_draft_settlement_proposal(self):
        rule = self.m_create_reconcile_rule()
        invoice, bill = self.m_create_intercompany_documents(amount=125.0)
        match = self.m_create_match(rule, invoice, bill)

        self.assertEqual(match.m_source_residual_amount, 125.0)
        self.assertEqual(match.m_destination_residual_amount, 125.0)
        self.assertTrue(match.m_source_move_line_ids)
        self.assertTrue(match.m_destination_move_line_ids)

        match.m_action_create_settlement()
        settlement = match.m_settlement_ids[:1]

        self.assertTrue(settlement)
        self.assertEqual(settlement.m_state, "draft")
        self.assertEqual(settlement.m_source_amount, 125.0)
        self.assertEqual(settlement.m_destination_amount, 125.0)
        self.assertEqual(len(settlement.m_line_ids), 2)
