from .common import IntercompanyReconcileCommon


class TestIntercompanyBilateralNetting(IntercompanyReconcileCommon):
    def test_bilateral_clearing_posts_and_reconciles_each_company(self):
        rule = self.m_create_reconcile_rule()
        invoice, bill = self.m_create_intercompany_documents(amount=210.0)
        match = self.m_create_match(rule, invoice, bill)
        match.m_action_create_settlement()
        settlement = match.m_settlement_ids[:1]

        settlement.with_user(self.m_reconcile_manager).m_action_approve_source()
        settlement.with_user(self.m_reconcile_manager).m_action_approve_destination()
        settlement.with_user(self.m_reconcile_manager).m_action_post()

        self.assertEqual(settlement.m_state, "posted")
        self.assertEqual(settlement.m_source_entry_move_id.state, "posted")
        self.assertEqual(settlement.m_destination_entry_move_id.state, "posted")

        invoice_lines = invoice.line_ids.filtered(lambda line: line.account_type == "asset_receivable")
        bill_lines = bill.line_ids.filtered(lambda line: line.account_type == "liability_payable")
        self.assertTrue(invoice_lines.reconciled)
        self.assertTrue(bill_lines.reconciled)

        source_due_lines = settlement.m_source_entry_move_id.line_ids.filtered(
            lambda line: line.account_id == self.source_due_from_account
        )
        destination_due_lines = settlement.m_destination_entry_move_id.line_ids.filtered(
            lambda line: line.account_id == self.destination_due_to_account
        )
        self.assertTrue(source_due_lines)
        self.assertTrue(destination_due_lines)

    def test_bilateral_clearing_can_be_reversed(self):
        rule = self.m_create_reconcile_rule()
        invoice, bill = self.m_create_intercompany_documents(amount=175.0)
        match = self.m_create_match(rule, invoice, bill)
        match.m_action_create_settlement()
        settlement = match.m_settlement_ids[:1]

        settlement.with_user(self.m_reconcile_manager).m_action_approve_source()
        settlement.with_user(self.m_reconcile_manager).m_action_approve_destination()
        settlement.with_user(self.m_reconcile_manager).m_action_post()
        settlement.with_user(self.m_reconcile_manager).m_action_reverse()

        self.assertEqual(settlement.m_state, "reversed")
        self.assertTrue(settlement.m_source_reversal_move_id)
        self.assertTrue(settlement.m_destination_reversal_move_id)
        self.assertFalse(invoice.line_ids.filtered(lambda line: line.account_type == "asset_receivable").reconciled)
        self.assertFalse(bill.line_ids.filtered(lambda line: line.account_type == "liability_payable").reconciled)
