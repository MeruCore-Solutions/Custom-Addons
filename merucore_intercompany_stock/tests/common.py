from odoo import Command, fields

from odoo.addons.merucore_intercompany_base.tests.common import IntercompanyTestCommon


class IntercompanyStockCommon(IntercompanyTestCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.group_stock_manager = cls.env.ref("stock.group_stock_manager")
        cls.group_stock_user = cls.env.ref("stock.group_stock_user")
        cls.transit_location = cls.env.ref("stock.stock_location_inter_company")

        cls.warehouse_a = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company_a.id)],
            limit=1,
        )
        cls.warehouse_b = cls.env["stock.warehouse"].search(
            [("company_id", "=", cls.company_b.id)],
            limit=1,
        )
        cls.location_a = cls.warehouse_a.lot_stock_id
        cls.location_b = cls.warehouse_b.lot_stock_id

        cls.m_stock_manager = cls.env["res.users"].create(
            {
                "name": "Intercompany Stock Manager",
                "login": "intercompany_stock_manager",
                "email": "intercompany.stock.manager@example.com",
                "company_id": cls.company_a.id,
                "company_ids": [Command.set([cls.company_a.id, cls.company_b.id])],
                "group_ids": [
                    Command.set(
                        [
                            cls.base_group_user.id,
                            cls.group_manager.id,
                            cls.group_stock_manager.id,
                        ]
                    )
                ],
            }
        )
        cls.m_stock_user = cls.env["res.users"].create(
            {
                "name": "Intercompany Stock User",
                "login": "intercompany_stock_user",
                "email": "intercompany.stock.user@example.com",
                "company_id": cls.company_a.id,
                "company_ids": [Command.set([cls.company_a.id, cls.company_b.id])],
                "group_ids": [
                    Command.set(
                        [
                            cls.base_group_user.id,
                            cls.group_user.id,
                            cls.group_stock_user.id,
                        ]
                    )
                ],
            }
        )

        cls.company_a.m_intercompany_default_responsible_user_id = cls.m_stock_manager
        cls.company_b.m_intercompany_default_responsible_user_id = cls.m_stock_manager

        cls.m_shared_product = cls.env["product.product"].create(
            {
                "name": "Intercompany Stock Product",
                "is_storable": True,
                "default_code": "INTERCO-STOCK-01",
                "barcode": "900000000001",
            }
        )
        cls.m_lot_product = cls.env["product.product"].create(
            {
                "name": "Intercompany Lot Product",
                "is_storable": True,
                "tracking": "lot",
                "default_code": "INTERCO-STOCK-LOT-01",
                "barcode": "900000000002",
            }
        )

    @classmethod
    def m_create_stock_rule(
        cls,
        workflow="automatic",
        product_mapping_strategy="same_product",
    ):
        rule = cls.m_create_rule(
            responsible_user=cls.m_stock_manager,
            name=f"Stock Rule {workflow}",
        )
        rule.with_user(cls.manager_all).with_context(allowed_company_ids=cls.allowed_pair_ids).write(
            {
                "m_stock_sync_enabled": True,
                "m_stock_workflow": workflow,
                "m_stock_product_mapping_strategy": product_mapping_strategy,
                "m_stock_sync_lots": True,
                "m_stock_sync_packages": True,
                "m_stock_sync_owners": True,
                "m_stock_auto_confirm_counterpart": True,
                "m_stock_auto_assign_counterpart": True,
                "m_stock_cancel_counterpart": True,
                "m_stock_transit_location_id": cls.transit_location.id,
                "m_stock_source_picking_type_id": cls.warehouse_a.out_type_id.id,
                "m_stock_destination_picking_type_id": cls.warehouse_b.in_type_id.id,
                "m_stock_destination_location_id": cls.location_b.id,
            }
        )
        return rule

    @classmethod
    def m_add_stock(cls, product, quantity, location=None, lot=False):
        location = location or cls.location_a
        cls.env["stock.quant"].with_company(location.company_id).with_context(
            allowed_company_ids=[location.company_id.id]
        )._update_available_quantity(
            product,
            location,
            quantity,
            lot_id=lot,
        )

    @classmethod
    def m_create_outgoing_picking(cls, product=None, qty=2.0, user=None):
        product = product or cls.m_shared_product
        user = user or cls.m_stock_manager
        return (
            cls.env["stock.picking"]
            .with_user(user)
            .with_company(cls.company_a)
            .with_context(allowed_company_ids=cls.allowed_pair_ids)
            .create(
                {
                    "company_id": cls.company_a.id,
                    "partner_id": cls.company_b.partner_id.id,
                    "picking_type_id": cls.warehouse_a.out_type_id.id,
                    "location_id": cls.location_a.id,
                    "location_dest_id": cls.transit_location.id,
                    "scheduled_date": fields.Datetime.now(),
                    "move_ids": [
                        Command.create(
                            {
                                "description_picking": product.display_name,
                                "product_id": product.id,
                                "product_uom": product.uom_id.id,
                                "product_uom_qty": qty,
                                "company_id": cls.company_a.id,
                                "location_id": cls.location_a.id,
                                "location_dest_id": cls.transit_location.id,
                            }
                        )
                    ],
                }
            )
        )
