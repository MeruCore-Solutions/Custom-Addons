from odoo.tests import tagged

from .common import IntercompanyStockCommon


@tagged("post_install", "-at_install")
class TestPickingSync(IntercompanyStockCommon):
    def test_outgoing_picking_creates_counterpart_receipt(self):
        self.m_create_stock_rule()
        self.m_add_stock(self.m_shared_product, 5.0)

        picking = self.m_create_outgoing_picking(qty=2.0)
        picking.action_confirm()
        picking.action_assign()
        self.assertTrue(picking.move_line_ids)
        picking.move_line_ids.quantity = 2.0
        picking.move_ids.picked = True

        picking.button_validate()

        self.assertEqual(picking.state, "done")
        self.assertTrue(picking.m_intercompany_transaction_id)
        self.assertTrue(picking.m_intercompany_counterpart_picking_id)
        counterpart = picking.m_intercompany_counterpart_picking_id
        self.assertEqual(counterpart.company_id, self.company_b)
        self.assertEqual(counterpart.picking_type_id.code, "incoming")
        self.assertEqual(counterpart.partner_id, self.company_a.partner_id)
        self.assertEqual(counterpart.origin, picking.name)
        self.assertEqual(
            counterpart.move_ids.filtered(lambda move: move.product_id == self.m_shared_product).product_uom_qty,
            2.0,
        )
        self.assertEqual(
            picking.m_intercompany_transaction_id.m_destination_picking_id,
            counterpart,
        )

    def test_lot_names_are_propagated_to_counterpart_receipt(self):
        self.m_create_stock_rule()
        lot_a = self.env["stock.lot"].create(
            {
                "name": "LOT-ICP-001",
                "product_id": self.m_lot_product.id,
                "company_id": self.company_a.id,
            }
        )
        self.m_add_stock(self.m_lot_product, 2.0, lot=lot_a)

        picking = self.m_create_outgoing_picking(product=self.m_lot_product, qty=2.0)
        picking.action_confirm()
        picking.action_assign()
        self.assertTrue(picking.move_line_ids)
        picking.move_line_ids.lot_id = lot_a
        picking.move_line_ids.quantity = 2.0
        picking.move_ids.picked = True

        picking.button_validate()

        counterpart = picking.m_intercompany_counterpart_picking_id
        self.assertTrue(counterpart)
        self.assertTrue(counterpart.move_line_ids.lot_id)
        self.assertEqual(counterpart.move_line_ids.lot_id.name, "LOT-ICP-001")
        self.assertEqual(counterpart.move_line_ids.lot_id.company_id, self.company_b)
