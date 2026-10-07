from odoo import tests
from odoo.exceptions import AccessError

from .common import IntercompanyTestCommon


@tests.tagged("post_install", "-at_install")
class TestIntercompanySecurity(IntercompanyTestCommon):
    def test_dual_company_visibility_and_manager_boundaries(self):
        rule = self.m_create_rule(name="Security Rule")
        transaction = self.m_create_transaction(rule=rule, reference="SEC-001")
        event = transaction.m_log_event(
            m_event_type="warning",
            m_summary="Security visibility warning",
            m_message="Visibility should follow both companies.",
            m_technical_details="restricted field",
        )

        visible_transaction = (
            self.env["merucore.intercompany.transaction"]
            .with_user(self.user_both)
            .with_context(allowed_company_ids=self.allowed_pair_ids)
            .search([("id", "=", transaction.id)])
        )
        self.assertEqual(visible_transaction, transaction)

        hidden_for_single_company = (
            self.env["merucore.intercompany.transaction"]
            .with_user(self.user_a_only)
            .with_context(allowed_company_ids=[self.company_a.id])
            .search([("id", "=", transaction.id)])
        )
        self.assertFalse(hidden_for_single_company)

        hidden_for_single_company_manager = (
            self.env["merucore.intercompany.transaction"]
            .with_user(self.manager_a_only)
            .with_context(allowed_company_ids=[self.company_a.id])
            .search([("id", "=", transaction.id)])
        )
        self.assertFalse(hidden_for_single_company_manager)

        visible_event = (
            self.env["merucore.intercompany.event"]
            .with_user(self.user_both)
            .with_context(allowed_company_ids=self.allowed_pair_ids)
            .search([("id", "=", event.id)])
        )
        self.assertEqual(visible_event, event)

    def test_regular_user_field_restrictions_and_delete_permissions(self):
        rule = self.m_create_rule(name="Restricted Field Rule")
        transaction = self.m_create_transaction(rule=rule, reference="SEC-002")
        event = transaction.m_log_event(
            m_event_type="error",
            m_summary="Sensitive event",
            m_message="Restricted details are present.",
            m_technical_details="sensitive technical payload",
        )

        with self.assertRaises(AccessError):
            event.with_user(self.user_both).read(["m_technical_details"])

        with self.assertRaises(AccessError):
            self.env["merucore.intercompany.event"].with_user(self.user_both).search_fetch(
                [("id", "=", event.id)],
                ["m_technical_details"],
            )

        manager_read = event.with_user(self.manager_both).read(["m_technical_details"])
        self.assertEqual(manager_read[0]["m_technical_details"], "sensitive technical payload")

        with self.assertRaises(AccessError):
            transaction.with_user(self.user_both).unlink()

        with self.assertRaises(AccessError):
            event.with_user(self.user_both).unlink()
