from .common import IntercompanySalePurchaseCommon


class TestPurchaseToSale(IntercompanySalePurchaseCommon):
    def test_po_creates_one_so(self):
        self.m_create_sale_purchase_rule(trigger_document="purchase_order")
        purchase_order = self.m_create_purchase_order()

        purchase_order.with_user(self.m_sync_user).m_action_create_counterpart_order()
        transaction = purchase_order.m_intercompany_transaction_id

        self.assertTrue(transaction)
        self.assertEqual(transaction.m_purchase_order_id, purchase_order)
        self.assertTrue(transaction.m_sale_order_id)
        self.assertEqual(transaction.m_sale_order_id.company_id, self.company_a)
        self.assertEqual(transaction.m_sale_order_id.partner_id.commercial_partner_id, self.company_b.partner_id.commercial_partner_id)
