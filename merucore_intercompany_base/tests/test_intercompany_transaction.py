from odoo import tests
from odoo.exceptions import AccessError, ValidationError

from .common import IntercompanyTestCommon


@tests.tagged("post_install", "-at_install")
class TestIntercompanyTransaction(IntercompanyTestCommon):
    def test_transaction_sequence_rule_matching_and_idempotency(self):
        rule = self.m_create_rule()
        transaction = self.m_create_transaction(rule=rule, reference="SEQ-001")
        self.assertTrue(transaction.m_name.startswith("ICT/"))
        self.assertEqual(transaction.m_state, "draft")

        with self.assertRaises(ValidationError):
            self.m_create_transaction(
                rule=rule,
                reference="MISMATCH",
                source=self.company_b,
                destination=self.company_a,
            )

        self.m_create_transaction(rule=rule, reference="IDEMP-1", idempotency_key="dup-key")
        with self.assertRaises(ValidationError):
            self.m_create_transaction(rule=rule, reference="IDEMP-2", idempotency_key="dup-key")

    def test_state_actions_event_logging_and_deletion_protection(self):
        rule = self.m_create_rule(name="State Rule")
        transaction = self.m_create_transaction(rule=rule, reference="STATE-001")

        transaction.with_user(self.user_both).with_context(allowed_company_ids=self.allowed_pair_ids).m_action_start()
        self.assertEqual(transaction.m_state, "in_progress")
        self.assertTrue(
            transaction.m_event_ids.filtered(lambda event: event.m_event_type == "state_change")
        )

        transaction.with_user(self.user_both).with_context(allowed_company_ids=self.allowed_pair_ids).m_action_mark_done()
        self.assertEqual(transaction.m_state, "done")
        self.assertEqual(transaction.m_health_state, "healthy")

        cancel_transaction = self.m_create_transaction(rule=rule, reference="STATE-002")
        cancel_transaction.with_user(self.user_both).with_context(allowed_company_ids=self.allowed_pair_ids).m_action_cancel()
        self.assertEqual(cancel_transaction.m_state, "cancelled")

        with self.assertRaises(ValidationError):
            transaction.sudo().unlink()

    def test_event_immutability_resolution_and_health_transitions(self):
        rule = self.m_create_rule(name="Event Rule")
        transaction = self.m_create_transaction(rule=rule, reference="EVENT-001")

        event = transaction.m_log_event(
            m_event_type="warning",
            m_summary="Manual warning event",
            m_message="A warning was logged for testing.",
            m_technical_details="manager-only technical note",
        )

        self.assertTrue(event)
        self.assertEqual(transaction.m_event_count, 2)

        with self.assertRaises(AccessError):
            self.env["merucore.intercompany.event"].with_user(self.user_both).create(
                {
                    "m_transaction_id": transaction.id,
                    "m_company_id": self.company_a.id,
                    "m_event_type": "info",
                    "m_summary": "Forbidden",
                }
            )

        with self.assertRaises(AccessError):
            event.with_user(self.manager_both).write({"m_summary": "Changed"})

        transaction.m_mark_warning("Transaction warning", "warning details")
        self.assertEqual(transaction.m_health_state, "warning")
        self.assertTrue(transaction.m_has_open_issue)

        transaction.m_mark_failed("Transaction failure", "failure details")
        self.assertEqual(transaction.m_health_state, "failed")

        failure_event = transaction.m_event_ids.filtered(lambda current: current.m_event_type == "error")[:1]
        failure_event.with_user(self.manager_both).with_context(
            allowed_company_ids=self.allowed_pair_ids
        ).m_action_resolve()
        self.assertTrue(failure_event.m_resolved)
        self.assertEqual(failure_event.m_resolved_by_id, self.manager_both)

        failure_event.with_user(self.manager_both).with_context(
            allowed_company_ids=self.allowed_pair_ids
        ).m_action_reopen()
        self.assertFalse(failure_event.m_resolved)

        transaction.m_mark_healthy("Healthy again", "Issue cleared")
        self.assertEqual(transaction.m_health_state, "healthy")
        self.assertFalse(transaction.m_has_open_issue)
