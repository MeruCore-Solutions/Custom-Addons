from odoo import fields, tests
from odoo.exceptions import UserError

from .common import IntercompanyTestCommon


@tests.tagged("post_install", "-at_install")
class TestIntercompanyRetry(IntercompanyTestCommon):
    def test_manual_retry_without_handler_and_maximum_retry(self):
        rule = self.m_create_rule(
            name="Retry Rule",
            auto_retry=True,
            max_retry_count=1,
            retry_delay_minutes=10,
        )
        transaction = self.m_create_transaction(rule=rule, reference="RETRY-001")
        transaction.m_mark_failed("Initial failure", "Ready for retry")

        transaction.with_user(self.manager_both).with_context(
            allowed_company_ids=self.allowed_pair_ids
        ).m_execute_retry(m_manager_note="First retry")

        self.assertEqual(transaction.m_retry_count, 1)
        self.assertEqual(transaction.m_health_state, "warning")
        self.assertNotEqual(transaction.m_state, "done")
        self.assertTrue(
            transaction.m_event_ids.filtered(lambda event: event.m_event_type == "retry")
        )

        with self.assertRaises(UserError):
            transaction.with_user(self.manager_both).with_context(
                allowed_company_ids=self.allowed_pair_ids
            ).m_execute_retry(m_manager_note="Second retry")

        wizard = (
            self.env["merucore.intercompany.retry.wizard"]
            .with_user(self.manager_both)
            .with_context(allowed_company_ids=self.allowed_pair_ids)
            .create(
                {
                    "m_transaction_id": transaction.id,
                    "m_manager_note": "Forced retry",
                    "m_force_retry": True,
                }
            )
        )
        wizard.m_action_retry()
        self.assertEqual(transaction.m_retry_count, 2)

    def test_cron_respects_due_date_batch_limit_and_survives_failures(self):
        rule = self.m_create_rule(
            name="Cron Retry Rule",
            auto_retry=True,
            max_retry_count=5,
            retry_delay_minutes=5,
        )
        tx1 = self.m_create_transaction(rule=rule, reference="CRON-001")
        tx2 = self.m_create_transaction(rule=rule, reference="CRON-002")
        tx3 = self.m_create_transaction(rule=rule, reference="CRON-003")

        for transaction in (tx1, tx2, tx3):
            transaction.with_context(m_intercompany_internal_write=True).write(
                {
                    "m_next_retry_at": fields.Datetime.now(),
                    "m_health_state": "failed",
                }
            )
        tx3.with_context(m_intercompany_internal_write=True).write(
            {"m_next_retry_at": fields.Datetime.add(fields.Datetime.now(), hours=2)}
        )

        transaction_model_class = type(self.env["merucore.intercompany.transaction"])
        original_execute_retry = transaction_model_class.m_execute_retry

        def patched_execute_retry(recordset, *args, **kwargs):
            if len(recordset) == 1 and recordset.id == tx1.id:
                raise RuntimeError("forced cron failure")
            return original_execute_retry(recordset, *args, **kwargs)

        self.patch(transaction_model_class, "m_execute_retry", patched_execute_retry)

        processed = (
            self.env["merucore.intercompany.transaction"]
            .with_user(self.manager_both)
            .with_context(allowed_company_ids=self.allowed_pair_ids)
            .m_cron_process_retry_batch(m_batch_size=2)
        )

        self.assertEqual(processed, 2)
        self.assertEqual(tx1.m_health_state, "failed")
        self.assertEqual(tx2.m_retry_count, 1)
        self.assertEqual(tx3.m_retry_count, 0)
