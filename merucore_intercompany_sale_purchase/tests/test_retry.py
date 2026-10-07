from .common import IntercompanySalePurchaseCommon


class TestSalePurchaseRetry(IntercompanySalePurchaseCommon):
    def test_retry_reuses_existing_counterpart(self):
        self.m_create_sale_purchase_rule(trigger_document="sale_order")
        sale_order = self.m_create_sale_order()
        sale_order.m_action_create_counterpart_order()

        transaction = sale_order.m_intercompany_transaction_id
        purchase_order = transaction.m_purchase_order_id

        sale_order.write({"note": "<p>Retry me</p>"})
        sale_order.with_context(m_skip_intercompany_sync=True).write({"m_intercompany_sync_state": "failed"})
        transaction.with_context(m_intercompany_internal_write=True).write(
            {
                "m_state": "draft",
                "m_health_state": "warning",
            }
        )
        transaction.m_execute_retry(m_force_retry=True, m_manager_note="Retry")

        self.assertEqual(transaction.m_purchase_order_id, purchase_order)
        self.assertEqual(
            self.env["purchase.order"].search_count([("id", "=", purchase_order.id)]),
            1,
        )
        self.assertIn("Retry me", purchase_order.note or "")
