from odoo import tests
from odoo.exceptions import ValidationError

from .common import IntercompanyTestCommon


@tests.tagged("post_install", "-at_install")
class TestIntercompanyRule(IntercompanyTestCommon):
    def test_rule_creation_and_validation(self):
        rule = self.m_create_rule()
        self.assertEqual(rule.m_source_company_id, self.company_a)
        self.assertEqual(rule.m_destination_company_id, self.company_b)

        with self.assertRaises(ValidationError):
            self.m_create_rule(name="Invalid Same Company", source=self.company_a, destination=self.company_a)

        with self.assertRaises(ValidationError):
            self.m_create_rule(name="Duplicate Pair")

        reverse_rule = self.m_create_rule(
            name="Rule B -> A",
            source=self.company_b,
            destination=self.company_a,
        )
        self.assertEqual(reverse_rule.m_source_company_id, self.company_b)
        self.assertEqual(reverse_rule.m_destination_company_id, self.company_a)

        with self.assertRaises(ValidationError):
            self.m_create_rule(
                name="Negative Retry",
                source=self.company_a,
                destination=self.company_c,
                responsible_user=False,
                max_retry_count=-1,
            )

        with self.assertRaises(ValidationError):
            self.m_create_rule(
                name="Negative Delay",
                source=self.company_b,
                destination=self.company_c,
                responsible_user=False,
                retry_delay_minutes=-5,
            )

    def test_rule_deletion_protection_when_transactions_exist(self):
        rule = self.m_create_rule(name="Protected Rule")
        self.m_create_transaction(rule=rule, reference="RULE-PROTECT")
        with self.assertRaises(ValidationError):
            rule.with_user(self.manager_both).unlink()
