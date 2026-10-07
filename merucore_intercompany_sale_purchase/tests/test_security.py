from odoo.exceptions import AccessError

from .common import IntercompanySalePurchaseCommon


class TestSalePurchaseSecurity(IntercompanySalePurchaseCommon):
    def test_user_without_purchase_rights_cannot_create_po_manually(self):
        self.m_create_sale_purchase_rule(trigger_document="sale_order")
        sale_order = self.m_create_sale_order(user=self.m_sale_only_user)

        with self.assertRaises(AccessError):
            sale_order.with_user(self.m_sale_only_user).m_action_create_counterpart_order()

    def test_single_company_user_cannot_read_counterpart_fields(self):
        self.m_create_sale_purchase_rule(
            trigger_document="sale_order",
            creation_timing="on_confirmation",
        )
        sale_order = self.m_create_sale_order(user=self.m_single_company_sale_user)

        sale_order.with_user(self.m_single_company_sale_user).action_confirm()
        row = sale_order.with_user(self.m_single_company_sale_user).read(
            ["m_intercompany_transaction_id", "m_intercompany_counterpart_id"]
        )[0]

        self.assertFalse(row["m_intercompany_transaction_id"])
        self.assertFalse(row["m_intercompany_counterpart_id"])
