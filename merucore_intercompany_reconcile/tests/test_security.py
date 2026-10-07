from .common import IntercompanyReconcileCommon


class TestIntercompanyReconcileSecurity(IntercompanyReconcileCommon):
    def test_single_company_user_cannot_see_dual_company_match(self):
        rule = self.m_create_reconcile_rule()
        invoice, bill = self.m_create_intercompany_documents(amount=99.0)
        match = self.m_create_match(rule, invoice, bill)

        visible_match = (
            self.env["merucore.intercompany.match"]
            .with_user(self.user_a_only)
            .with_context(allowed_company_ids=[self.company_a.id])
            .search([("id", "=", match.id)])
        )

        self.assertFalse(visible_match)
