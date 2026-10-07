from odoo import Command, fields
from odoo.tests import tagged

from odoo.addons.merucore_intercompany_base.tests.common import IntercompanyTestCommon


@tagged("post_install", "-at_install")
class IntercompanyReconcileCommon(IntercompanyTestCommon):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.group_account_manager = cls.env.ref("account.group_account_manager")
        cls.group_account_user = cls.env.ref("account.group_account_user")

        cls.env["account.chart.template"].try_loading("generic_coa", company=cls.company_a, install_demo=False)
        cls.env["account.chart.template"].try_loading("generic_coa", company=cls.company_b, install_demo=False)

        cls.m_reconcile_manager = cls.env["res.users"].create(
            {
                "name": "Intercompany Reconcile Manager",
                "login": "intercompany_reconcile_manager",
                "email": "intercompany.reconcile.manager@example.com",
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

        cls.receivable_a = cls.m_find_account(cls.company_a, [("account_type", "=", "asset_receivable")])
        cls.payable_a = cls.m_find_account(cls.company_a, [("account_type", "=", "liability_payable")])
        cls.revenue_a = cls.m_find_account(cls.company_a, [("internal_group", "=", "income")])
        cls.expense_a = cls.m_find_account(cls.company_a, [("internal_group", "=", "expense")])
        cls.receivable_b = cls.m_find_account(cls.company_b, [("account_type", "=", "asset_receivable")])
        cls.payable_b = cls.m_find_account(cls.company_b, [("account_type", "=", "liability_payable")])
        cls.revenue_b = cls.m_find_account(cls.company_b, [("internal_group", "=", "income")])
        cls.expense_b = cls.m_find_account(cls.company_b, [("internal_group", "=", "expense")])

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

        cls.source_due_from_account = cls.m_create_reconcile_account(
            cls.company_a,
            "MCIDFA",
            "Intercompany Due From A",
            "asset_current",
        )
        cls.source_due_to_account = cls.m_create_reconcile_account(
            cls.company_a,
            "MCIDTA",
            "Intercompany Due To A",
            "liability_current",
        )
        cls.destination_due_from_account = cls.m_create_reconcile_account(
            cls.company_b,
            "MCIDFB",
            "Intercompany Due From B",
            "asset_current",
        )
        cls.destination_due_to_account = cls.m_create_reconcile_account(
            cls.company_b,
            "MCIDTB",
            "Intercompany Due To B",
            "liability_current",
        )

        cls.general_journal_a = cls.env["account.journal"].search(
            [("company_id", "=", cls.company_a.id), ("type", "=", "general")],
            order="sequence, id",
            limit=1,
        )
        cls.general_journal_b = cls.env["account.journal"].search(
            [("company_id", "=", cls.company_b.id), ("type", "=", "general")],
            order="sequence, id",
            limit=1,
        )

    @classmethod
    def m_find_account(cls, company, extra_domain):
        return (
            cls.env["account.account"]
            .with_company(company)
            .search([("company_ids", "in", [company.id])] + extra_domain, order="id", limit=1)
        )

    @classmethod
    def m_create_reconcile_account(cls, company, code, name, account_type):
        return (
            cls.env["account.account"]
            .with_company(company)
            .create(
                {
                    "name": name,
                    "code": code,
                    "account_type": account_type,
                    "reconcile": True,
                    "company_ids": [Command.set([company.id])],
                }
            )
        )

    @classmethod
    def m_create_reconcile_rule(cls):
        rule = cls.m_create_rule(
            name="Reconcile Rule A -> B",
            responsible_user=cls.m_reconcile_manager,
        )
        rule.with_user(cls.manager_all).with_context(allowed_company_ids=cls.allowed_pair_ids).write(
            {
                "m_reconcile_enabled": True,
                "m_matching_strategy": "manual_only",
                "m_match_date_tolerance_days": 7,
                "m_match_amount_tolerance": 0.0,
                "m_match_residual_only": True,
                "m_settlement_strategy": "bilateral_clearing",
                "m_allow_partial_settlement": True,
                "m_allow_cross_currency_settlement": False,
                "m_source_clearing_journal_id": cls.general_journal_a.id,
                "m_destination_clearing_journal_id": cls.general_journal_b.id,
                "m_source_due_to_account_id": cls.source_due_to_account.id,
                "m_source_due_from_account_id": cls.source_due_from_account.id,
                "m_destination_due_to_account_id": cls.destination_due_to_account.id,
                "m_destination_due_from_account_id": cls.destination_due_from_account.id,
                "m_require_dual_approval": True,
                "m_source_approver_ids": [Command.set([cls.m_reconcile_manager.id])],
                "m_destination_approver_ids": [Command.set([cls.m_reconcile_manager.id])],
                "m_responsible_treasury_user_id": cls.m_reconcile_manager.id,
            }
        )
        return rule

    @classmethod
    def m_create_intercompany_documents(cls, amount=100.0, invoice_date=False):
        invoice_date = invoice_date or fields.Date.from_string("2026-08-24")
        invoice = (
            cls.env["account.move"]
            .with_company(cls.company_a)
            .with_context(allowed_company_ids=cls.allowed_pair_ids)
            .create(
                {
                    "move_type": "out_invoice",
                    "company_id": cls.company_a.id,
                    "partner_id": cls.company_b.partner_id.id,
                    "invoice_date": invoice_date,
                    "invoice_line_ids": [
                        Command.create(
                            {
                                "name": "Intercompany Sale",
                                "account_id": cls.revenue_a.id,
                                "quantity": 1.0,
                                "price_unit": amount,
                            }
                        )
                    ],
                }
            )
        )
        invoice.action_post()

        bill = (
            cls.env["account.move"]
            .with_company(cls.company_b)
            .with_context(allowed_company_ids=cls.allowed_pair_ids)
            .create(
                {
                    "move_type": "in_invoice",
                    "company_id": cls.company_b.id,
                    "partner_id": cls.company_a.partner_id.id,
                    "invoice_date": invoice_date,
                    "invoice_line_ids": [
                        Command.create(
                            {
                                "name": "Intercompany Purchase",
                                "account_id": cls.expense_b.id,
                                "quantity": 1.0,
                                "price_unit": amount,
                            }
                        )
                    ],
                }
            )
        )
        bill.action_post()
        return invoice, bill

    @classmethod
    def m_create_match(cls, rule, invoice, bill, transaction=False):
        transaction = transaction or cls.m_create_transaction(
            rule,
            reference=f"{invoice.name}/{bill.name}",
            source_model="account.move",
            source_res_id=invoice.id,
            destination_model="account.move",
            destination_res_id=bill.id,
            responsible_user=cls.m_reconcile_manager,
            user=cls.m_reconcile_manager,
        )
        return (
            cls.env["merucore.intercompany.match"]
            .with_user(cls.m_reconcile_manager)
            .with_context(allowed_company_ids=cls.allowed_pair_ids)
            .create(
                {
                    "m_rule_id": rule.id,
                    "m_transaction_id": transaction.id,
                    "m_source_move_id": invoice.id,
                    "m_destination_move_id": bill.id,
                }
            )
        )
