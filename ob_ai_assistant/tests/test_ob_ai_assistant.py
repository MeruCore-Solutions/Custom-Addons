import base64
import json
from unittest.mock import patch

from dateutil.relativedelta import relativedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


class MockResponse:

    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
        self.text = json.dumps(payload)

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


@tagged("post_install", "-at_install")
class TestObAIAssistant(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.provider_openai = cls.env.ref("ob_ai_assistant.ob_ai_provider_openai")
        cls.provider_anthropic = cls.env.ref("ob_ai_assistant.ob_ai_provider_anthropic")
        cls.model_openai = cls.env.ref("ob_ai_assistant.ob_ai_model_openai_gpt54mini")
        cls.model_anthropic = cls.env.ref("ob_ai_assistant.ob_ai_model_anthropic_sonnet4")
        cls.ai_user_group = cls.env.ref("ob_ai_assistant.group_ai_user")
        partner_model = cls.env["ir.model"]._get("res.partner")
        field_ids = cls.env["ir.model.fields"].search([
            ("model_id", "=", partner_model.id),
            ("name", "in", ["name", "email", "phone"]),
        ])
        cls.allowed_partner_model = cls.env["ob.ai.allowed.model"].create({
            "name": "Partners",
            "model_id": partner_model.id,
            "allowed_field_ids": [(6, 0, field_ids.ids)],
            "blocked_field_ids": [(6, 0, field_ids.filtered(lambda field: field.name == "phone").ids)],
            "max_record_count": 3,
            "search_limit": 3,
            "reference_field_names": "name,email",
            "name_field_names": "name,email",
            "allow_document_context": True,
            "allow_activity_creation": True,
            "allow_reminder_creation": True,
            "allow_chatter_posting": True,
            "allow_dashboard_generation": True,
            "allow_validation": True,
        })
        cls.partner = cls.env["res.partner"].create({
            "name": "AI Test Customer",
            "email": "ai.customer@example.com",
            "phone": "+49 123 456 789",
        })
        params = cls.env["ir.config_parameter"].sudo()
        params.set_param("ob_ai_assistant.enabled", True)
        params.set_param("ob_ai_assistant.default_provider_id", cls.provider_openai.id)
        params.set_param("ob_ai_assistant.default_model_id", cls.model_openai.id)
        params.set_param("ob_ai_assistant.openai_api_key", "test-openai-key")
        params.set_param("ob_ai_assistant.anthropic_api_key", "test-anthropic-key")
        params.set_param("ob_ai_assistant.store_raw_payload", "False")
        params.set_param("ob_ai_assistant.shared_data_retention_days", 1095)
        params.set_param("ob_ai_assistant.allow_activity_creation", True)
        params.set_param("ob_ai_assistant.allow_reminder_creation", True)
        params.set_param("ob_ai_assistant.allow_chatter_posting", True)
        params.set_param("ob_ai_assistant.dashboard_enabled", True)
        params.set_param("ob_ai_assistant.validation_enabled", True)
        params.set_param("ob_ai_assistant.document_summary_enabled", True)
        params.set_param("ob_ai_assistant.generic_engine_enabled", True)
        params.set_param("ob_ai_assistant.schema_auto_refresh_enabled", True)
        params.set_param("ob_ai_assistant.semantic_auto_sync_enabled", True)
        params.set_param("ob_ai_assistant.request_token_ttl_minutes", 15)
        params.set_param("ob_ai_assistant.gateway_enabled", True)
        params.set_param("ob_ai_assistant.gateway_require_signature", True)
        params.set_param("ob_ai_assistant.gateway_max_clock_skew_seconds", 180)
        params.set_param("ob_ai_assistant.gateway_allow_action_scope", True)
        params.set_param("ob_ai_assistant.gateway_action_scope_admin_only", True)
        params.set_param("ob_ai_assistant.gateway_auto_action_scope", True)
        params.set_param("ob_ai_assistant.max_investigation_steps", 3)
        params.set_param("ob_ai_assistant.max_models_per_request", 6)
        params.set_param("ob_ai_assistant.max_records_per_fetch", 25)
        params.set_param("ob_ai_assistant.schema_snapshot_retention", 5)
        params.set_param("ob_ai_assistant.human_approval_required", "False")

    def _provider_payload(self, text, response_id="resp_ai_test"):
        return {
            "id": response_id,
            "output_text": text,
            "usage": {
                "input_tokens": 77,
                "output_tokens": 24,
            },
        }

    def test_openai_provider_service(self):
        payload = {
            "id": "resp_openai_1",
            "output_text": "OpenAI summary response",
            "usage": {
                "input_tokens": 55,
                "output_tokens": 18,
            },
        }
        with patch(
            "odoo.addons.ob_ai_assistant.services.ob_ai_provider_service.requests.post",
            return_value=MockResponse(payload),
        ) as mocked_post:
            result = self.env["ob.ai.provider.service"].generate_text(
                self.provider_openai,
                self.model_openai,
                "System prompt",
                [{"role": "user", "content": "Hello"}],
            )

        self.assertEqual(result["text"], "OpenAI summary response")
        self.assertEqual(result["provider_response_id"], "resp_openai_1")
        self.assertEqual(result["input_tokens"], 55)
        self.assertEqual(result["output_tokens"], 18)
        self.assertEqual(mocked_post.call_args.args[0], self.provider_openai.endpoint_url)
        self.assertFalse(mocked_post.call_args.kwargs["json"]["store"])
        self.assertEqual(mocked_post.call_args.kwargs["json"]["model"], self.model_openai.model_key)

    def test_config_parameter_setdefault_is_idempotent(self):
        params = self.env["ir.config_parameter"].sudo()
        key = "ob_ai_assistant.test_default_key"
        params.search([("key", "=", key)]).unlink()

        params.setdefault_param(key, "first")
        params.setdefault_param(key, "second")

        self.assertEqual(params.get_param(key), "first")
        self.assertEqual(params.search_count([("key", "=", key)]), 1)

    def test_settings_persist_false_boolean_flags(self):
        settings = self.env["res.config.settings"].create({
            "ai_human_approval_required": False,
            "ai_store_raw_payload": False,
            "ai_shared_data_retention_days": 730,
            "ai_allow_activity_creation": False,
            "ai_dashboard_enabled": False,
        })
        settings.set_values()
        params = self.env["ir.config_parameter"].sudo()

        self.assertEqual(params.get_param("ob_ai_assistant.human_approval_required"), "False")
        self.assertEqual(params.get_param("ob_ai_assistant.store_raw_payload"), "False")
        self.assertEqual(params.get_param("ob_ai_assistant.shared_data_retention_days"), "730")
        self.assertEqual(params.get_param("ob_ai_assistant.allow_activity_creation"), "False")
        self.assertEqual(params.get_param("ob_ai_assistant.dashboard_enabled"), "False")

    def test_audit_payload_cleanup_uses_shared_data_retention_days(self):
        params = self.env["ir.config_parameter"].sudo()
        params.set_param("ob_ai_assistant.store_raw_payload", "True")
        params.set_param("ob_ai_assistant.shared_data_retention_days", "1095")
        old_log = self.env["ob.ai.audit.log"].create({
            "request_kind": "chat",
            "status": "success",
            "context_payload": {"source": "old"},
            "request_payload": {"old": True},
            "response_payload": {"old": True},
            "input_stored": True,
            "output_stored": True,
        })
        fresh_log = self.env["ob.ai.audit.log"].create({
            "request_kind": "chat",
            "status": "success",
            "context_payload": {"source": "fresh"},
            "request_payload": {"fresh": True},
            "response_payload": {"fresh": True},
            "input_stored": True,
            "output_stored": True,
        })
        old_create_date = fields.Datetime.to_string(fields.Datetime.now() - relativedelta(days=1100))
        fresh_create_date = fields.Datetime.to_string(fields.Datetime.now() - relativedelta(days=10))
        self.env.cr.execute(
            "UPDATE ob_ai_audit_log SET create_date=%s WHERE id=%s",
            [old_create_date, old_log.id],
        )
        self.env.cr.execute(
            "UPDATE ob_ai_audit_log SET create_date=%s WHERE id=%s",
            [fresh_create_date, fresh_log.id],
        )
        self.env.invalidate_all()

        self.env["ob.ai.audit.log"]._cleanup_audit_payloads()

        self.env.invalidate_all()
        old_log = self.env["ob.ai.audit.log"].browse(old_log.id)
        fresh_log = self.env["ob.ai.audit.log"].browse(fresh_log.id)
        self.assertFalse(old_log.context_payload)
        self.assertFalse(old_log.request_payload)
        self.assertFalse(old_log.response_payload)
        self.assertFalse(old_log.input_stored)
        self.assertFalse(old_log.output_stored)
        self.assertTrue(fresh_log.context_payload)
        self.assertTrue(fresh_log.request_payload)
        self.assertTrue(fresh_log.response_payload)

    def test_anthropic_provider_service(self):
        payload = {
            "id": "msg_anthropic_1",
            "content": [{"type": "text", "text": "Claude summary response"}],
            "usage": {
                "input_tokens": 44,
                "output_tokens": 21,
            },
        }
        with patch(
            "odoo.addons.ob_ai_assistant.services.ob_ai_provider_service.requests.post",
            return_value=MockResponse(payload),
        ) as mocked_post:
            result = self.env["ob.ai.provider.service"].generate_text(
                self.provider_anthropic,
                self.model_anthropic,
                "System prompt",
                [{"role": "user", "content": "Hello Claude"}],
            )

        self.assertEqual(result["text"], "Claude summary response")
        self.assertEqual(result["provider_response_id"], "msg_anthropic_1")
        headers = mocked_post.call_args.kwargs["headers"]
        self.assertEqual(headers["anthropic-version"], "2023-06-01")
        self.assertEqual(headers["x-api-key"], "test-anthropic-key")

    def test_schema_refresh_creates_current_snapshot(self):
        version = self.env["ob.ai.schema.service"].refresh_schema_registry(trigger_source="manual")

        self.assertEqual(version.status, "ready")
        self.assertTrue(version.current)
        self.assertTrue(version.checksum)
        self.assertGreater(version.module_count, 0)
        self.assertGreater(version.model_count, 0)
        self.assertGreater(version.field_count, 0)
        self.assertTrue(version.module_ids.filtered(lambda module: module.technical_name == "ob_ai_assistant"))
        partner_schema = version.schema_model_ids.filtered(lambda model: model.model_name == "res.partner")[:1]
        self.assertTrue(partner_schema)
        self.assertTrue(partner_schema.field_ids.filtered(lambda field: field.name == "name"))

    def test_schema_service_builds_ecosystem_context(self):
        version = self.env["ob.ai.schema.service"].ensure_current_schema(trigger_source="manual")
        ecosystem = self.env["ob.ai.schema.service"].build_ecosystem_context(schema_version=version)

        self.assertEqual(ecosystem["schema_version_id"], version.id)
        self.assertEqual(ecosystem["odoo_version"], version.odoo_version)
        self.assertGreater(ecosystem["installed_module_count"], 0)
        self.assertIn("ob_ai_assistant", ecosystem["custom_modules"])
        self.assertTrue(ecosystem["business_domains"])

    def test_semantic_sync_creates_partner_semantic(self):
        version = self.env["ob.ai.schema.service"].ensure_current_schema(trigger_source="manual")
        self.env["ob.ai.semantic.service"].sync_semantics(schema_version=version, force_update=True)

        semantic = self.env["ob.ai.semantic.service"].get_semantic_for_allowed_model(self.allowed_partner_model)
        self.assertTrue(semantic)
        self.assertEqual(semantic.schema_version_id, version)
        self.assertEqual(semantic.business_label, "Partners")
        self.assertIn("name", semantic.title_field_names or "")

    def test_semantic_sync_reuses_inactive_semantic_record(self):
        version = self.env["ob.ai.schema.service"].ensure_current_schema(trigger_source="manual")
        semantic = self.env["ob.ai.semantic.service"].get_semantic_for_allowed_model(self.allowed_partner_model)
        semantic.write({"active": False})

        self.env["ob.ai.semantic.service"].sync_semantics(schema_version=version, force_update=True)

        semantic = self.env["ob.ai.semantic.service"].get_semantic_for_allowed_model(self.allowed_partner_model)
        self.assertTrue(semantic)
        self.assertEqual(
            self.env["ob.ai.model.semantic"].with_context(active_test=False).search_count([
                ("allowed_model_id", "=", self.allowed_partner_model.id),
            ]),
            1,
        )
        self.assertFalse(semantic.active)

    def test_request_token_fetch_respects_template_fields(self):
        self.env["ob.ai.allowed.model"].ensure_default_models()
        limited_user = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "AI Token Template User",
            "login": "ai.token.template.user",
            "email": "ai.token.template.user@example.com",
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id, self.ai_user_group.id])],
        })
        template = self.env["ob.ai.access.template"].create({
            "name": "Token Partner Template",
            "user_ids": [(6, 0, [limited_user.id])],
        })
        partner_line = template.line_ids.filtered(lambda line: line.allowed_model_id == self.allowed_partner_model)[:1]
        self.assertTrue(partner_line)
        visible_fields = self.env["ir.model.fields"].search([
            ("model_id", "=", self.allowed_partner_model.model_id.id),
            ("name", "in", ["name", "email"]),
        ])
        phone_field = self.env["ir.model.fields"].search([
            ("model_id", "=", self.allowed_partner_model.model_id.id),
            ("name", "=", "phone"),
        ], limit=1)
        (template.line_ids - partner_line).write({"active": False})
        partner_line.write({
            "active": True,
            "allowed_field_ids": [(6, 0, visible_fields.ids)],
            "blocked_field_ids": [(6, 0, phone_field.ids)],
        })

        communication_service = self.env["ob.ai.communication.service"].with_user(limited_user).with_company(self.env.company)
        contract = communication_service.issue_request_token(request_kind="record_read")

        schema_bundle = self.env["ob.ai.communication.service"].fetch_schema_bundle(
            contract["token"],
            model_names=["res.partner", "sale.order"],
        )
        self.assertTrue(schema_bundle["schema_version_id"])
        self.assertEqual([model_payload["model"] for model_payload in schema_bundle["models"]], ["res.partner"])
        schema_field_names = [field_payload["name"] for field_payload in schema_bundle["models"][0]["fields"]]
        self.assertIn("name", schema_field_names)
        self.assertIn("email", schema_field_names)
        self.assertNotIn("phone", schema_field_names)

        record_bundle = self.env["ob.ai.communication.service"].fetch_record_bundle(
            contract["token"],
            "res.partner",
            domain=[("id", "=", self.partner.id)],
            limit=1,
            field_names=["name", "email", "phone"],
        )
        self.assertEqual(record_bundle["source"], "communication_gateway")
        self.assertEqual(record_bundle["token_id"], contract["record"].id)
        self.assertEqual(record_bundle["records"][0]["name"], "AI Test Customer")
        self.assertEqual(record_bundle["records"][0]["email"], "ai.customer@example.com")
        self.assertNotIn("phone", record_bundle["records"][0])
        self.assertEqual(record_bundle["blocked_requested_fields"], ["phone"])

    def test_signed_gateway_request_validation_rejects_replay(self):
        communication_service = self.env["ob.ai.communication.service"]
        contract = communication_service.issue_request_token(request_kind="schema_read")
        payload = {"model_names": ["res.partner"]}
        headers = communication_service.prepare_gateway_auth_headers(
            contract["token"],
            payload,
            required_scope="read_schema",
        )
        raw_body = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")

        token_record = communication_service.validate_signed_gateway_request(
            headers,
            raw_body,
            required_scope="read_schema",
        )
        self.assertTrue(token_record.last_used_at)
        self.assertEqual(token_record.use_count, 1)

        with self.assertRaises(UserError):
            communication_service.validate_signed_gateway_request(
                headers,
                raw_body,
                required_scope="read_schema",
            )

    def test_global_context_mode_does_not_auto_lock_model_after_response(self):
        if "crm.lead" not in self.env:
            self.skipTest("CRM is not installed in this test database.")
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Global Context Conversation",
            "provider_id": self.provider_openai.id,
            "model_id": self.model_openai.id,
            "context_mode": "global",
            "allowed_model_id": self.allowed_partner_model.id,
            "prompt_input": "Give me the CRM briefing",
        })
        payload = self._provider_payload("Provider fallback text")
        with patch(
            "odoo.addons.ob_ai_assistant.services.ob_ai_provider_service.requests.post",
            return_value=MockResponse(payload),
        ):
            conversation.action_send_prompt()

        self.assertEqual(conversation.context_mode, "global")
        self.assertEqual(conversation.allowed_model_id, self.allowed_partner_model)
        self.assertIn(conversation.intent_code, {"crm_briefing", "generic_investigation"})

    def test_access_service_filters_blocked_fields(self):
        context = self.env["ob.ai.access.service"].build_record_context(
            self.partner,
            allowed_model=self.allowed_partner_model,
        )

        self.assertEqual(context["source"], "related_record")
        self.assertEqual(context["accessed_models"], ["res.partner"])
        self.assertIn(self.partner.id, context["accessed_record_ids"]["res.partner"])
        row = context["records"][0]
        self.assertEqual(row["name"], "AI Test Customer")
        self.assertEqual(row["email"], "ai.customer@example.com")
        self.assertNotIn("phone", row)
        self.assertIn("phone", context["blocked_fields"]["res.partner"])

    def test_available_allowed_models_excludes_abstract_models(self):
        if "account.edi.common" not in self.env:
            self.skipTest("account.edi.common model is not available in this test database.")
        abstract_ir_model = self.env["ir.model"]._get("account.edi.common")
        abstract_allowed_model = self.env["ob.ai.allowed.model"].search(
            [("model_id", "=", abstract_ir_model.id)],
            limit=1,
        )
        if not abstract_allowed_model:
            abstract_allowed_model = self.env["ob.ai.allowed.model"].create({
                "name": "EDI Common (Abstract)",
                "model_id": abstract_ir_model.id,
                "allow_dashboard_generation": True,
                "allow_validation": True,
            })

        available_models = self.env["ob.ai.access.service"].available_allowed_models(user=self.env.user)
        self.assertNotIn(abstract_allowed_model, available_models)

    def test_conversation_send_prompt_creates_messages_and_audit_log(self):
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Partner Summary",
            "provider_id": self.provider_openai.id,
            "model_id": self.model_openai.id,
            "allowed_model_id": self.allowed_partner_model.id,
            "related_record_ref": "res.partner,%s" % self.partner.id,
            "prompt_input": "Summarize this customer and suggest a follow-up.",
        })
        payload = {
            "id": "resp_openai_2",
            "output_text": "Customer looks active. Suggested next action: follow up tomorrow with a payment reminder.",
            "usage": {
                "input_tokens": 77,
                "output_tokens": 24,
            },
        }
        with patch(
            "odoo.addons.ob_ai_assistant.services.ob_ai_provider_service.requests.post",
            return_value=MockResponse(payload),
        ):
            conversation.action_send_prompt()

        self.assertEqual(conversation.state, "done")
        self.assertFalse(conversation.prompt_input)
        self.assertEqual(len(conversation.ai_message_ids), 2)
        assistant_message = conversation.ai_message_ids.sorted("id")[-1]
        self.assertEqual(assistant_message.role, "assistant")
        self.assertIn("follow up", assistant_message.content.lower())
        self.assertTrue(assistant_message.audit_log_id)
        self.assertEqual(assistant_message.audit_log_id.status, "success")
        self.assertEqual(assistant_message.audit_log_id.accessed_models, "res.partner")
        self.assertTrue(assistant_message.audit_log_id.schema_version_id)
        self.assertTrue(assistant_message.audit_log_id.request_token_id)
        self.assertEqual(assistant_message.audit_log_id.request_token_id.audit_log_id, assistant_message.audit_log_id)
        self.assertEqual(assistant_message.audit_log_id.request_token_id.conversation_id, conversation)
        self.assertEqual(conversation.intent_code, "summarize_document")

    def test_reminder_prompt_creates_reminder(self):
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Partner Reminder",
            "provider_id": self.provider_openai.id,
            "model_id": self.model_openai.id,
            "allowed_model_id": self.allowed_partner_model.id,
            "related_record_ref": "res.partner,%s" % self.partner.id,
            "prompt_input": "Remind me tomorrow to call this customer.",
        })
        with patch(
            "odoo.addons.ob_ai_assistant.services.ob_ai_provider_service.requests.post",
            return_value=MockResponse(self._provider_payload("Reminder noted and prepared.")),
        ):
            conversation.action_send_prompt()

        self.assertEqual(conversation.intent_code, "create_reminder")
        self.assertEqual(len(conversation.reminder_ids), 1)
        reminder = conversation.reminder_ids[:1]
        self.assertEqual(reminder.status, "pending")
        self.assertTrue(reminder.due_datetime)
        self.assertEqual(conversation.audit_log_ids.sorted("id")[-1].action_performed, "reminder_created")

    def test_duplicate_activity_is_prevented(self):
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Partner Activity",
            "allowed_model_id": self.allowed_partner_model.id,
            "related_record_ref": "res.partner,%s" % self.partner.id,
        })
        route = {
            "allowed_model": self.allowed_partner_model,
            "target_record": self.partner,
            "due_datetime": fields.Datetime.now(),
            "requires_approval": False,
            "approval_scope": "general",
        }
        action_service = self.env["ob.ai.action.service"]
        result_1 = action_service.create_activity_from_prompt(conversation, route, "Create activity to call this customer.")
        result_2 = action_service.create_activity_from_prompt(conversation, route, "Create activity to call this customer.")

        self.assertEqual(result_1["action_performed"], "activity_created")
        self.assertEqual(result_2["action_performed"], "activity_existing")
        self.assertEqual(
            self.env["mail.activity"].search_count([("res_model", "=", "res.partner"), ("res_id", "=", self.partner.id)]),
            1,
        )

    def test_duplicate_activity_approval_is_prevented(self):
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Partner Activity Approval",
            "allowed_model_id": self.allowed_partner_model.id,
            "related_record_ref": "res.partner,%s" % self.partner.id,
        })
        route = {
            "allowed_model": self.allowed_partner_model,
            "target_record": self.partner,
            "due_datetime": fields.Datetime.now(),
            "requires_approval": True,
            "approval_scope": "general",
        }
        action_service = self.env["ob.ai.action.service"]
        result_1 = action_service.create_activity_from_prompt(conversation, route, "Create activity to call this customer.")
        result_2 = action_service.create_activity_from_prompt(conversation, route, "Create activity to call this customer.")

        self.assertEqual(result_1["action_performed"], "approval_requested")
        self.assertEqual(result_2["action_performed"], "approval_requested")
        self.assertEqual(
            self.env["ob.ai.approval"].search_count([("source_conversation_id", "=", conversation.id), ("action_type", "=", "activity")]),
            1,
        )

    def test_activity_approval_payload_serializes_date_fields(self):
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Partner Activity Approval Payload",
            "allowed_model_id": self.allowed_partner_model.id,
            "related_record_ref": "res.partner,%s" % self.partner.id,
        })
        due_datetime = fields.Datetime.now()
        route = {
            "allowed_model": self.allowed_partner_model,
            "target_record": self.partner,
            "due_datetime": due_datetime,
            "requires_approval": True,
            "approval_scope": "general",
        }

        result = self.env["ob.ai.action.service"].create_activity_from_prompt(
            conversation,
            route,
            "Create activity to call this customer.",
        )
        approval = result["approval"]
        expected_deadline = fields.Date.to_string(fields.Datetime.to_datetime(due_datetime).date())

        self.assertEqual(result["action_performed"], "approval_requested")
        self.assertEqual(approval.payload_json["date_deadline"], expected_deadline)

        approval.action_approve()
        approval.action_apply()

        self.assertEqual(approval.review_status, "applied")
        activity = self.env["mail.activity"].search([("ob_ai_idempotency_key", "=", approval.idempotency_key)], limit=1)
        self.assertTrue(activity)
        self.assertEqual(fields.Date.to_string(activity.date_deadline), expected_deadline)

    def test_generic_investigation_is_used_for_customer_visibility_prompt(self):
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Partner Dashboard",
            "provider_id": self.provider_openai.id,
            "model_id": self.model_openai.id,
            "allowed_model_id": self.allowed_partner_model.id,
            "prompt_input": "How many customers are visible right now?",
        })
        with patch(
            "odoo.addons.ob_ai_assistant.services.ob_ai_provider_service.requests.post",
            return_value=MockResponse(self._provider_payload("Customer visibility dashboard generated.")),
        ):
            conversation.action_send_prompt()

        self.assertEqual(conversation.intent_code, "generic_investigation")
        self.assertTrue(conversation.last_investigation_trace_id)
        self.assertTrue(conversation.last_memory_state_id)
        self.assertIn("visible records", conversation.ai_message_ids.sorted("id")[-1].content.lower())
        self.assertEqual(
            conversation.audit_log_ids.sorted("id")[-1].action_performed,
            "generic_investigation_completed",
        )

    def test_generic_investigation_handles_probe_exception_gracefully(self):
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Investigation Probe Exception",
            "allowed_model_id": self.allowed_partner_model.id,
        })
        with patch(
            "odoo.addons.ob_ai_assistant.services.ob_ai_investigation_service.OBAIInvestigationService._investigate_semantic",
            side_effect=Exception("probe_failure"),
        ):
            result = self.env["ob.ai.assistant.service"].generate_response(
                conversation,
                "How many customers are visible right now?",
                provider=False,
                model=False,
            )

        self.assertEqual(result["intent_code"], "generic_investigation")
        self.assertEqual(result["action_performed"], "generic_investigation_completed")
        self.assertIn("did not return any visible odoo data", result["text"].lower())
        self.assertIn("skipped", (result.get("warning_message") or "").lower())

    def test_conversation_context_includes_ecosystem_metadata(self):
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Partner Ecosystem Context",
            "allowed_model_id": self.allowed_partner_model.id,
        })
        result = self.env["ob.ai.assistant.service"].generate_response(
            conversation,
            "How many customers are visible right now?",
            provider=False,
            model=False,
        )

        ecosystem = result["context_bundle"].get("ecosystem") or {}
        self.assertTrue(ecosystem)
        self.assertEqual(ecosystem["odoo_version"], result["context_bundle"]["schema"]["odoo_version"])
        self.assertIn("ob_ai_assistant", ecosystem["custom_modules"])

    def test_generic_investigation_overrides_internal_ai_conversation_model(self):
        approval_ir_model = self.env["ir.model"]._get("ob.ai.approval")
        approval_fields = self.env["ir.model.fields"].search([
            ("model_id", "=", approval_ir_model.id),
            ("name", "in", ["name", "review_status", "action_type"]),
        ])
        internal_allowed_model = self.env["ob.ai.allowed.model"].create({
            "name": "AI Approvals",
            "model_id": approval_ir_model.id,
            "allowed_field_ids": [(6, 0, approval_fields.ids)],
            "reference_field_names": "name",
            "name_field_names": "name",
            "allow_dashboard_generation": True,
            "allow_validation": True,
        })
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Internal AI Bias Check",
            "allowed_model_id": internal_allowed_model.id,
        })

        result = self.env["ob.ai.assistant.service"].generate_response(
            conversation,
            "I want to understand my customer behaviour.",
            provider=False,
            model=False,
        )

        self.assertEqual(result["intent_code"], "customer_behavior_briefing")
        self.assertEqual(result["related_model"], "multi_model")
        self.assertNotIn("approval request", result["text"].lower())
        self.assertIn("customer behavior briefing", result["text"].lower())

    def test_business_overview_combines_multiple_models(self):
        if (
            "sale.order" not in self.env
            or "sale.order.line" not in self.env
            or "product.product" not in self.env
            or "stock.picking" not in self.env
            or "stock.picking.type" not in self.env
            or "stock.location" not in self.env
            or "account.move" not in self.env
            or "mail.activity" not in self.env
        ):
            self.skipTest("Business overview requires sales, accounting, inventory, and activity models.")
        customer = self.env["res.partner"].create({"name": "Business Overview Customer"})
        product = self.env["product.product"].create({
            "name": "Business Overview Product",
            "sale_ok": True,
            "list_price": 99.0,
            "type": "service",
        })
        order = self.env["sale.order"].create({
            "partner_id": customer.id,
            "date_order": fields.Datetime.now(),
        })
        self.env["sale.order.line"].create({
            "order_id": order.id,
            "product_id": product.id,
            "name": product.display_name,
            "product_uom_qty": 1.0,
            "product_uom_id": product.uom_id.id,
            "price_unit": 99.0,
        })
        order.write({"state": "sale"})
        outgoing_type = self.env["stock.picking.type"].search([("code", "=", "outgoing")], limit=1)
        if not outgoing_type:
            self.skipTest("No outgoing picking type is configured in this test database.")
        self.env["stock.picking"].create({
            "partner_id": customer.id,
            "picking_type_id": outgoing_type.id,
            "location_id": outgoing_type.default_location_src_id.id,
            "location_dest_id": outgoing_type.default_location_dest_id.id,
            "scheduled_date": "%s 00:00:01" % fields.Date.context_today(self),
            "state": "confirmed",
        })
        activity_type = self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
        if activity_type:
            self.env["mail.activity"].create({
                "activity_type_id": activity_type.id,
                "res_model_id": self.env["ir.model"]._get_id("res.partner"),
                "res_id": customer.id,
                "summary": "Overview follow-up",
                "user_id": self.env.user.id,
                "date_deadline": fields.Date.context_today(self),
            })

        conversation = self.env["ob.ai.conversation"].create({
            "name": "Business Overview Conversation",
        })
        result = self.env["ob.ai.assistant.service"].generate_response(
            conversation,
            "Give me today's business overview across sales, invoices, deliveries, and activities.",
            provider=False,
            model=False,
        )

        snapshot = self.env["ob.ai.kpi.snapshot"].browse(result["snapshot_id"])
        self.assertEqual(result["intent_code"], "business_overview")
        self.assertEqual(result["related_model"], "multi_model")
        self.assertEqual(result["route_context"]["target_model_name"], "multi_model")
        self.assertEqual(snapshot.target_model, "multi_model")
        self.assertIn("business overview", result["text"].lower())
        self.assertIn("booked sales", result["text"].lower())
        self.assertIn("invoiced sales", result["text"].lower())
        self.assertIn("deliveries", result["text"].lower())
        self.assertIn("activities", result["text"].lower())
        self.assertIn("sale.order", result["context_bundle"]["accessed_models"])
        self.assertIn("stock.picking", result["context_bundle"]["accessed_models"])

    def test_multi_domain_overview_prompt_prefers_business_overview_over_crm_only(self):
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Multi Domain Overview Prompt",
            "allowed_model_id": self.allowed_partner_model.id,
        })
        route = self.env["ob.ai.router.service"].route_prompt(
            conversation,
            (
                "give me the current month sales overview\n"
                "give me the current month stock overview\n"
                "give me the current month account overview\n"
                "give me the current month crm overview"
            ),
        )

        self.assertEqual(route["intent_code"], "business_overview")
        self.assertEqual(route["target_model_name"], "multi_model")

    def test_sales_overview_prompt_without_explicit_period_routes_to_sales_overview(self):
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Sales Overview Routing",
            "allowed_model_id": self.allowed_partner_model.id,
        })
        route = self.env["ob.ai.router.service"].route_prompt(
            conversation,
            "give me sales overview",
        )

        self.assertEqual(route["intent_code"], "sales_overview")
        self.assertEqual(route["target_model_name"], "sale.order")

    def test_business_health_prompt_routes_to_business_overview(self):
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Business Health Routing",
            "allowed_model_id": self.allowed_partner_model.id,
        })
        route = self.env["ob.ai.router.service"].route_prompt(
            conversation,
            "research on our ERP data and predict our business health and give me suggestions.",
        )

        self.assertEqual(route["intent_code"], "business_overview")
        self.assertEqual(route["target_model_name"], "multi_model")

    def test_crm_stage_distribution_prompt_routes_to_crm_briefing(self):
        conversation = self.env["ob.ai.conversation"].create({
            "name": "CRM Stage Distribution Routing",
            "allowed_model_id": self.allowed_partner_model.id,
        })
        route = self.env["ob.ai.router.service"].route_prompt(
            conversation,
            "show stage distribution of opportunities",
        )

        self.assertEqual(route["intent_code"], "crm_briefing")
        self.assertEqual(route["target_model_name"], "crm.lead")

    def test_receivables_due_prompt_routes_to_payment_due(self):
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Receivables Due Routing",
            "allowed_model_id": self.allowed_partner_model.id,
        })
        route = self.env["ob.ai.router.service"].route_prompt(
            conversation,
            "show receivables due today",
        )

        self.assertEqual(route["intent_code"], "payment_due")

    def test_overdue_activities_grouped_by_user_routes_to_overdue_items(self):
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Overdue Activities Grouped Routing",
            "allowed_model_id": self.allowed_partner_model.id,
        })
        route = self.env["ob.ai.router.service"].route_prompt(
            conversation,
            "show overdue activities grouped by user",
        )

        self.assertEqual(route["intent_code"], "overdue_items")
        self.assertIn(route["target_model_name"], {"mail.activity", "account.move", "stock.picking"})

    def test_open_quotations_followup_routes_to_sales_overview(self):
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Open Quotations Follow-up Routing",
            "allowed_model_id": self.allowed_partner_model.id,
        })
        route = self.env["ob.ai.router.service"].route_prompt(
            conversation,
            "show open quotations needing follow up",
        )

        self.assertEqual(route["intent_code"], "sales_overview")

    def test_validation_failures_prompt_routes_to_generic_investigation(self):
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Validation Failures Routing",
            "allowed_model_id": self.allowed_partner_model.id,
        })
        route = self.env["ob.ai.router.service"].route_prompt(
            conversation,
            "show validation failures this month",
        )

        self.assertEqual(route["intent_code"], "generic_investigation")

    def test_full_access_prompt_routes_to_access_capability_explainer(self):
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Access Capability Routing",
            "allowed_model_id": self.allowed_partner_model.id,
        })
        route = self.env["ob.ai.router.service"].route_prompt(
            conversation,
            "you have full access",
        )

        self.assertEqual(route["intent_code"], "access_capability_explainer")

    def test_summarize_conversation_phrase_routes_to_summary_intent(self):
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Conversation Summary Routing",
            "allowed_model_id": self.allowed_partner_model.id,
        })
        route = self.env["ob.ai.router.service"].route_prompt(
            conversation,
            "summarize conversation",
        )

        self.assertEqual(route["intent_code"], "summarize_conversation")

    def test_semantic_matching_avoids_view_substring_false_positive(self):
        if "sale.order" not in self.env:
            self.skipTest("Sales order model is required for semantic routing verification.")
        self.env["ob.ai.allowed.model"].ensure_default_models()
        sale_allowed_model = self.env["ob.ai.allowed.model"].search([("model_id.model", "=", "sale.order")], limit=1)
        self.assertTrue(sale_allowed_model)

        view_ir_model = self.env["ir.model"]._get("ir.ui.view")
        view_allowed_model = self.env["ob.ai.allowed.model"].search([("model_id", "=", view_ir_model.id)], limit=1)
        view_fields = self.env["ir.model.fields"].search([
            ("model_id", "=", view_ir_model.id),
            ("name", "in", ["name", "model", "type", "create_date"]),
        ])
        if view_allowed_model:
            view_allowed_model.write({
                "active": True,
                "name": "Views",
                "alias_keywords": "view,views",
                "allowed_field_ids": [(6, 0, view_fields.ids)],
                "reference_field_names": "name,model",
                "name_field_names": "name,model",
                "allow_dashboard_generation": True,
            })
        else:
            view_allowed_model = self.env["ob.ai.allowed.model"].create({
                "name": "Views",
                "model_id": view_ir_model.id,
                "alias_keywords": "view,views",
                "allowed_field_ids": [(6, 0, view_fields.ids)],
                "reference_field_names": "name,model",
                "name_field_names": "name,model",
                "allow_dashboard_generation": True,
                "allow_validation": True,
            })
        self.assertTrue(view_allowed_model)
        self.env["ob.ai.semantic.service"].sync_semantics(force_update=True)

        conversation = self.env["ob.ai.conversation"].create({
            "name": "Semantic Overview Match",
            "allowed_model_id": self.allowed_partner_model.id,
        })
        semantic = self.env["ob.ai.semantic.service"].match_semantics(
            "give me sales overview",
            conversation=conversation,
            user=self.env.user,
            limit=1,
            prefer_related_record=False,
            prefer_conversation_model=False,
            prefer_last_route=False,
        )[:1]

        self.assertTrue(semantic)
        self.assertNotEqual(semantic.model_id.model, "ir.ui.view")

    def test_business_overview_issue_request_token_is_generated(self):
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Business Overview Token Check",
            "allowed_model_id": self.allowed_partner_model.id,
        })
        result = self.env["ob.ai.assistant.service"].generate_response(
            conversation,
            (
                "give me the current month sales overview "
                "and stock overview and account overview and crm overview"
            ),
            provider=False,
            model=False,
        )

        self.assertEqual(result["intent_code"], "business_overview")
        self.assertTrue(result.get("request_token_id"))
        token_record = self.env["ob.ai.request.token"].browse(result["request_token_id"])
        self.assertTrue(token_record.exists())
        self.assertEqual(token_record.request_kind, "chat_context")

    def test_customer_behavior_prompt_generates_cross_model_briefing(self):
        required_models = {"res.partner", "sale.order", "crm.lead", "account.move", "mail.activity"}
        if not required_models.issubset(set(self.env)):
            self.skipTest("Customer behavior briefing requires contacts, sales, CRM, invoicing, and activities.")
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Customer Behavior Briefing",
            "allowed_model_id": self.allowed_partner_model.id,
        })

        result = self.env["ob.ai.assistant.service"].generate_response(
            conversation,
            "I want to understand my customer behaviour across sales, CRM, invoicing and support.",
            provider=False,
            model=False,
        )

        snapshot = self.env["ob.ai.kpi.snapshot"].browse(result["snapshot_id"])
        self.assertEqual(result["intent_code"], "customer_behavior_briefing")
        self.assertEqual(result["related_model"], "multi_model")
        self.assertEqual(result["route_context"]["target_model_name"], "multi_model")
        self.assertEqual(result["action_performed"], "customer_behavior_generated")
        self.assertEqual(snapshot.target_model, "multi_model")
        self.assertIn("customer behavior briefing", result["text"].lower())
        self.assertIn("sales behavior", result["text"].lower())
        self.assertIn("crm behavior", result["text"].lower())
        self.assertIn("payment behavior", result["text"].lower())

    def test_customer_behavior_follow_up_reuses_previous_intent(self):
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Customer Behavior Follow-up",
            "allowed_model_id": self.allowed_partner_model.id,
        })
        first_result = self.env["ob.ai.assistant.service"].generate_response(
            conversation,
            "I want to understand my customer behaviour.",
            provider=False,
            model=False,
        )
        conversation.write({
            "last_route_payload": first_result["route_context"],
            "last_memory_state_id": first_result["memory_state_id"],
            "last_investigation_trace_id": first_result["investigation_trace_id"],
            "intent_code": first_result["intent_code"],
        })

        route = self.env["ob.ai.router.service"].route_prompt(
            conversation,
            "all Sales, CRM, Invoicing and support",
        )

        self.assertEqual(route["intent_code"], "customer_behavior_briefing")
        self.assertEqual(route["target_model_name"], "multi_model")

    def test_customer_behavior_domain_prompt_routes_without_customer_keyword(self):
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Customer Behavior Domain Routing",
            "allowed_model_id": self.allowed_partner_model.id,
        })

        route = self.env["ob.ai.router.service"].route_prompt(
            conversation,
            "all sales, crm, invoicing and support",
        )

        self.assertEqual(route["intent_code"], "customer_behavior_briefing")
        self.assertEqual(route["target_model_name"], "multi_model")

    def test_customer_behavior_prefers_deterministic_summary_over_provider_fallback(self):
        required_models = {"res.partner", "sale.order", "crm.lead", "account.move", "mail.activity"}
        if not required_models.issubset(set(self.env)):
            self.skipTest("Customer behavior briefing requires contacts, sales, CRM, invoicing, and activities.")
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Customer Behavior Deterministic Output",
            "provider_id": self.provider_openai.id,
            "model_id": self.model_openai.id,
            "allowed_model_id": self.allowed_partner_model.id,
        })
        payload = {
            "id": "resp_openai_manual_first",
            "output_text": "I need additional exports and permissions to answer this safely.",
            "usage": {
                "input_tokens": 45,
                "output_tokens": 18,
            },
        }
        with patch(
            "odoo.addons.ob_ai_assistant.services.ob_ai_provider_service.requests.post",
            return_value=MockResponse(payload),
        ):
            conversation.write({
                "prompt_input": "I want to understand my customer behaviour across sales, CRM, invoicing and support.",
            })
            conversation.action_send_prompt()

        assistant_message = conversation.ai_message_ids.sorted("id")[-1]
        self.assertEqual(assistant_message.role, "assistant")
        self.assertIn("customer behavior briefing", assistant_message.content.lower())
        self.assertNotIn("additional exports and permissions", assistant_message.content.lower())

    def test_crm_briefing_uses_crm_pipeline_when_template_allows_it(self):
        if "crm.lead" not in self.env:
            self.skipTest("CRM is not installed in this test database.")
        self.env["ob.ai.allowed.model"].ensure_default_models()
        crm_allowed_model = self.env["ob.ai.allowed.model"].search([("model_id.model", "=", "crm.lead")], limit=1)
        self.assertTrue(crm_allowed_model)
        template = self.env["ob.ai.access.template"].create({
            "name": "CRM Access Template",
            "user_ids": [(6, 0, [self.env.user.id])],
        })
        crm_line = template.line_ids.filtered(lambda line: line.allowed_model_id == crm_allowed_model)[:1]
        self.assertTrue(crm_line)
        partner_line = template.line_ids.filtered(lambda line: line.allowed_model_id == self.allowed_partner_model)[:1]
        crm_fields = self.env["ir.model.fields"].search([
            ("model_id", "=", crm_allowed_model.model_id.id),
            ("name", "in", ["name", "stage_id", "type", "expected_revenue", "probability", "date_deadline", "user_id", "company_currency"]),
        ])
        crm_line.write({
            "allowed_field_ids": [(6, 0, crm_fields.ids)],
            "allow_dashboard_generation": True,
            "max_record_count": 10,
            "search_limit": 10,
        })
        if partner_line:
            partner_line.write({"allowed_model_id": self.allowed_partner_model.id})

        lead = self.env["crm.lead"].create({
            "name": "AI CRM Opportunity",
            "type": "opportunity",
            "user_id": self.env.user.id,
            "expected_revenue": 12500.0,
            "probability": 85.0,
            "date_deadline": fields.Date.context_today(self) + relativedelta(days=3),
        })
        self.assertTrue(lead)
        conversation = self.env["ob.ai.conversation"].create({
            "name": "CRM Briefing Conversation",
            "allowed_model_id": self.allowed_partner_model.id,
        })

        result = self.env["ob.ai.assistant.service"].generate_response(
            conversation,
            "Give me the CRM briefing",
            provider=False,
            model=False,
        )

        snapshot = self.env["ob.ai.kpi.snapshot"].browse(result["snapshot_id"])
        self.assertEqual(result["intent_code"], "crm_briefing")
        self.assertEqual(result["related_model"], "crm.lead")
        self.assertEqual(result["allowed_model_id"], crm_allowed_model.id)
        self.assertEqual(result["route_context"]["target_model_name"], "crm.lead")
        self.assertEqual(snapshot.target_model, "crm.lead")
        self.assertIn("crm briefing", result["text"].lower())
        self.assertIn("pipeline", result["text"].lower())
        self.assertIn("expected pipeline revenue", result["text"].lower())
        self.assertIn("crm.lead", result["context_bundle"]["accessed_models"])

    def test_crm_customer_specific_prompt_routes_to_generic_investigation(self):
        if "crm.lead" not in self.env:
            self.skipTest("CRM is not installed in this test database.")
        conversation = self.env["ob.ai.conversation"].create({
            "name": "CRM Existing Customer Filter Prompt",
            "allowed_model_id": self.allowed_partner_model.id,
        })
        route = self.env["ob.ai.router.service"].route_prompt(
            conversation,
            "give me the status of CRM Leads for those contacts which already our customer.",
        )

        self.assertEqual(route["intent_code"], "generic_investigation")
        self.assertEqual(route["target_model_name"], "crm.lead")

    def test_document_summary_without_attachment_returns_guidance_text(self):
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Document Summary Without Attachment",
            "allowed_model_id": self.allowed_partner_model.id,
        })
        result = self.env["ob.ai.assistant.service"].generate_response(
            conversation,
            "analyze document",
            provider=False,
            model=False,
        )

        self.assertEqual(result["intent_code"], "summarize_document")
        self.assertEqual(result["action_performed"], "document_context_missing")
        self.assertIn("upload a document", result["text"].lower())

    def test_router_detects_dashboard_export_requests(self):
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Export Intent Routing",
            "allowed_model_id": self.allowed_partner_model.id,
        })
        route = self.env["ob.ai.router.service"].route_prompt(
            conversation,
            "Give me a CRM pipeline briefing and create PDF dashboard with PNG image export.",
        )

        self.assertTrue(route["export_pdf_requested"])
        self.assertTrue(route["export_image_requested"])

    def test_crm_briefing_can_generate_pdf_and_image_exports(self):
        if "crm.lead" not in self.env:
            self.skipTest("CRM is not installed in this test database.")
        self.env["ob.ai.allowed.model"].ensure_default_models()
        crm_allowed_model = self.env["ob.ai.allowed.model"].search([("model_id.model", "=", "crm.lead")], limit=1)
        self.assertTrue(crm_allowed_model)
        template = self.env["ob.ai.access.template"].create({
            "name": "CRM Export Template",
            "user_ids": [(6, 0, [self.env.user.id])],
        })
        crm_line = template.line_ids.filtered(lambda line: line.allowed_model_id == crm_allowed_model)[:1]
        self.assertTrue(crm_line)
        crm_fields = self.env["ir.model.fields"].search([
            ("model_id", "=", crm_allowed_model.model_id.id),
            ("name", "in", ["name", "stage_id", "type", "expected_revenue", "probability", "date_deadline", "user_id", "company_currency"]),
        ])
        crm_line.write({
            "allowed_field_ids": [(6, 0, crm_fields.ids)],
            "allow_dashboard_generation": True,
            "max_record_count": 10,
            "search_limit": 10,
        })
        self.env["crm.lead"].create({
            "name": "AI CRM Export Opportunity",
            "type": "opportunity",
            "user_id": self.env.user.id,
            "expected_revenue": 18500.0,
            "probability": 72.0,
            "date_deadline": fields.Date.context_today(self) + relativedelta(days=4),
        })
        conversation = self.env["ob.ai.conversation"].create({
            "name": "CRM Export Conversation",
            "allowed_model_id": self.allowed_partner_model.id,
        })

        result = self.env["ob.ai.assistant.service"].generate_response(
            conversation,
            "Give me CRM briefing and create PDF dashboard and image export.",
            provider=False,
            model=False,
        )

        snapshot = self.env["ob.ai.kpi.snapshot"].browse(result["snapshot_id"])
        self.assertTrue(snapshot.export_pdf_attachment_id)
        self.assertTrue(snapshot.export_image_attachment_id)
        self.assertEqual(snapshot.export_pdf_attachment_id.mimetype, "application/pdf")
        self.assertEqual(snapshot.export_image_attachment_id.mimetype, "image/png")
        self.assertEqual(snapshot.export_pdf_attachment_id.res_model, "ob.ai.kpi.snapshot")
        self.assertEqual(snapshot.export_image_attachment_id.res_model, "ob.ai.kpi.snapshot")
        self.assertEqual(snapshot.export_pdf_attachment_id.res_id, snapshot.id)
        self.assertEqual(snapshot.export_image_attachment_id.res_id, snapshot.id)
        self.assertEqual(sorted(result["export_attachment_ids"]), sorted(snapshot.export_pdf_attachment_id.ids + snapshot.export_image_attachment_id.ids))
        self.assertEqual(len(result["export_urls"]), 2)
        self.assertTrue(all(url.startswith("/web/content/") for url in result["export_urls"]))
        self.assertIn("dashboard export completed", result["text"].lower())

    def test_generic_investigation_applies_existing_customer_domain(self):
        if "crm.lead" not in self.env:
            self.skipTest("CRM is not installed in this test database.")
        self.env["ob.ai.allowed.model"].ensure_default_models()
        crm_allowed_model = self.env["ob.ai.allowed.model"].search([("model_id.model", "=", "crm.lead")], limit=1)
        self.assertTrue(crm_allowed_model)
        semantic = self.env["ob.ai.semantic.service"].get_semantic_for_allowed_model(crm_allowed_model)
        semantic_payload = self.env["ob.ai.semantic.service"].get_runtime_semantic(semantic, user=self.env.user)

        domain = self.env["ob.ai.investigation.service"]._build_domain(
            semantic_payload,
            {"search_term": False},
            date_scope=False,
            state_scope=False,
            normalized_prompt="show crm leads for existing customers",
        )

        partner_field = semantic_payload.get("partner_field_names", [False])[0]
        self.assertTrue(partner_field)
        self.assertIn((partner_field, "!=", False), domain)
        if "customer_rank" in self.env["res.partner"]._fields:
            self.assertIn(("%s.customer_rank" % partner_field, ">", 0), domain)

    def test_generic_investigation_can_aggregate_visible_pipeline_amount(self):
        if "crm.lead" not in self.env:
            self.skipTest("CRM is not installed in this test database.")
        self.env["ob.ai.allowed.model"].ensure_default_models()
        crm_allowed_model = self.env["ob.ai.allowed.model"].search([("model_id.model", "=", "crm.lead")], limit=1)
        self.assertTrue(crm_allowed_model)
        template = self.env["ob.ai.access.template"].create({
            "name": "CRM Aggregate Template",
            "user_ids": [(6, 0, [self.env.user.id])],
        })
        crm_line = template.line_ids.filtered(lambda line: line.allowed_model_id == crm_allowed_model)[:1]
        self.assertTrue(crm_line)
        crm_fields = self.env["ir.model.fields"].search([
            ("model_id", "=", crm_allowed_model.model_id.id),
            ("name", "in", ["name", "stage_id", "type", "expected_revenue", "probability", "date_deadline", "user_id"]),
        ])
        crm_line.write({
            "allowed_field_ids": [(6, 0, crm_fields.ids)],
            "max_record_count": 10,
            "search_limit": 10,
        })
        stage = self.env["crm.stage"].search([], limit=1)
        self.assertTrue(stage)
        self.env["crm.lead"].create({
            "name": "AI Pipeline Deal A",
            "type": "opportunity",
            "stage_id": stage.id,
            "user_id": self.env.user.id,
            "expected_revenue": 12000.0,
            "probability": 40.0,
        })
        self.env["crm.lead"].create({
            "name": "AI Pipeline Deal B",
            "type": "opportunity",
            "stage_id": stage.id,
            "user_id": self.env.user.id,
            "expected_revenue": 8000.0,
            "probability": 80.0,
        })
        conversation = self.env["ob.ai.conversation"].create({
            "name": "CRM Aggregate Conversation",
            "allowed_model_id": crm_allowed_model.id,
        })

        result = self.env["ob.ai.assistant.service"].generate_response(
            conversation,
            'What is the average probability for "AI Pipeline Deal"?',
            provider=False,
            model=False,
        )

        self.assertEqual(result["intent_code"], "generic_investigation")
        self.assertEqual(result["route_context"]["generic_query_type"], "aggregate")
        self.assertEqual(result["allowed_model_id"], crm_allowed_model.id)
        self.assertIn("probability", result["text"].lower())
        self.assertIn("60.00", result["text"])
        self.assertIn("crm.lead", result["context_bundle"]["accessed_models"])

    def test_generic_investigation_can_group_visible_pipeline_by_stage(self):
        if "crm.lead" not in self.env:
            self.skipTest("CRM is not installed in this test database.")
        self.env["ob.ai.allowed.model"].ensure_default_models()
        crm_allowed_model = self.env["ob.ai.allowed.model"].search([("model_id.model", "=", "crm.lead")], limit=1)
        self.assertTrue(crm_allowed_model)
        template = self.env["ob.ai.access.template"].create({
            "name": "CRM Group Template",
            "user_ids": [(6, 0, [self.env.user.id])],
        })
        crm_line = template.line_ids.filtered(lambda line: line.allowed_model_id == crm_allowed_model)[:1]
        self.assertTrue(crm_line)
        crm_fields = self.env["ir.model.fields"].search([
            ("model_id", "=", crm_allowed_model.model_id.id),
            ("name", "in", ["name", "stage_id", "type", "expected_revenue", "probability", "date_deadline", "user_id"]),
        ])
        crm_line.write({
            "allowed_field_ids": [(6, 0, crm_fields.ids)],
            "max_record_count": 10,
            "search_limit": 10,
        })
        stages = self.env["crm.stage"].search([], order="sequence, id", limit=2)
        if len(stages) < 2:
            stages |= self.env["crm.stage"].create({"name": "AI Negotiation"})
        self.env["crm.lead"].create({
            "name": "AI Stage Deal A",
            "type": "opportunity",
            "stage_id": stages[0].id,
            "user_id": self.env.user.id,
            "expected_revenue": 5000.0,
            "probability": 90.0,
        })
        self.env["crm.lead"].create({
            "name": "AI Stage Deal B",
            "type": "opportunity",
            "stage_id": stages[0].id,
            "user_id": self.env.user.id,
            "expected_revenue": 2500.0,
            "probability": 50.0,
        })
        self.env["crm.lead"].create({
            "name": "AI Stage Deal C",
            "type": "opportunity",
            "stage_id": stages[1].id,
            "user_id": self.env.user.id,
            "expected_revenue": 7000.0,
            "probability": 25.0,
        })
        conversation = self.env["ob.ai.conversation"].create({
            "name": "CRM Group Conversation",
            "allowed_model_id": crm_allowed_model.id,
        })

        result = self.env["ob.ai.assistant.service"].generate_response(
            conversation,
            'Show the visible CRM opportunities by stage for "AI Stage Deal" with probability.',
            provider=False,
            model=False,
        )

        self.assertEqual(result["intent_code"], "generic_investigation")
        self.assertEqual(result["route_context"]["generic_query_type"], "group")
        self.assertEqual(result["allowed_model_id"], crm_allowed_model.id)
        self.assertIn("grouped by", result["text"].lower())
        self.assertIn(stages[0].name, result["text"])
        self.assertIn(stages[1].name, result["text"])
        self.assertIn("average probability", result["text"].lower())

    def test_sales_order_count_follow_up_reuses_previous_context(self):
        if "sale.order" not in self.env:
            self.skipTest("Sales orders are not installed in this test database.")
        customer = self.env["res.partner"].create({"name": "Follow-up Sales Customer"})
        current_month_order = self.env["sale.order"].create({
            "partner_id": customer.id,
            "date_order": fields.Datetime.now(),
        })
        previous_month_order = self.env["sale.order"].create({
            "partner_id": customer.id,
            "date_order": fields.Datetime.now() - relativedelta(months=1),
        })
        current_month_order.write({"state": "sale"})
        previous_month_order.write({"state": "sale"})
        self.assertTrue(current_month_order and previous_month_order)
        today = fields.Date.context_today(self)
        month_start = today.replace(day=1)
        month_end = month_start + relativedelta(months=1)
        expected_month_confirmed = self.env["sale.order"].search_count([
            ("state", "in", ["sale", "done"]),
            ("date_order", ">=", "%s 00:00:00" % month_start),
            ("date_order", "<", "%s 00:00:00" % month_end),
        ])
        expected_all_confirmed = self.env["sale.order"].search_count([("state", "in", ["sale", "done"])])
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Sales Follow-up Context",
        })

        first_result = self.env["ob.ai.assistant.service"].generate_response(
            conversation,
            "How many sale orders do we have this month?",
            provider=False,
            model=False,
        )
        conversation.write({
            "last_route_payload": first_result["route_context"],
            "allowed_model_id": first_result["allowed_model_id"],
        })
        second_result = self.env["ob.ai.assistant.service"].generate_response(
            conversation,
            "in total till date",
            provider=False,
            model=False,
        )

        self.assertEqual(first_result["intent_code"], "sales_order_count")
        self.assertEqual(first_result["route_context"]["date_scope"], "current_month")
        self.assertIn("%s confirmed sales orders" % expected_month_confirmed, first_result["text"].lower())
        self.assertEqual(second_result["intent_code"], "sales_order_count")
        self.assertEqual(second_result["route_context"]["date_scope"], "all_time")
        self.assertEqual(second_result["related_model"], "sale.order")
        self.assertIn("%s confirmed sales orders" % expected_all_confirmed, second_result["text"].lower())

    def test_sales_prompt_generates_real_sales_snapshot(self):
        if "sale.order" not in self.env or "sale.order.line" not in self.env or "product.product" not in self.env:
            self.skipTest("Sales models are not installed in this test database.")
        customer = self.env["res.partner"].create({"name": "Monthly Sales Customer"})
        product = self.env["product.product"].create({
            "name": "AI Sales Service",
            "sale_ok": True,
            "list_price": 250.0,
            "type": "service",
        })
        order = self.env["sale.order"].create({
            "partner_id": customer.id,
            "date_order": fields.Datetime.now(),
        })
        self.env["sale.order.line"].create({
            "order_id": order.id,
            "product_id": product.id,
            "name": product.display_name,
            "product_uom_qty": 1.0,
            "product_uom_id": product.uom_id.id,
            "price_unit": 250.0,
        })
        order.write({"state": "sale"})

        conversation = self.env["ob.ai.conversation"].create({
            "name": "Monthly Sales",
            "provider_id": self.provider_openai.id,
            "model_id": self.model_openai.id,
            "prompt_input": "What is my current month sales?",
        })
        with patch(
            "odoo.addons.ob_ai_assistant.services.ob_ai_provider_service.requests.post",
            return_value=MockResponse(self._provider_payload("Monthly sales metrics prepared.")),
        ):
            conversation.action_send_prompt()

        self.assertEqual(conversation.intent_code, "sales_overview")
        self.assertTrue(conversation.last_snapshot_id)
        self.assertEqual(conversation.last_snapshot_id.target_model, "sale.order")
        self.assertTrue(self.env["ob.ai.allowed.model"].search([("model_id.model", "=", "sale.order")], limit=1))
        assistant_message = conversation.ai_message_ids.sorted("id")[-1]
        self.assertIn("confirmed sales orders", assistant_message.content.lower())
        self.assertEqual(conversation.audit_log_ids.sorted("id")[-1].action_performed, "sales_snapshot_generated")

    def test_sales_margin_prompt_is_install_aware(self):
        if "sale.order" not in self.env:
            self.skipTest("Sales orders are not installed in this test database.")
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Sales Margin",
        })

        result = self.env["ob.ai.assistant.service"].generate_response(
            conversation,
            "List all sale orders with margin",
            provider=False,
            model=False,
        )

        self.assertEqual(result["intent_code"], "sales_order_margin_list")
        self.assertEqual(result["related_model"], "sale.order")
        if "margin" in self.env["sale.order"]._fields:
            self.assertIn("margin", result["text"].lower())
        else:
            self.assertIn("sale_margin", result["text"])
            self.assertIn("not installed", result["text"].lower())

    def test_default_allowed_model_syncs_margin_fields_when_available(self):
        if "sale.order" not in self.env or "margin" not in self.env["sale.order"]._fields:
            self.skipTest("Sales margin fields are not installed in this test database.")
        self.env["ob.ai.allowed.model"].ensure_default_models()
        sale_order_allowed_model = self.env["ob.ai.allowed.model"].search([("model_id.model", "=", "sale.order")], limit=1)

        self.assertTrue(sale_order_allowed_model)
        self.assertIn("margin", sale_order_allowed_model.allowed_field_ids.mapped("name"))

    def test_default_allowed_models_include_validation_results(self):
        if "ob.ai.validation.result" not in self.env:
            self.skipTest("Validation result model is not available in this test database.")
        self.env["ob.ai.allowed.model"].ensure_default_models()
        validation_allowed_model = self.env["ob.ai.allowed.model"].search(
            [("model_id.model", "=", "ob.ai.validation.result")],
            limit=1,
        )

        self.assertTrue(validation_allowed_model)
        self.assertIn("validation_status", validation_allowed_model.allowed_field_ids.mapped("name"))

    def test_validation_failures_prompt_returns_investigation_summary(self):
        if "ob.ai.validation.result" not in self.env:
            self.skipTest("Validation result model is not available in this test database.")
        self.env["ob.ai.allowed.model"].ensure_default_models()
        self.env["ob.ai.validation.result"].create({
            "record_model": "res.partner",
            "record_res_id": self.partner.id,
            "validation_status": "fail",
            "review_status": "draft",
            "ai_explanation": "Auto-created test validation failure",
        })
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Validation Failure Prompt",
            "allowed_model_id": self.allowed_partner_model.id,
        })

        result = self.env["ob.ai.assistant.service"].generate_response(
            conversation,
            "show validation failures this month",
            provider=False,
            model=False,
        )

        self.assertEqual(result["intent_code"], "generic_investigation")
        self.assertNotIn("could not map this request", result["text"].lower())

    def test_access_capability_prompt_returns_summary(self):
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Access Capability Summary",
            "allowed_model_id": self.allowed_partner_model.id,
        })
        result = self.env["ob.ai.assistant.service"].generate_response(
            conversation,
            "use communication controller and fetch full data",
            provider=False,
            model=False,
        )

        self.assertEqual(result["intent_code"], "access_capability_explainer")
        self.assertEqual(result["action_performed"], "access_capability_explained")
        self.assertIn("current ai access profile", result["text"].lower())

    def test_product_sales_ranking_can_switch_away_from_conversation_model(self):
        if "sale.order" not in self.env or "sale.order.line" not in self.env or "product.product" not in self.env:
            self.skipTest("Sales models are not installed in this test database.")
        self.env["ob.ai.allowed.model"].ensure_default_models()
        sale_order_allowed_model = self.env["ob.ai.allowed.model"].search([("model_id.model", "=", "sale.order")], limit=1)
        if not sale_order_allowed_model:
            self.skipTest("No default sale.order allowed model is available in this test database.")
        customer = self.env["res.partner"].create({"name": "Ranking Customer"})
        product_a = self.env["product.product"].create({
            "name": "Top Product",
            "sale_ok": True,
            "list_price": 120.0,
            "type": "service",
        })
        product_b = self.env["product.product"].create({
            "name": "Other Product",
            "sale_ok": True,
            "list_price": 80.0,
            "type": "service",
        })
        order = self.env["sale.order"].create({
            "partner_id": customer.id,
            "date_order": fields.Datetime.now(),
        })
        self.env["sale.order.line"].create({
            "order_id": order.id,
            "product_id": product_a.id,
            "name": product_a.display_name,
            "product_uom_qty": 5.0,
            "product_uom_id": product_a.uom_id.id,
            "price_unit": 120.0,
        })
        self.env["sale.order.line"].create({
            "order_id": order.id,
            "product_id": product_b.id,
            "name": product_b.display_name,
            "product_uom_qty": 2.0,
            "product_uom_id": product_b.uom_id.id,
            "price_unit": 80.0,
        })
        order.write({"state": "sale"})
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Cross Model Ranking",
            "allowed_model_id": sale_order_allowed_model.id,
        })

        result = self.env["ob.ai.assistant.service"].generate_response(
            conversation,
            "Which is the most selling product in current month?",
            provider=False,
            model=False,
        )

        self.assertEqual(result["intent_code"], "product_sales_ranking")
        self.assertEqual(result["related_model"], "sale.order.line")
        self.assertIn("top-selling product", result["text"].lower())
        self.assertIn("confirmed orders", result["text"].lower())

    def test_delivery_worklist_can_switch_away_from_conversation_model(self):
        if "stock.picking" not in self.env or "stock.picking.type" not in self.env or "stock.location" not in self.env:
            self.skipTest("Inventory models are not installed in this test database.")
        self.env["ob.ai.allowed.model"].ensure_default_models()
        sale_order_allowed_model = self.env["ob.ai.allowed.model"].search([("model_id.model", "=", "sale.order")], limit=1)
        if not sale_order_allowed_model:
            self.skipTest("No default sale.order allowed model is available in this test database.")
        outgoing_type = self.env["stock.picking.type"].search([("code", "=", "outgoing")], limit=1)
        if not outgoing_type:
            self.skipTest("No outgoing picking type is configured in this test database.")
        picking = self.env["stock.picking"].create({
            "partner_id": self.partner.id,
            "picking_type_id": outgoing_type.id,
            "location_id": outgoing_type.default_location_src_id.id,
            "location_dest_id": outgoing_type.default_location_dest_id.id,
            "scheduled_date": "%s 00:00:01" % fields.Date.context_today(self),
            "state": "confirmed",
        })
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Cross Model Deliveries",
            "allowed_model_id": sale_order_allowed_model.id,
        })

        result = self.env["ob.ai.assistant.service"].generate_response(
            conversation,
            "What are the delivery we need to process today?",
            provider=False,
            model=False,
        )

        self.assertEqual(result["intent_code"], "delivery_worklist")
        self.assertEqual(result["related_model"], "stock.picking")
        self.assertIn("delivery orders to process today", result["text"].lower())
        self.assertIn("first in line", result["text"].lower())

    def test_delivery_worklist_can_create_followup_activities(self):
        if "stock.picking" not in self.env or "stock.picking.type" not in self.env or "stock.location" not in self.env:
            self.skipTest("Inventory models are not installed in this test database.")
        self.env["ob.ai.allowed.model"].ensure_default_models()
        sale_order_allowed_model = self.env["ob.ai.allowed.model"].search([("model_id.model", "=", "sale.order")], limit=1)
        if not sale_order_allowed_model:
            self.skipTest("No default sale.order allowed model is available in this test database.")
        outgoing_type = self.env["stock.picking.type"].search([("code", "=", "outgoing")], limit=1)
        if not outgoing_type:
            self.skipTest("No outgoing picking type is configured in this test database.")
        picking = self.env["stock.picking"].create({
            "partner_id": self.partner.id,
            "picking_type_id": outgoing_type.id,
            "location_id": outgoing_type.default_location_src_id.id,
            "location_dest_id": outgoing_type.default_location_dest_id.id,
            "scheduled_date": "%s 00:00:01" % fields.Date.context_today(self),
            "state": "confirmed",
            "user_id": self.env.user.id,
        })
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Deliveries With Activities",
            "allowed_model_id": sale_order_allowed_model.id,
        })
        activity_count_before = self.env["mail.activity"].search_count([
            ("res_model", "=", "stock.picking"),
            ("ob_ai_generated", "=", True),
        ])

        result = self.env["ob.ai.assistant.service"].generate_response(
            conversation,
            "What are the delivery we need to process today? and create activity to the responsible person.",
            provider=False,
            model=False,
        )

        self.assertEqual(result["intent_code"], "delivery_worklist")
        self.assertEqual(result["related_model"], "stock.picking")
        activity_count_after = self.env["mail.activity"].search_count([
            ("res_model", "=", "stock.picking"),
            ("ob_ai_generated", "=", True),
        ])
        self.assertGreaterEqual(activity_count_after, activity_count_before)
        self.assertTrue(
            "follow-up activities" in result["text"].lower()
            or "already existed" in result["text"].lower()
        )

    def test_activity_creation_without_related_record_uses_investigation_result_set(self):
        if "crm.lead" not in self.env:
            self.skipTest("CRM is not installed in this test database.")
        self.env["ob.ai.allowed.model"].ensure_default_models()
        self.env["crm.lead"].create({
            "name": "AI Follow-up Opportunity",
            "type": "opportunity",
            "user_id": self.env.user.id,
            "date_deadline": fields.Date.context_today(self) - relativedelta(days=2),
            "expected_revenue": 5000.0,
            "probability": 75.0,
        })
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Activity Without Related Record",
            "allowed_model_id": self.allowed_partner_model.id,
        })

        result = self.env["ob.ai.assistant.service"].generate_response(
            conversation,
            "create activity for overdue opportunities assigned to responsible users",
            provider=False,
            model=False,
        )

        self.assertIn(result["intent_code"], {"generic_investigation", "create_activity"})
        self.assertTrue(result["action_performed"])
        self.assertTrue(
            "activities" in result["action_performed"]
            or "activity" in result["action_performed"]
        )
        self.assertNotIn("select a related record", result["text"].lower())

    def test_validation_result_is_created(self):
        validation_partner = self.env["res.partner"].create({"name": "Validation Target"})
        partner_model = self.env["ir.model"]._get("res.partner")
        name_email_fields = self.env["ir.model.fields"].search([
            ("model_id", "=", partner_model.id),
            ("name", "in", ["name", "email"]),
        ])
        self.env["ob.ai.validation.rule"].create({
            "name": "Partner Email Required",
            "target_model_id": partner_model.id,
            "rule_type": "required_fields",
            "required_field_ids": [(6, 0, name_email_fields.ids)],
            "severity": "warning",
        })
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Partner Validation",
            "provider_id": self.provider_openai.id,
            "model_id": self.model_openai.id,
            "allowed_model_id": self.allowed_partner_model.id,
            "related_record_ref": "res.partner,%s" % validation_partner.id,
            "prompt_input": "Validate this customer record.",
        })
        with patch(
            "odoo.addons.ob_ai_assistant.services.ob_ai_provider_service.requests.post",
            return_value=MockResponse(self._provider_payload("Validation completed with one warning.")),
        ):
            conversation.action_send_prompt()

        self.assertEqual(conversation.intent_code, "validate_record")
        self.assertTrue(conversation.validation_result_ids)
        self.assertEqual(conversation.validation_result_ids[:1].validation_status, "warning")
        self.assertEqual(conversation.audit_log_ids.sorted("id")[-1].action_performed, "validation_completed")

    def test_document_context_is_cached(self):
        attachment = self.env["ir.attachment"].create({
            "name": "customer-note.txt",
            "datas": base64.b64encode(b"Customer promised to respond this week.").decode(),
            "mimetype": "text/plain",
            "res_model": "res.partner",
            "res_id": self.partner.id,
            "type": "binary",
        })
        self.assertTrue(attachment)
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Document Summary",
            "provider_id": self.provider_openai.id,
            "model_id": self.model_openai.id,
            "allowed_model_id": self.allowed_partner_model.id,
            "related_record_ref": "res.partner,%s" % self.partner.id,
            "prompt_input": "Summarize document for this customer.",
        })
        with patch(
            "odoo.addons.ob_ai_assistant.services.ob_ai_provider_service.requests.post",
            return_value=MockResponse(self._provider_payload("Document summary prepared.")),
        ):
            conversation.action_send_prompt()

        self.assertEqual(conversation.intent_code, "summarize_document")
        self.assertTrue(conversation.document_context_ids)
        cached_context = conversation.document_context_ids[:1]
        self.assertEqual(cached_context.state, "ready")
        self.assertIn("Customer promised", cached_context.extracted_text)
        # Calling the cache builder again should reuse the same cached row.
        document_payload = self.env["ob.ai.document.service"].build_document_context(self.partner, conversation=conversation)
        self.assertEqual(len(document_payload["document_contexts"]), 1)

    def test_chat_upload_document_can_be_analyzed_without_related_record(self):
        attachment = self.env["ir.attachment"].create({
            "name": "chat-upload-note.txt",
            "datas": base64.b64encode(b"Q2 delivery delay root causes: vendor late dispatch and incomplete ASN details.").decode(),
            "mimetype": "text/plain",
            "type": "binary",
        })
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Chat Upload Analysis",
            "provider_id": self.provider_openai.id,
            "model_id": self.model_openai.id,
            "chat_attachment_ids": [(6, 0, [attachment.id])],
            "prompt_input": "Analyze this attached document and summarize key risks.",
        })
        with patch(
            "odoo.addons.ob_ai_assistant.services.ob_ai_provider_service.requests.post",
            return_value=MockResponse(self._provider_payload("Key risks identified from uploaded document.")),
        ):
            conversation.action_send_prompt()

        self.assertEqual(conversation.intent_code, "summarize_document")
        self.assertTrue(conversation.chat_attachment_ids)
        self.assertTrue(conversation.document_context_ids)
        cached_context = conversation.document_context_ids[:1]
        self.assertIn("vendor late dispatch", (cached_context.extracted_text or "").lower())
        self.assertEqual(attachment.res_model, "ob.ai.conversation")
        self.assertEqual(attachment.res_id, conversation.id)
        assistant_message = conversation.ai_message_ids.sorted("id")[-1]
        self.assertIn("uploaded document", assistant_message.content.lower())

    def test_document_service_extracts_structured_csv_payload(self):
        attachment = self.env["ir.attachment"].create({
            "name": "partner-import.csv",
            "datas": base64.b64encode(
                b"name,email,phone\nCSV Partner One,csv.one@example.com,+491111\nCSV Partner Two,csv.two@example.com,+492222\n"
            ).decode(),
            "mimetype": "text/csv",
            "res_model": "res.partner",
            "res_id": self.partner.id,
            "type": "binary",
        })
        document_service = self.env["ob.ai.document.service"]
        context = document_service.build_attachment_context(attachment)

        self.assertEqual(context["structured_table_count"], 1)
        self.assertEqual(context["structured_row_count"], 2)
        self.assertTrue(context["tables"])
        self.assertEqual(context["tables"][0]["columns"], ["name", "email", "phone"])
        self.assertEqual(context["tables"][0]["rows"][0]["name"], "CSV Partner One")

    def test_tool_import_attachment_rows_can_create_partners_from_csv(self):
        attachment = self.env["ir.attachment"].create({
            "name": "import-partners.csv",
            "datas": base64.b64encode(
                b"name,email\nImport Partner Alpha,import.alpha@example.com\nImport Partner Beta,import.beta@example.com\n"
            ).decode(),
            "mimetype": "text/csv",
            "type": "binary",
        })
        conversation = self.env["ob.ai.conversation"].create({
            "name": "CSV Import Conversation",
            "allowed_model_id": self.allowed_partner_model.id,
        })

        preview = self.env["ob.ai.tool.service"].tool_import_attachment_rows(
            conversation=conversation,
            user=self.env.user,
            model="res.partner",
            attachment_id=attachment.id,
            field_map={"name": "name", "email": "email"},
            mode="create",
            max_rows=50,
            dry_run=True,
        )
        self.assertTrue(preview["ok"])
        self.assertEqual(preview["created_count"], 2)
        self.assertEqual(preview["updated_count"], 0)
        self.assertFalse(self.env["res.partner"].search([("email", "=", "import.alpha@example.com")], limit=1))

        executed = self.env["ob.ai.tool.service"].tool_import_attachment_rows(
            conversation=conversation,
            user=self.env.user,
            model="res.partner",
            attachment_id=attachment.id,
            field_map={"name": "name", "email": "email"},
            mode="create",
            max_rows=50,
            dry_run=False,
        )
        self.assertTrue(executed["ok"])
        self.assertEqual(executed["created_count"], 2)
        created_partners = self.env["res.partner"].search([("email", "in", ["import.alpha@example.com", "import.beta@example.com"])])
        self.assertEqual(len(created_partners), 2)

    def test_tool_odoo_create_records_supports_dry_run_and_execute(self):
        tool_service = self.env["ob.ai.tool.service"]
        dry_run = tool_service.tool_odoo_create_records(
            user=self.env.user,
            model="res.partner",
            values_list=[
                {"name": "Generic Create One", "email": "generic.one@example.com"},
                {"name": "Generic Create Two", "email": "generic.two@example.com"},
            ],
            dry_run=True,
        )
        self.assertTrue(dry_run["ok"])
        self.assertEqual(dry_run["create_count"], 2)
        self.assertFalse(self.env["res.partner"].search([("email", "=", "generic.one@example.com")], limit=1))

        executed = tool_service.tool_odoo_create_records(
            user=self.env.user,
            model="res.partner",
            values_list=[
                {"name": "Generic Create One", "email": "generic.one@example.com"},
                {"name": "Generic Create Two", "email": "generic.two@example.com"},
            ],
            dry_run=False,
        )
        self.assertTrue(executed["ok"])
        self.assertEqual(executed["created_count"], 2)
        created = self.env["res.partner"].search([("email", "in", ["generic.one@example.com", "generic.two@example.com"])])
        self.assertEqual(len(created), 2)

    def test_tool_odoo_update_records_rejects_invalid_fields(self):
        partner = self.env["res.partner"].create({
            "name": "Generic Update Partner",
            "email": "before.update@example.com",
            "phone": "+49 000 111",
        })
        tool_service = self.env["ob.ai.tool.service"]
        updated = tool_service.tool_odoo_update_records(
            user=self.env.user,
            model="res.partner",
            record_ids=[partner.id],
            values={"email": "after.update@example.com"},
            dry_run=False,
        )
        self.assertTrue(updated["ok"])
        self.assertEqual(updated["updated_count"], 1)
        self.assertEqual(partner.email, "after.update@example.com")

        blocked = tool_service.tool_odoo_update_records(
            user=self.env.user,
            model="res.partner",
            record_ids=[partner.id],
            values={"field_does_not_exist": "x"},
            dry_run=False,
        )
        self.assertFalse(blocked["ok"])
        self.assertIn("unknown", blocked["error"].lower())

    def test_tool_odoo_call_method_can_run_business_button(self):
        partner = self.env["res.partner"].create({
            "name": "Archive Candidate",
            "email": "archive.candidate@example.com",
            "active": True,
        })
        result = self.env["ob.ai.tool.service"].tool_odoo_call_method(
            user=self.env.user,
            model="res.partner",
            method="action_archive",
            record_id=partner.id,
            dry_run=False,
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["target_count"], 1)
        self.assertFalse(partner.active)

    def test_access_template_can_reduce_models_and_fields(self):
        self.env["ob.ai.allowed.model"].ensure_default_models()
        limited_user = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "AI Template User",
            "login": "ai.template.user",
            "email": "ai.template.user@example.com",
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id, self.ai_user_group.id])],
        })
        template = self.env["ob.ai.access.template"].create({
            "name": "Partner Only Template",
            "user_ids": [(6, 0, [limited_user.id])],
        })
        partner_line = template.line_ids.filtered(lambda line: line.allowed_model_id == self.allowed_partner_model)[:1]
        self.assertTrue(partner_line)
        visible_fields = self.env["ir.model.fields"].search([
            ("model_id", "=", self.allowed_partner_model.model_id.id),
            ("name", "in", ["name", "email"]),
        ])
        phone_field = self.env["ir.model.fields"].search([
            ("model_id", "=", self.allowed_partner_model.model_id.id),
            ("name", "=", "phone"),
        ], limit=1)
        (template.line_ids - partner_line).write({"active": False})
        partner_line.write({
            "active": True,
            "allowed_field_ids": [(6, 0, visible_fields.ids)],
            "blocked_field_ids": [(6, 0, phone_field.ids)],
        })

        access_service = self.env["ob.ai.access.service"].with_user(limited_user)
        available_models = access_service.available_allowed_models()
        self.assertEqual(available_models.mapped("model_id.model"), ["res.partner"])
        context = access_service.build_record_context(self.partner, allowed_model=self.allowed_partner_model)
        row = context["records"][0]
        self.assertEqual(row["name"], "AI Test Customer")
        self.assertEqual(row["email"], "ai.customer@example.com")
        self.assertNotIn("phone", row)
        with self.assertRaises(UserError):
            access_service.get_allowed_model("sale.order")

    def test_available_allowed_models_auto_syncs_missing_template_lines(self):
        self.env["ob.ai.allowed.model"].ensure_default_models()
        limited_user = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "AI Template Sync User",
            "login": "ai.template.sync.user",
            "email": "ai.template.sync.user@example.com",
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id, self.ai_user_group.id])],
        })
        template = self.env["ob.ai.access.template"].create({
            "name": "Template Auto Sync",
            "user_ids": [(6, 0, [limited_user.id])],
        })
        validation_allowed_model = self.env["ob.ai.allowed.model"].search(
            [("model_id.model", "=", "ob.ai.validation.result")],
            limit=1,
        )
        self.assertTrue(validation_allowed_model)
        stale_line = template.line_ids.filtered(
            lambda line: line.allowed_model_id == validation_allowed_model
        )[:1]
        self.assertTrue(stale_line)
        stale_line.unlink()
        self.assertFalse(
            template.line_ids.filtered(lambda line: line.allowed_model_id == validation_allowed_model)
        )

        access_service = self.env["ob.ai.access.service"].with_user(limited_user)
        available_models = access_service.available_allowed_models()

        self.assertIn("ob.ai.validation.result", available_models.mapped("model_id.model"))
        self.assertTrue(
            template.line_ids.filtered(lambda line: line.allowed_model_id == validation_allowed_model)
        )

    def test_tool_list_models_respects_template_scope(self):
        self.env["ob.ai.allowed.model"].ensure_default_models()
        limited_user = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "AI Models Scope User",
            "login": "ai.models.scope.user",
            "email": "ai.models.scope.user@example.com",
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id, self.ai_user_group.id])],
        })
        template = self.env["ob.ai.access.template"].create({
            "name": "Model Scope Template",
            "user_ids": [(6, 0, [limited_user.id])],
        })
        partner_line = template.line_ids.filtered(lambda line: line.allowed_model_id == self.allowed_partner_model)[:1]
        self.assertTrue(partner_line)
        (template.line_ids - partner_line).write({"active": False})
        partner_line.write({"active": True})

        payload = self.env["ob.ai.tool.service"].tool_list_models(user=limited_user)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["models"][0]["model"], "res.partner")

    def test_admin_full_access_can_auto_allow_models_in_tool_handlers(self):
        self.env["ob.ai.allowed.model"].ensure_default_models()
        full_access_template = self.env["ob.ai.access.template"].create({
            "name": "Admin Full Access Template",
            "allow_full_access": True,
            "user_ids": [(6, 0, [self.env.user.id])],
        })
        self.assertTrue(full_access_template.allow_full_access)

        candidates = ["res.currency.rate", "mail.followers", "utm.source", "crm.tag", "project.task"]
        target_model = False
        allowed_model_obj = self.env["ob.ai.allowed.model"]
        for candidate in candidates:
            if candidate not in self.env:
                continue
            if not allowed_model_obj.search([("model_id.model", "=", candidate), ("active", "=", True)], limit=1):
                target_model = candidate
                break
        if not target_model:
            self.skipTest("No non-whitelisted candidate model is available in this database.")

        result = self.env["ob.ai.tool.service"].tool_odoo_count(
            user=self.env.user,
            model=target_model,
            domain=[],
        )
        self.assertTrue(result["ok"])
        self.assertTrue(
            allowed_model_obj.search([("model_id.model", "=", target_model), ("active", "=", True)], limit=1)
        )

    def test_communication_service_dispatch_tool_calls_with_action_scope(self):
        full_access_template = self.env["ob.ai.access.template"].create({
            "name": "Gateway Action Template",
            "allow_full_access": True,
            "user_ids": [(6, 0, [self.env.user.id])],
        })
        self.assertTrue(full_access_template.allow_full_access)
        communication_service = self.env["ob.ai.communication.service"]
        issued = communication_service.issue_request_token(
            conversation=False,
            scopes=["read_context", "read_schema", "execute_actions"],
            request_kind="action_proposal",
            ttl_minutes=10,
        )
        token_value = issued["token"]

        dispatch_result = communication_service.dispatch_tool_calls(
            token_value,
            [{
                "tool": "odoo_count",
                "arguments": {"model": "res.partner", "domain": []},
            }],
            max_requests=5,
        )
        self.assertEqual(dispatch_result["count"], 1)
        self.assertEqual(dispatch_result["results"][0]["status"], "success")
        self.assertEqual(dispatch_result["results"][0]["tool"], "odoo_count")
        self.assertTrue(dispatch_result["results"][0]["data"]["ok"])

    def test_generic_investigation_summarizes_related_partner_record(self):
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Generic Partner Investigation",
            "allowed_model_id": self.allowed_partner_model.id,
            "related_record_ref": "res.partner,%s" % self.partner.id,
        })
        result = self.env["ob.ai.assistant.service"].generate_response(
            conversation,
            "Give me a customer briefing.",
            provider=False,
            model=False,
        )
        audit_log = self.env["ob.ai.assistant.service"].create_audit_log(
            conversation,
            False,
            False,
            "Give me a customer briefing.",
            result=result,
            status="success",
            context_bundle=result.get("context_bundle"),
        )
        trace = self.env["ob.ai.investigation.trace"].browse(result["investigation_trace_id"])

        self.assertEqual(result["intent_code"], "generic_investigation")
        self.assertEqual(result["related_model"], "res.partner")
        self.assertEqual(
            self.env["ob.ai.allowed.model"].browse(result["allowed_model_id"]).model_id.model,
            "res.partner",
        )
        self.assertIn("briefing", result["text"].lower())
        self.assertIn("visible records: 1", result["text"].lower())
        self.assertIn("ai test customer", result["text"].lower())
        self.assertTrue(trace)
        self.assertEqual(trace.conversation_id, conversation)
        self.assertEqual(trace.audit_log_id, audit_log)
        self.assertEqual(audit_log.investigation_trace_id, trace)
        self.assertTrue(trace.steps_json)

    def test_generic_investigation_persists_memory_state_and_result_refs(self):
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Generic Memory Capture",
            "allowed_model_id": self.allowed_partner_model.id,
            "related_record_ref": "res.partner,%s" % self.partner.id,
        })
        result = self.env["ob.ai.assistant.service"].generate_response(
            conversation,
            "Give me a customer briefing.",
            provider=False,
            model=False,
        )

        memory_state = self.env["ob.ai.memory.state"].browse(result["memory_state_id"])
        self.assertTrue(memory_state)
        self.assertEqual(memory_state.status, "valid")
        self.assertEqual(memory_state.intent_code, "generic_investigation")
        self.assertEqual(memory_state.operation_type, "summary")
        self.assertEqual(memory_state.target_model_name, "res.partner")
        self.assertEqual(memory_state.last_trace_id.id, result["investigation_trace_id"])
        self.assertIn("res.partner,%s" % self.partner.id, memory_state.result_record_refs)
        self.assertTrue(memory_state.result_reference_ids)
        self.assertEqual(memory_state.result_reference_ids[:1].record_ref, "res.partner,%s" % self.partner.id)

    def test_generic_follow_up_reuses_previous_trace_context(self):
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Generic Follow-up Investigation",
            "allowed_model_id": self.allowed_partner_model.id,
        })
        assistant_service = self.env["ob.ai.assistant.service"]
        first_result = assistant_service.generate_response(
            conversation,
            "How many customers are visible right now?",
            provider=False,
            model=False,
        )
        conversation.write({
            "last_route_payload": first_result["route_context"],
            "intent_code": first_result["intent_code"],
            "last_investigation_trace_id": first_result["investigation_trace_id"],
        })
        second_result = assistant_service.generate_response(
            conversation,
            "list them",
            provider=False,
            model=False,
        )

        first_trace = self.env["ob.ai.investigation.trace"].browse(first_result["investigation_trace_id"])
        second_trace = self.env["ob.ai.investigation.trace"].browse(second_result["investigation_trace_id"])
        self.assertEqual(first_result["intent_code"], "generic_investigation")
        self.assertEqual(second_result["intent_code"], "generic_investigation")
        self.assertEqual(first_trace.operation_type, "count")
        self.assertEqual(second_trace.operation_type, "list")
        self.assertEqual(second_trace.parent_trace_id, first_trace)
        self.assertEqual(second_result["route_context"]["generic_query_type"], "list")
        self.assertEqual(second_result["route_context"]["generic_trace_id"], second_trace.id)
        self.assertIn("matching your request", second_result["text"].lower())

    def test_generic_follow_up_can_use_memory_state_when_route_payload_is_cleared(self):
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Generic Memory Follow-up",
            "allowed_model_id": self.allowed_partner_model.id,
        })
        assistant_service = self.env["ob.ai.assistant.service"]
        first_result = assistant_service.generate_response(
            conversation,
            "How many customers are visible right now?",
            provider=False,
            model=False,
        )
        conversation.write({
            "last_route_payload": {},
            "last_memory_state_id": first_result["memory_state_id"],
            "last_investigation_trace_id": first_result["investigation_trace_id"],
            "intent_code": first_result["intent_code"],
        })
        second_result = assistant_service.generate_response(
            conversation,
            "list them",
            provider=False,
            model=False,
        )

        first_trace = self.env["ob.ai.investigation.trace"].browse(first_result["investigation_trace_id"])
        second_trace = self.env["ob.ai.investigation.trace"].browse(second_result["investigation_trace_id"])
        second_memory_state = self.env["ob.ai.memory.state"].browse(second_result["memory_state_id"])
        self.assertEqual(second_result["intent_code"], "generic_investigation")
        self.assertEqual(second_trace.parent_trace_id, first_trace)
        self.assertEqual(second_result["route_context"]["generic_memory_state_id"], second_memory_state.id)
        self.assertEqual(second_memory_state.parent_memory_state_id.id, first_result["memory_state_id"])
        self.assertIn("matching your request", second_result["text"].lower())

    def test_generic_follow_up_reuses_memory_search_term_filters(self):
        if "crm.lead" not in self.env:
            self.skipTest("CRM is not installed in this test database.")
        self.env["ob.ai.allowed.model"].ensure_default_models()
        crm_allowed_model = self.env["ob.ai.allowed.model"].search([("model_id.model", "=", "crm.lead")], limit=1)
        self.assertTrue(crm_allowed_model)
        template = self.env["ob.ai.access.template"].create({
            "name": "CRM Memory Filter Template",
            "user_ids": [(6, 0, [self.env.user.id])],
        })
        crm_line = template.line_ids.filtered(lambda line: line.allowed_model_id == crm_allowed_model)[:1]
        self.assertTrue(crm_line)
        crm_fields = self.env["ir.model.fields"].search([
            ("model_id", "=", crm_allowed_model.model_id.id),
            ("name", "in", ["name", "stage_id", "type", "expected_revenue", "probability", "user_id"]),
        ])
        crm_line.write({
            "allowed_field_ids": [(6, 0, crm_fields.ids)],
            "max_record_count": 10,
            "search_limit": 10,
        })
        filtered_stages = self.env["crm.stage"].create([
            {"name": "AI Memory Stage One"},
            {"name": "AI Memory Stage Two"},
        ])
        outside_stage = self.env["crm.stage"].create({"name": "AI Memory Outside Stage"})
        self.env["crm.lead"].create({
            "name": "AI Memory Deal Alpha",
            "type": "opportunity",
            "stage_id": filtered_stages[0].id,
            "user_id": self.env.user.id,
            "probability": 30.0,
        })
        self.env["crm.lead"].create({
            "name": "AI Memory Deal Beta",
            "type": "opportunity",
            "stage_id": filtered_stages[1].id,
            "user_id": self.env.user.id,
            "probability": 70.0,
        })
        self.env["crm.lead"].create({
            "name": "Outside Memory Deal",
            "type": "opportunity",
            "stage_id": outside_stage.id,
            "user_id": self.env.user.id,
            "probability": 15.0,
        })
        conversation = self.env["ob.ai.conversation"].create({
            "name": "CRM Memory Search Filters",
            "allowed_model_id": crm_allowed_model.id,
        })
        assistant_service = self.env["ob.ai.assistant.service"]
        first_result = assistant_service.generate_response(
            conversation,
            'What is the average probability for "AI Memory Deal"?',
            provider=False,
            model=False,
        )
        conversation.write({
            "last_route_payload": {},
            "last_memory_state_id": first_result["memory_state_id"],
            "last_investigation_trace_id": first_result["investigation_trace_id"],
            "intent_code": first_result["intent_code"],
        })
        second_result = assistant_service.generate_response(
            conversation,
            "show them by stage with probability",
            provider=False,
            model=False,
        )

        self.assertEqual(second_result["intent_code"], "generic_investigation")
        self.assertEqual(second_result["route_context"]["generic_query_type"], "group")
        self.assertEqual(second_result["route_context"]["search_term"], "ai memory deal")
        self.assertIn(filtered_stages[0].name, second_result["text"])
        self.assertIn(filtered_stages[1].name, second_result["text"])
        self.assertNotIn(outside_stage.name, second_result["text"])

    def test_memory_backed_followup_can_create_activities_for_last_result_set(self):
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Memory Backed Activities",
            "provider_id": self.provider_openai.id,
            "model_id": self.model_openai.id,
            "allowed_model_id": self.allowed_partner_model.id,
            "prompt_input": "How many customers are visible right now?",
        })
        provider_payloads = [
            MockResponse(self._provider_payload("Customer visibility generated.", response_id="resp_memory_1")),
            MockResponse(self._provider_payload("Activities prepared.", response_id="resp_memory_2")),
        ]
        with patch(
            "odoo.addons.ob_ai_assistant.services.ob_ai_provider_service.requests.post",
            side_effect=provider_payloads,
        ):
            conversation.action_send_prompt()
            first_memory_state = conversation.last_memory_state_id
            self.assertTrue(first_memory_state)
            result_partner_ids = first_memory_state.result_reference_ids.filtered(
                lambda reference: reference.model_name == "res.partner"
            ).mapped("record_id_value")
            self.assertTrue(result_partner_ids)
            activity_count_before = self.env["mail.activity"].search_count([
                ("res_model", "=", "res.partner"),
                ("res_id", "in", result_partner_ids),
                ("ob_ai_generated", "=", True),
            ])
            conversation.write({
                "last_route_payload": {},
                "prompt_input": "Create activities for them and tell the responsible person to review this today.",
            })
            conversation.action_send_prompt()

        activity_count_after = self.env["mail.activity"].search_count([
            ("res_model", "=", "res.partner"),
            ("res_id", "in", result_partner_ids),
            ("ob_ai_generated", "=", True),
        ])
        self.assertGreaterEqual(activity_count_after, activity_count_before + 1)
        self.assertEqual(conversation.last_memory_state_id, first_memory_state)
        assistant_message = conversation.ai_message_ids.sorted("id")[-1]
        self.assertIn("last ai result set", assistant_message.content.lower())
        activity = self.env["mail.activity"].search([
            ("res_model", "=", "res.partner"),
            ("res_id", "in", result_partner_ids),
            ("ob_ai_generated", "=", True),
        ], order="id desc", limit=1)
        self.assertTrue(activity)
        self.assertIn("latest ai result set", (activity.note or "").lower())
        self.assertIn("requested action", (activity.note or "").lower())

    def test_memory_backed_followup_can_create_reminders_for_last_result_set(self):
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Memory Backed Reminders",
            "provider_id": self.provider_openai.id,
            "model_id": self.model_openai.id,
            "allowed_model_id": self.allowed_partner_model.id,
            "prompt_input": "How many customers are visible right now?",
        })
        provider_payloads = [
            MockResponse(self._provider_payload("Customer visibility generated.", response_id="resp_memory_reminder_1")),
            MockResponse(self._provider_payload("Reminders prepared.", response_id="resp_memory_reminder_2")),
        ]
        with patch(
            "odoo.addons.ob_ai_assistant.services.ob_ai_provider_service.requests.post",
            side_effect=provider_payloads,
        ):
            conversation.action_send_prompt()
            first_memory_state = conversation.last_memory_state_id
            result_refs = first_memory_state.result_reference_ids.filtered(
                lambda reference: reference.model_name == "res.partner"
            ).mapped("record_ref")
            self.assertTrue(result_refs)
            reminder_count_before = self.env["ob.ai.reminder"].search_count([
                ("related_record_ref", "in", result_refs),
                ("created_by_ai", "=", True),
            ])
            conversation.write({
                "last_route_payload": {},
                "prompt_input": "Remind me tomorrow to follow up with them.",
            })
            conversation.action_send_prompt()

        reminder_count_after = self.env["ob.ai.reminder"].search_count([
            ("related_record_ref", "in", result_refs),
            ("created_by_ai", "=", True),
        ])
        self.assertGreaterEqual(reminder_count_after, reminder_count_before + 1)
        self.assertEqual(conversation.last_memory_state_id, first_memory_state)
        assistant_message = conversation.ai_message_ids.sorted("id")[-1]
        self.assertIn("last ai result set", assistant_message.content.lower())
        reminder = self.env["ob.ai.reminder"].search([
            ("related_record_ref", "in", result_refs),
            ("created_by_ai", "=", True),
        ], order="id desc", limit=1)
        self.assertTrue(reminder)
        self.assertIn("last ai result set", (reminder.reminder_text or "").lower())

    def test_memory_backed_followup_can_post_chatter_for_last_result_set(self):
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Memory Backed Chatter",
            "provider_id": self.provider_openai.id,
            "model_id": self.model_openai.id,
            "allowed_model_id": self.allowed_partner_model.id,
            "prompt_input": "How many customers are visible right now?",
        })
        provider_payloads = [
            MockResponse(self._provider_payload("Customer visibility generated.", response_id="resp_memory_chatter_1")),
            MockResponse(self._provider_payload("Notes prepared.", response_id="resp_memory_chatter_2")),
        ]
        with patch(
            "odoo.addons.ob_ai_assistant.services.ob_ai_provider_service.requests.post",
            side_effect=provider_payloads,
        ):
            conversation.action_send_prompt()
            first_memory_state = conversation.last_memory_state_id
            result_partner_ids = first_memory_state.result_reference_ids.filtered(
                lambda reference: reference.model_name == "res.partner"
            ).mapped("record_id_value")
            self.assertTrue(result_partner_ids)
            message_count_before = self.env["mail.message"].search_count([
                ("model", "=", "res.partner"),
                ("res_id", "in", result_partner_ids),
                ("body", "ilike", "latest AI result set"),
            ])
            conversation.write({
                "last_route_payload": {},
                "prompt_input": "Post a note on them that we reviewed this today.",
            })
            conversation.action_send_prompt()

        message_count_after = self.env["mail.message"].search_count([
            ("model", "=", "res.partner"),
            ("res_id", "in", result_partner_ids),
            ("body", "ilike", "latest AI result set"),
        ])
        self.assertGreaterEqual(message_count_after, message_count_before + 1)
        self.assertEqual(conversation.last_memory_state_id, first_memory_state)
        assistant_message = conversation.ai_message_ids.sorted("id")[-1]
        self.assertIn("last ai result set", assistant_message.content.lower())
        message = self.env["mail.message"].search([
            ("model", "=", "res.partner"),
            ("res_id", "in", result_partner_ids),
            ("body", "ilike", "latest AI result set"),
        ], order="id desc", limit=1)
        self.assertTrue(message)
        self.assertIn("requested note", (message.body or "").lower())

    def test_full_access_template_bypasses_line_reductions(self):
        self.env["ob.ai.allowed.model"].ensure_default_models()
        admin_template_user = self.env["res.users"].with_context(no_reset_password=True).create({
            "name": "AI Admin Template User",
            "login": "ai.admin.template.user",
            "email": "ai.admin.template.user@example.com",
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id, self.ai_user_group.id])],
        })
        template = self.env["ob.ai.access.template"].create({
            "name": "Admin Full Access Template",
            "allow_full_access": True,
            "user_ids": [(6, 0, [admin_template_user.id])],
        })
        partner_line = template.line_ids.filtered(lambda line: line.allowed_model_id == self.allowed_partner_model)[:1]
        self.assertTrue(partner_line)
        visible_fields = self.env["ir.model.fields"].search([
            ("model_id", "=", self.allowed_partner_model.model_id.id),
            ("name", "in", ["name", "email"]),
        ])
        phone_field = self.env["ir.model.fields"].search([
            ("model_id", "=", self.allowed_partner_model.model_id.id),
            ("name", "=", "phone"),
        ], limit=1)
        (template.line_ids - partner_line).write({"active": False})
        partner_line.write({
            "active": True,
            "allowed_field_ids": [(6, 0, visible_fields.ids)],
            "blocked_field_ids": [(6, 0, phone_field.ids)],
        })

        access_service = self.env["ob.ai.access.service"].with_user(admin_template_user)
        self.assertTrue(access_service.user_has_full_access())
        self.assertGreater(len(access_service.available_allowed_models()), 1)
        partner_policy = access_service.get_model_access_policy(self.allowed_partner_model)
        self.assertEqual(partner_policy["source"], "full_access_template")
        context = access_service.build_record_context(self.partner, allowed_model=self.allowed_partner_model)
        row = context["records"][0]
        self.assertEqual(row["name"], "AI Test Customer")
        self.assertEqual(row["phone"], "+49 123 456 789")

    def test_provider_failure_falls_back_to_deterministic_answer(self):
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Fallback Dashboard",
            "provider_id": self.provider_openai.id,
            "model_id": self.model_openai.id,
            "allowed_model_id": self.allowed_partner_model.id,
            "prompt_input": "How many customers are visible right now?",
        })
        with patch(
            "odoo.addons.ob_ai_assistant.services.ob_ai_provider_service.OBAIProviderService.generate_text",
            side_effect=UserError("Provider temporarily unavailable"),
        ):
            conversation.action_send_prompt()

        self.assertEqual(conversation.state, "done")
        self.assertTrue(conversation.last_investigation_trace_id)
        assistant_message = conversation.ai_message_ids.sorted("id")[-1]
        self.assertIn("visible records", assistant_message.content.lower())
        self.assertIn("provider temporarily unavailable", conversation.audit_log_ids.sorted("id")[-1].warning_message.lower())

    def test_audit_log_serializes_datetime_json_payloads(self):
        params = self.env["ir.config_parameter"].sudo()
        params.set_param("ob_ai_assistant.store_raw_payload", True)
        conversation = self.env["ob.ai.conversation"].create({
            "name": "Raw Audit Payload",
        })
        timestamp = fields.Datetime.now()
        context_bundle = {
            "source": "recent_records",
            "records": [{
                "display_name": "SO0001",
                "date_order": timestamp,
            }],
            "documents": [{
                "name": "delivery-note.txt",
                "generated_on": timestamp.date(),
            }],
            "accessed_models": ["sale.order"],
            "accessed_record_ids": {"sale.order": [1]},
            "accessed_fields": {"sale.order": ["display_name", "date_order"]},
            "blocked_fields": {"sale.order": []},
            "hidden_record_count": 0,
        }
        result = {
            "text": "Serialized safely.",
            "related_record_refs": ["sale.order,1"],
            "request_payload": {"generated_at": timestamp},
            "response_payload": {"received_at": timestamp},
        }

        try:
            audit_log = self.env["ob.ai.assistant.service"].create_audit_log(
                conversation,
                self.provider_openai,
                self.model_openai,
                "Show raw payloads",
                result=result,
                status="success",
                context_bundle=context_bundle,
            )
        finally:
            params.set_param("ob_ai_assistant.store_raw_payload", "False")

        self.assertEqual(
            audit_log.context_payload["records"][0]["date_order"],
            fields.Datetime.to_string(timestamp),
        )
        self.assertEqual(
            audit_log.context_payload["documents"][0]["generated_on"],
            fields.Date.to_string(timestamp.date()),
        )
        self.assertEqual(
            audit_log.request_payload["generated_at"],
            fields.Datetime.to_string(timestamp),
        )
        self.assertEqual(
            audit_log.response_payload["received_at"],
            fields.Datetime.to_string(timestamp),
        )
