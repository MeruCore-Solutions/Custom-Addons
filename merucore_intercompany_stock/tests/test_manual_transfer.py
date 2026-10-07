from odoo import Command, fields
from odoo.tests import tagged

from .common import IntercompanyStockCommon


@tagged("post_install", "-at_install")
class TestManualTransfer(IntercompanyStockCommon):
    def test_manual_transfer_generates_linked_pickings(self):
        rule = self.m_create_stock_rule(workflow="both")

        transfer = (
            self.env["merucore.intercompany.stock.transfer"]
            .with_user(self.m_stock_manager)
            .with_context(allowed_company_ids=self.allowed_pair_ids)
            .create(
                {
                    "m_rule_id": rule.id,
                    "m_reference": "MT-001",
                    "m_planned_date": fields.Datetime.now(),
                    "m_line_ids": [
                        Command.create(
                            {
                                "m_product_id": self.m_shared_product.id,
                                "m_description": self.m_shared_product.display_name,
                                "m_quantity": 3.0,
                                "m_uom_id": self.m_shared_product.uom_id.id,
                            }
                        )
                    ],
                }
            )
        )

        transfer.m_action_generate_documents()

        self.assertEqual(transfer.m_state, "confirmed")
        self.assertTrue(transfer.m_intercompany_transaction_id)
        self.assertTrue(transfer.m_source_picking_id)
        self.assertTrue(transfer.m_destination_picking_id)
        self.assertEqual(transfer.m_source_picking_id.company_id, self.company_a)
        self.assertEqual(transfer.m_destination_picking_id.company_id, self.company_b)
        self.assertEqual(
            transfer.m_source_picking_id.m_intercompany_counterpart_picking_id,
            transfer.m_destination_picking_id,
        )
        self.assertEqual(
            transfer.m_destination_picking_id.m_intercompany_counterpart_picking_id,
            transfer.m_source_picking_id,
        )
        self.assertEqual(
            transfer.m_intercompany_transaction_id.m_source_picking_id,
            transfer.m_source_picking_id,
        )
        self.assertEqual(
            transfer.m_intercompany_transaction_id.m_destination_picking_id,
            transfer.m_destination_picking_id,
        )
