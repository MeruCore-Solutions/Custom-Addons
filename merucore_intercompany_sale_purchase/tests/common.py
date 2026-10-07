from odoo import Command, fields

from odoo.addons.merucore_intercompany_base.tests.common import IntercompanyTestCommon


class IntercompanySalePurchaseCommon(IntercompanyTestCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.group_sale_user = cls.env.ref("sales_team.group_sale_salesman")
        cls.group_sale_manager = cls.env.ref("sales_team.group_sale_manager")
        cls.group_purchase_user = cls.env.ref("purchase.group_purchase_user")
        cls.group_purchase_manager = cls.env.ref("purchase.group_purchase_manager")

        cls.m_sync_user = cls.env["res.users"].create(
            {
                "name": "Intercompany Sale Purchase User",
                "login": "intercompany_sale_purchase_user",
                "email": "sale.purchase.user@example.com",
                "company_id": cls.company_a.id,
                "company_ids": [Command.set([cls.company_a.id, cls.company_b.id])],
                "group_ids": [
                    Command.set(
                        [
                            cls.base_group_user.id,
                            cls.group_user.id,
                            cls.group_sale_user.id,
                            cls.group_purchase_user.id,
                        ]
                    )
                ],
            }
        )
        cls.m_sync_manager = cls.env["res.users"].create(
            {
                "name": "Intercompany Sale Purchase Manager",
                "login": "intercompany_sale_purchase_manager",
                "email": "sale.purchase.manager@example.com",
                "company_id": cls.company_a.id,
                "company_ids": [Command.set([cls.company_a.id, cls.company_b.id])],
                "group_ids": [
                    Command.set(
                        [
                            cls.base_group_user.id,
                            cls.group_manager.id,
                            cls.group_sale_manager.id,
                            cls.group_purchase_manager.id,
                        ]
                    )
                ],
            }
        )
        cls.m_sale_only_user = cls.env["res.users"].create(
            {
                "name": "Intercompany Sale Only User",
                "login": "intercompany_sale_only_user",
                "email": "sale.only.user@example.com",
                "company_id": cls.company_a.id,
                "company_ids": [Command.set([cls.company_a.id, cls.company_b.id])],
                "group_ids": [
                    Command.set(
                        [
                            cls.base_group_user.id,
                            cls.group_user.id,
                            cls.group_sale_user.id,
                        ]
                    )
                ],
            }
        )
        cls.m_single_company_sale_user = cls.env["res.users"].create(
            {
                "name": "Intercompany Single Company Sales User",
                "login": "intercompany_single_company_sales_user",
                "email": "single.company.sales.user@example.com",
                "company_id": cls.company_a.id,
                "company_ids": [Command.set([cls.company_a.id])],
                "group_ids": [
                    Command.set(
                        [
                            cls.base_group_user.id,
                            cls.group_user.id,
                            cls.group_sale_user.id,
                        ]
                    )
                ],
            }
        )

        cls.company_a.m_intercompany_default_responsible_user_id = cls.m_sync_user
        cls.company_b.m_intercompany_default_responsible_user_id = cls.m_sync_user

        cls.m_shared_product = cls.env["product.product"].create(
            {
                "name": "Intercompany Service",
                "type": "service",
                "sale_ok": True,
                "purchase_ok": True,
                "list_price": 150.0,
                "standard_price": 80.0,
                "default_code": "INTERCO-SVC-01",
                "barcode": "123450000001",
            }
        )
        cls.m_alt_product = cls.env["product.product"].create(
            {
                "name": "Intercompany Alternate Service",
                "type": "service",
                "sale_ok": True,
                "purchase_ok": True,
                "list_price": 75.0,
                "standard_price": 40.0,
                "default_code": "INTERCO-SVC-02",
                "barcode": "123450000002",
            }
        )

    @classmethod
    def m_create_sale_purchase_rule(
        cls,
        trigger_document="both",
        creation_timing="on_manual_action",
        sync_direction="source_to_destination",
        conflict_policy="block_and_review",
        product_mapping_strategy="same_product",
        price_strategy="source_document",
        counterpart_state="draft",
        allow_sync_after_confirmation=False,
        allow_line_deletion=True,
        sync_unit_prices=True,
    ):
        rule = cls.m_create_rule(
            responsible_user=cls.m_sync_user,
            name=f"Rule {trigger_document} {creation_timing}",
        )
        rule.with_user(cls.manager_all).with_context(allowed_company_ids=cls.allowed_pair_ids).write(
            {
                "m_sale_purchase_enabled": True,
                "m_trigger_document": trigger_document,
                "m_creation_timing": creation_timing,
                "m_sync_direction": sync_direction,
                "m_sync_header_values": True,
                "m_sync_order_lines": True,
                "m_sync_quantities": True,
                "m_sync_unit_prices": sync_unit_prices,
                "m_sync_discounts": True,
                "m_sync_descriptions": True,
                "m_sync_planned_dates": True,
                "m_sync_uom": True,
                "m_allow_counterpart_line_creation": True,
                "m_allow_counterpart_line_deletion": allow_line_deletion,
                "m_allow_sync_after_confirmation": allow_sync_after_confirmation,
                "m_cancel_counterpart": True,
                "m_company_partner_validation": True,
                "m_price_strategy": price_strategy,
                "m_currency_strategy": "source_document_currency",
                "m_tax_strategy": "destination_product_taxes",
                "m_product_mapping_strategy": product_mapping_strategy,
                "m_conflict_policy": conflict_policy,
                "m_counterpart_document_state": counterpart_state,
                "m_confirm_counterpart_automatically": counterpart_state == "confirmed",
            }
        )
        return rule

    @classmethod
    def m_create_sale_order(
        cls,
        user=None,
        company=None,
        partner=None,
        product=None,
        qty=2.0,
        price=125.0,
        extra_lines=None,
    ):
        user = user or cls.m_sync_user
        company = company or cls.company_a
        partner = partner or cls.company_b.partner_id
        product = product or cls.m_shared_product
        extra_lines = extra_lines or []
        pricelist = partner.with_company(company).property_product_pricelist
        order_line = [
            Command.create(
                {
                    "name": product.display_name,
                    "product_id": product.id,
                    "product_uom_id": product.uom_id.id,
                    "product_uom_qty": qty,
                    "price_unit": price,
                }
            )
        ] + extra_lines
        return (
            cls.env["sale.order"]
            .with_user(user)
            .with_company(company)
            .with_context(allowed_company_ids=[company.id, cls.company_b.id])
            .create(
                {
                    "company_id": company.id,
                    "partner_id": partner.id,
                    "pricelist_id": pricelist.id if pricelist else False,
                    "order_line": order_line,
                    "commitment_date": fields.Datetime.now(),
                }
            )
        )

    @classmethod
    def m_create_purchase_order(
        cls,
        user=None,
        company=None,
        partner=None,
        product=None,
        qty=2.0,
        price=125.0,
        extra_lines=None,
    ):
        user = user or cls.m_sync_user
        company = company or cls.company_b
        partner = partner or cls.company_a.partner_id
        product = product or cls.m_shared_product
        extra_lines = extra_lines or []
        order_line = [
            Command.create(
                {
                    "name": product.display_name,
                    "product_id": product.id,
                    "product_uom_id": product.uom_id.id,
                    "product_qty": qty,
                    "price_unit": price,
                    "date_planned": fields.Datetime.now(),
                }
            )
        ] + extra_lines
        return (
            cls.env["purchase.order"]
            .with_user(user)
            .with_company(company)
            .with_context(allowed_company_ids=[cls.company_a.id, company.id])
            .create(
                {
                    "company_id": company.id,
                    "partner_id": partner.id,
                    "currency_id": company.currency_id.id,
                    "order_line": order_line,
                }
            )
        )
