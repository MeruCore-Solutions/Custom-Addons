from odoo import tests
from odoo.exceptions import ValidationError

from .common import IntercompanyAccountCommon


@tests.tagged("post_install", "-at_install")
class TestIntercompanyAccountMappings(IntercompanyAccountCommon):
    def test_account_mapping_blocks_receivable_and_payable_accounts(self):
        rule = self.m_create_account_rule()

        with self.assertRaises(ValidationError):
            self.env["merucore.intercompany.account.mapping"].create(
                {
                    "m_name": "Blocked Receivable Mapping",
                    "m_rule_id": rule.id,
                    "m_source_account_id": self.receivable_a.id,
                    "m_destination_account_id": self.expense_b.id,
                    "m_move_scope": "sale",
                }
            )

        with self.assertRaises(ValidationError):
            self.env["merucore.intercompany.account.mapping"].create(
                {
                    "m_name": "Blocked Payable Mapping",
                    "m_rule_id": rule.id,
                    "m_source_account_id": self.expense_a.id,
                    "m_destination_account_id": self.payable_b.id,
                    "m_move_scope": "purchase",
                }
            )

    def test_account_mapping_enforces_unique_active_scope(self):
        rule = self.m_create_account_rule()

        self.env["merucore.intercompany.account.mapping"].create(
            {
                "m_name": "Primary Sales Mapping",
                "m_rule_id": rule.id,
                "m_source_account_id": self.revenue_a.id,
                "m_destination_account_id": self.expense_b.id,
                "m_move_scope": "sale",
            }
        )

        with self.assertRaises(ValidationError):
            self.env["merucore.intercompany.account.mapping"].create(
                {
                    "m_name": "Duplicate Sales Mapping",
                    "m_rule_id": rule.id,
                    "m_source_account_id": self.revenue_a.id,
                    "m_destination_account_id": self.revenue_b.id,
                    "m_move_scope": "sale",
                }
            )

    def test_account_mapping_enforces_company_pair(self):
        rule = self.m_create_account_rule()

        with self.assertRaises(ValidationError):
            self.env["merucore.intercompany.account.mapping"].create(
                {
                    "m_name": "Wrong Destination Company Mapping",
                    "m_rule_id": rule.id,
                    "m_source_account_id": self.revenue_a.id,
                    "m_destination_account_id": self.expense_a.id,
                    "m_move_scope": "all",
                }
            )
