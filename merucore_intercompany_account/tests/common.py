from odoo import Command

from odoo.addons.merucore_intercompany_base.tests.common import IntercompanyTestCommon


class IntercompanyAccountCommon(IntercompanyTestCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.group_account_user = cls.env.ref("account.group_account_user")
        cls.group_account_manager = cls.env.ref("account.group_account_manager")

        cls.env["account.chart.template"].try_loading("generic_coa", company=cls.company_a, install_demo=False)
        cls.env["account.chart.template"].try_loading("generic_coa", company=cls.company_b, install_demo=False)

        cls.m_account_manager = cls.env["res.users"].create(
            {
                "name": "Intercompany Account Manager",
                "login": "intercompany_account_manager",
                "email": "intercompany.account.manager@example.com",
                "company_id": cls.company_a.id,
                "company_ids": [Command.set([cls.company_a.id, cls.company_b.id])],
                "group_ids": [
                    Command.set(
                        [
                            cls.base_group_user.id,
                            cls.group_manager.id,
                            cls.group_account_user.id,
                            cls.group_account_manager.id,
                        ]
                    )
                ],
            }
        )

        cls.company_a.m_intercompany_default_responsible_user_id = cls.m_account_manager
        cls.company_b.m_intercompany_default_responsible_user_id = cls.m_account_manager

        cls.receivable_a = cls.m_find_account(cls.company_a, [("account_type", "=", "asset_receivable")])
        cls.payable_a = cls.m_find_account(cls.company_a, [("account_type", "=", "liability_payable")])
        cls.revenue_a = cls.m_find_account(cls.company_a, [("internal_group", "=", "income")])
        cls.expense_a = cls.m_find_account(cls.company_a, [("internal_group", "=", "expense")])
        cls.receivable_b = cls.m_find_account(cls.company_b, [("account_type", "=", "asset_receivable")])
        cls.payable_b = cls.m_find_account(cls.company_b, [("account_type", "=", "liability_payable")])
        cls.revenue_b = cls.m_find_account(cls.company_b, [("internal_group", "=", "income")])
        cls.expense_b = cls.m_find_account(cls.company_b, [("internal_group", "=", "expense")])

        cls.sale_journal_a = cls.m_find_journal(cls.company_a, "sale")
        cls.purchase_journal_a = cls.m_find_journal(cls.company_a, "purchase")
        cls.sale_journal_b = cls.m_find_journal(cls.company_b, "sale")
        cls.purchase_journal_b = cls.m_find_journal(cls.company_b, "purchase")

        cls.company_b.partner_id.with_company(cls.company_a).write(
            {
                "property_account_receivable_id": cls.receivable_a.id,
                "property_account_payable_id": cls.payable_a.id,
            }
        )
        cls.company_a.partner_id.with_company(cls.company_b).write(
            {
                "property_account_receivable_id": cls.receivable_b.id,
                "property_account_payable_id": cls.payable_b.id,
            }
        )

    @classmethod
    def m_find_account(cls, company, extra_domain):
        return (
            cls.env["account.account"]
            .with_company(company)
            .search([("company_ids", "in", [company.id])] + extra_domain, order="id", limit=1)
        )

    @classmethod
    def m_find_journal(cls, company, journal_type):
        return cls.env["account.journal"].search(
            [("company_id", "=", company.id), ("type", "=", journal_type)],
            order="sequence, id",
            limit=1,
        )

    @classmethod
    def m_create_account_rule(cls, **overrides):
        responsible_user = overrides.pop("responsible_user", cls.m_account_manager)
        rule = cls.m_create_rule(
            name=overrides.pop("name", "Account Rule A -> B"),
            responsible_user=responsible_user,
        )
        values = {
            "m_account_sync_enabled": True,
            "m_account_workflow": "manual_documents",
            "m_trigger_document": "both",
            "m_counterpart_creation_timing": "manual",
            "m_counterpart_document_state": "draft",
            "m_sync_direction": "source_to_destination",
            "m_journal_strategy": "configured_journal",
            "m_source_sale_journal_id": cls.sale_journal_a.id,
            "m_source_purchase_journal_id": cls.purchase_journal_a.id,
            "m_destination_sale_journal_id": cls.sale_journal_b.id,
            "m_destination_purchase_journal_id": cls.purchase_journal_b.id,
            "m_responsible_account_user_id": cls.m_account_manager.id,
        }
        values.update(overrides)
        rule.with_user(cls.m_account_manager).with_context(allowed_company_ids=cls.allowed_pair_ids).write(values)
        return rule

    @classmethod
    def m_create_invoice(cls, company, partner, account, move_type="out_invoice", amount=100.0):
        return (
            cls.env["account.move"]
            .with_user(cls.m_account_manager)
            .with_company(company)
            .with_context(allowed_company_ids=cls.allowed_pair_ids)
            .create(
                {
                    "move_type": move_type,
                    "company_id": company.id,
                    "partner_id": partner.id,
                    "invoice_line_ids": [
                        Command.create(
                            {
                                "name": f"Intercompany {move_type}",
                                "account_id": account.id,
                                "quantity": 1.0,
                                "price_unit": amount,
                            }
                        )
                    ],
                }
            )
        )
