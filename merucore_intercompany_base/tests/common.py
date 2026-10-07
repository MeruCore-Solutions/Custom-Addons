from odoo import Command
from odoo.tests import TransactionCase


class IntercompanyTestCommon(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.group_user = cls.env.ref("merucore_intercompany_base.m_group_intercompany_user")
        cls.group_manager = cls.env.ref("merucore_intercompany_base.m_group_intercompany_manager")
        cls.base_group_user = cls.env.ref("base.group_user")

        cls.company_a = cls.env["res.company"].create({"name": "Intercompany A"})
        cls.company_b = cls.env["res.company"].create({"name": "Intercompany B"})
        cls.company_c = cls.env["res.company"].create({"name": "Intercompany C"})

        cls.user_both = cls.env["res.users"].create(
            {
                "name": "Intercompany Pair User",
                "login": "intercompany_pair_user",
                "email": "pair.user@example.com",
                "company_id": cls.company_a.id,
                "company_ids": [Command.set([cls.company_a.id, cls.company_b.id])],
                "group_ids": [Command.set([cls.base_group_user.id, cls.group_user.id])],
            }
        )
        cls.user_a_only = cls.env["res.users"].create(
            {
                "name": "Intercompany A User",
                "login": "intercompany_a_only",
                "email": "a.only@example.com",
                "company_id": cls.company_a.id,
                "company_ids": [Command.set([cls.company_a.id])],
                "group_ids": [Command.set([cls.base_group_user.id, cls.group_user.id])],
            }
        )
        cls.manager_both = cls.env["res.users"].create(
            {
                "name": "Intercompany Pair Manager",
                "login": "intercompany_pair_manager",
                "email": "pair.manager@example.com",
                "company_id": cls.company_a.id,
                "company_ids": [Command.set([cls.company_a.id, cls.company_b.id])],
                "group_ids": [Command.set([cls.base_group_user.id, cls.group_manager.id])],
            }
        )
        cls.manager_all = cls.env["res.users"].create(
            {
                "name": "Intercompany All Companies Manager",
                "login": "intercompany_all_manager",
                "email": "all.manager@example.com",
                "company_id": cls.company_a.id,
                "company_ids": [Command.set([cls.company_a.id, cls.company_b.id, cls.company_c.id])],
                "group_ids": [Command.set([cls.base_group_user.id, cls.group_manager.id])],
            }
        )
        cls.manager_a_only = cls.env["res.users"].create(
            {
                "name": "Intercompany A Manager",
                "login": "intercompany_a_manager",
                "email": "a.manager@example.com",
                "company_id": cls.company_a.id,
                "company_ids": [Command.set([cls.company_a.id])],
                "group_ids": [Command.set([cls.base_group_user.id, cls.group_manager.id])],
            }
        )

        cls.company_a.m_intercompany_enabled = True
        cls.company_b.m_intercompany_enabled = True
        cls.company_a.m_intercompany_default_responsible_user_id = cls.user_both
        cls.company_b.m_intercompany_default_responsible_user_id = cls.user_both

        cls.allowed_pair_ids = [cls.company_a.id, cls.company_b.id]

    @classmethod
    def m_create_rule(
        cls,
        name="Rule A -> B",
        source=None,
        destination=None,
        responsible_user=None,
        auto_retry=False,
        max_retry_count=3,
        retry_delay_minutes=15,
        notify_on_warning=True,
        notify_on_failure=True,
    ):
        source = source or cls.company_a
        destination = destination or cls.company_b
        if responsible_user is None:
            responsible_user = cls.user_both
        return (
            cls.env["merucore.intercompany.rule"]
            .with_user(cls.manager_all)
            .with_context(allowed_company_ids=[source.id, destination.id])
            .create(
                {
                    "m_name": name,
                    "m_source_company_id": source.id,
                    "m_destination_company_id": destination.id,
                    "m_responsible_user_id": responsible_user.id if responsible_user else False,
                    "m_auto_retry": auto_retry,
                    "m_max_retry_count": max_retry_count,
                    "m_retry_delay_minutes": retry_delay_minutes,
                    "m_notify_on_warning": notify_on_warning,
                    "m_notify_on_failure": notify_on_failure,
                }
            )
        )

    @classmethod
    def m_create_transaction(
        cls,
        rule,
        reference="TX-REF-001",
        source=None,
        destination=None,
        idempotency_key=False,
        source_model=False,
        source_res_id=False,
        destination_model=False,
        destination_res_id=False,
        responsible_user=None,
        user=None,
    ):
        user = user or cls.user_both
        source = source or rule.m_source_company_id
        destination = destination or rule.m_destination_company_id
        responsible_user = responsible_user or rule.m_responsible_user_id or cls.user_both
        return (
            cls.env["merucore.intercompany.transaction"]
            .with_user(user)
            .with_context(allowed_company_ids=[source.id, destination.id])
            .create(
                {
                    "m_rule_id": rule.id,
                    "m_source_company_id": source.id,
                    "m_destination_company_id": destination.id,
                    "m_reference": reference,
                    "m_idempotency_key": idempotency_key,
                    "m_source_model": source_model,
                    "m_source_res_id": source_res_id,
                    "m_destination_model": destination_model,
                    "m_destination_res_id": destination_res_id,
                    "m_responsible_user_id": responsible_user.id,
                }
            )
        )
