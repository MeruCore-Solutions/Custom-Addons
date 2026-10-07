from .common import IntercompanySalePurchaseCommon


class TestSalePurchaseIdempotency(IntercompanySalePurchaseCommon):
    def test_copy_clears_intercompany_links(self):
        self.m_create_sale_purchase_rule(trigger_document="sale_order")
        sale_order = self.m_create_sale_order()
        sale_order.m_action_create_counterpart_order()

        copied_order = sale_order.copy()

        self.assertFalse(copied_order.m_intercompany_transaction_id)
        self.assertFalse(copied_order.m_intercompany_counterpart_id)
        self.assertEqual(copied_order.m_intercompany_sync_state, "not_applicable")
        self.assertFalse(any(copied_order.order_line.mapped("m_intercompany_counterpart_line_id")))
        self.assertTrue(all(copied_order.order_line.mapped("m_intercompany_line_key")))
