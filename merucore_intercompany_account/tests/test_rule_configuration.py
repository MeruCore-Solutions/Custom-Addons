from odoo import tests
from odoo.exceptions import ValidationError

from .common import IntercompanyAccountCommon


@tests.tagged("post_install", "-at_install")
class TestIntercompanyAccountRule(IntercompanyAccountCommon):
    def test_find_applicable_rule_and_trigger_direction(self):
        rule = self.m_create_account_rule()

        invoice = self.m_create_invoice(
            company=self.company_a,
            partner=self.company_b.partner_id,
            account=self.revenue_a,
            move_type="out_invoice",
        )
        bill = self.m_create_invoice(
            company=self.company_b,
            partner=self.company_a.partner_id,
            account=self.expense_b,
            move_type="in_invoice",
        )

        self.assertEqual(invoice.m_find_applicable_intercompany_rule(), rule)
        self.assertTrue(rule.m_allows_account_trigger(invoice))
        self.assertFalse(rule.m_allows_account_trigger(bill))

        rule.with_user(self.m_account_manager).write({"m_sync_direction": "bidirectional"})
        self.assertEqual(bill.m_find_applicable_intercompany_rule(), rule)
        self.assertTrue(rule.m_allows_account_trigger(bill))

    def test_rule_requires_responsible_user_for_posted_automation(self):
        rule = self.m_create_rule(name="No Accounting User Rule", responsible_user=False)

        with self.assertRaises(ValidationError):
            rule.with_user(self.m_account_manager).with_context(allowed_company_ids=self.allowed_pair_ids).write(
                {
                    "m_account_sync_enabled": True,
                    "m_counterpart_document_state": "posted",
                    "m_journal_strategy": "configured_journal",
                    "m_source_sale_journal_id": self.sale_journal_a.id,
                    "m_source_purchase_journal_id": self.purchase_journal_a.id,
                    "m_destination_sale_journal_id": self.sale_journal_b.id,
                    "m_destination_purchase_journal_id": self.purchase_journal_b.id,
                    "m_responsible_account_user_id": False,
                }
            )

    def test_rule_rejects_wrong_journal_type(self):
        rule = self.m_create_rule(name="Wrong Journal Type Rule", responsible_user=self.m_account_manager)

        with self.assertRaises(ValidationError):
            rule.with_user(self.m_account_manager).with_context(allowed_company_ids=self.allowed_pair_ids).write(
                {
                    "m_account_sync_enabled": True,
                    "m_source_sale_journal_id": self.purchase_journal_a.id,
                }
            )

    def test_rule_returns_configured_journals(self):
        rule = self.m_create_account_rule()

        self.assertEqual(
            rule.m_get_account_journal_for_company(self.company_a, "out_invoice"),
            self.sale_journal_a,
        )
        self.assertEqual(
            rule.m_get_account_journal_for_company(self.company_b, "in_invoice"),
            self.purchase_journal_b,
        )
