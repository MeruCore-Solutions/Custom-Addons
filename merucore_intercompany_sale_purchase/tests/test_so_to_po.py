from odoo import Command
from odoo.exceptions import AccessError

from .common import IntercompanySalePurchaseCommon


class TestSaleToPurchase(IntercompanySalePurchaseCommon):
    def test_so_creates_one_po_and_links_lines(self):
        self.m_create_sale_purchase_rule(trigger_document="sale_order")
        sale_order = self.m_create_sale_order(
            extra_lines=[
                Command.create({"display_type": "line_section", "name": "Section A"}),
                Command.create({"display_type": "line_note", "name": "Note A"}),
            ],
        )

        sale_order.with_user(self.m_sync_user).m_action_create_counterpart_order()
        transaction = sale_order.m_intercompany_transaction_id

        self.assertTrue(transaction)
        self.assertEqual(transaction.m_transaction_type, "sale_purchase")
        self.assertEqual(transaction.m_sale_order_id, sale_order)
        self.assertTrue(transaction.m_purchase_order_id)
        self.assertEqual(transaction.m_purchase_order_id.company_id, self.company_b)
        self.assertEqual(transaction.m_purchase_order_id.partner_id.commercial_partner_id, self.company_a.partner_id.commercial_partner_id)
        self.assertEqual(len(transaction.m_purchase_order_id.order_line), len(sale_order.order_line))
        self.assertTrue(all(sale_order.order_line.mapped("m_intercompany_counterpart_line_id")))

    def test_repeat_so_action_is_idempotent(self):
        self.m_create_sale_purchase_rule(trigger_document="sale_order")
        sale_order = self.m_create_sale_order()

        sale_order.with_user(self.m_sync_user).m_action_create_counterpart_order()
        first_purchase = sale_order.m_intercompany_transaction_id.m_purchase_order_id
        sale_order.with_user(self.m_sync_user).m_action_create_counterpart_order()

        self.assertEqual(sale_order.m_intercompany_transaction_id.m_purchase_order_id, first_purchase)
        self.assertEqual(
            self.env["purchase.order"].search_count([("id", "=", first_purchase.id)]),
            1,
        )

    def test_transaction_factory_allows_internal_state_defaults(self):
        rule = self.m_create_sale_purchase_rule(trigger_document="sale_order")
        sale_order = self.m_create_sale_order()

        transaction = (
            self.env["merucore.intercompany.transaction"]
            .with_user(self.m_sync_user)
            .with_context(allowed_company_ids=self.allowed_pair_ids)
            .m_get_sale_purchase_transaction(m_rule=rule, m_sale_order=sale_order)
        )

        self.assertTrue(transaction)
        self.assertEqual(transaction.m_state, "draft")
        self.assertEqual(transaction.m_counterpart_creation_state, "not_created")
        with self.assertRaises(AccessError):
            transaction.with_user(self.m_sync_user).write({"m_state": "done"})
