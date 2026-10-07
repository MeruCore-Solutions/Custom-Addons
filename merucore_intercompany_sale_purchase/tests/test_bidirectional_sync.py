from .common import IntercompanySalePurchaseCommon


class TestBidirectionalSync(IntercompanySalePurchaseCommon):
    def test_confirmation_does_not_recurse(self):
        self.m_create_sale_purchase_rule(
            trigger_document="both",
            creation_timing="on_confirmation",
            sync_direction="bidirectional",
        )
        sale_order = self.m_create_sale_order(user=self.m_sync_user)

        sale_order.action_confirm()

        transaction = sale_order.m_intercompany_transaction_id
        self.assertTrue(transaction)
        self.assertTrue(transaction.m_purchase_order_id)
        self.assertEqual(
            self.env["merucore.intercompany.transaction"].search_count(
                [("m_transaction_type", "=", "sale_purchase"), ("m_sale_order_id", "=", sale_order.id)]
            ),
            1,
        )

    def test_conflict_policy_blocks_dual_edits(self):
        self.m_create_sale_purchase_rule(
            trigger_document="sale_order",
            conflict_policy="block_and_review",
        )
        sale_order = self.m_create_sale_order()
        sale_order.m_action_create_counterpart_order()

        purchase_order = sale_order.m_intercompany_counterpart_id
        sale_order.write({"note": "<p>Changed on sale</p>"})
        purchase_order.write({"note": "<p>Changed on purchase</p>"})
        sale_order.m_action_synchronize_now()

        transaction = sale_order.m_intercompany_transaction_id
        self.assertTrue(transaction.m_pending_conflict)
        self.assertIn("Changed on purchase", purchase_order.note or "")
