from odoo import _, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = "res.config.settings"

    ai_assistant_enabled = fields.Boolean(string="Enable AI Assistant")
    ai_default_provider_id = fields.Many2one("ob.ai.provider", string="Default AI Provider")
    ai_default_model_id = fields.Many2one(
        "ob.ai.model",
        string="Default Model",
        domain="[('provider_id', '=', ai_default_provider_id)]",
    )
    ai_service_user_id = fields.Many2one("res.users", string="AI Service User")
    ai_request_timeout = fields.Integer(string="Request Timeout (seconds)", default=60)
    ai_max_retries = fields.Integer(string="Maximum Retries", default=1)
    ai_max_prompt_chars = fields.Integer(string="Maximum Prompt Size", default=6000)
    ai_max_response_chars = fields.Integer(string="Maximum Response Size", default=6000)
    ai_document_summary_enabled = fields.Boolean(string="Enable Document Summaries", default=True)
    ai_conversation_summary_enabled = fields.Boolean(string="Enable Conversation Summaries", default=True)
    ai_allow_chatter_posting = fields.Boolean(string="Allow Chatter Posting")
    ai_allow_activity_creation = fields.Boolean(string="Allow Activity Creation")
    ai_allow_reminder_creation = fields.Boolean(string="Allow Reminder Creation")
    ai_dashboard_enabled = fields.Boolean(string="Enable Dashboard Generation")
    ai_validation_enabled = fields.Boolean(string="Enable Validation Suggestions")
    ai_generic_engine_enabled = fields.Boolean(string="Enable Generic Schema Engine", default=True)
    ai_true_ai_orchestration_enabled = fields.Boolean(string="Enable True AI Orchestration", default=True)
    ai_orchestrator_force_for_all = fields.Boolean(string="Force Agentic AI for Read Queries", default=True)
    ai_orchestrator_force_for_admin = fields.Boolean(string="Force Agentic AI for Administrators", default=True)
    ai_admin_global_scope_enabled = fields.Boolean(string="Admin Global Scope Mode", default=True)
    ai_schema_auto_refresh_enabled = fields.Boolean(string="Auto Refresh Schema Registry", default=True)
    ai_semantic_auto_sync_enabled = fields.Boolean(string="Auto Sync Model Semantics", default=True)
    ai_orchestrator_max_iterations = fields.Integer(string="Orchestrator Max Iterations", default=2)
    ai_orchestrator_max_tools = fields.Integer(string="Orchestrator Max Tool Requests", default=12)
    ai_request_token_ttl_minutes = fields.Integer(string="Request Token TTL (minutes)", default=15)
    ai_gateway_enabled = fields.Boolean(string="Enable Communication Gateway", default=True)
    ai_gateway_require_signature = fields.Boolean(string="Require Signed Gateway Requests", default=True)
    ai_gateway_max_clock_skew_seconds = fields.Integer(string="Gateway Clock Skew (seconds)", default=180)
    ai_gateway_allow_action_scope = fields.Boolean(string="Allow Gateway Action Scope", default=True)
    ai_gateway_action_scope_admin_only = fields.Boolean(string="Gateway Actions for Admin Full Access Only", default=True)
    ai_gateway_auto_action_scope = fields.Boolean(string="Auto-add Action Scope to Chat Tokens", default=True)
    ai_max_investigation_steps = fields.Integer(string="Maximum Investigation Steps", default=3)
    ai_max_models_per_request = fields.Integer(string="Maximum Models per Investigation", default=6)
    ai_max_records_per_fetch = fields.Integer(string="Maximum Records per Fetch", default=25)
    ai_schema_snapshot_retention = fields.Integer(string="Schema Snapshot Retention", default=5)
    ai_human_approval_required = fields.Boolean(string="Require Human Approval", default=True)
    ai_prompt_retention_days = fields.Integer(string="Prompt Retention (days)", default=30)
    ai_response_retention_days = fields.Integer(string="Response Retention (days)", default=30)
    ai_store_raw_payload = fields.Boolean(string="Store Raw Request and Response Payloads", default=True)
    ai_shared_data_retention_days = fields.Integer(string="Shared AI Data Retention (days)", default=1095)
    ai_document_extract_max_chars = fields.Integer(string="Document Extraction Max Characters", default=20000)
    ai_document_extract_max_rows = fields.Integer(string="Document Extraction Max Rows", default=500)
    ai_document_extract_max_tables = fields.Integer(string="Document Extraction Max Tables", default=5)
    ai_feature_flags = fields.Text(string="Experimental Feature Flags")
    ai_openai_api_key = fields.Char(string="OpenAI API Key")
    ai_anthropic_api_key = fields.Char(string="Anthropic API Key")

    def get_values(self):
        values = super().get_values()
        params = self.env["ir.config_parameter"].sudo()
        provider_id = params.get_param("ob_ai_assistant.default_provider_id", default=False)
        model_id = params.get_param("ob_ai_assistant.default_model_id", default=False)
        service_user_id = params.get_param("ob_ai_assistant.service_user_id", default=False)
        values.update({
            "ai_assistant_enabled": params.get_param("ob_ai_assistant.enabled", default="True") == "True",
            "ai_default_provider_id": int(provider_id) if provider_id else False,
            "ai_default_model_id": int(model_id) if model_id else False,
            "ai_service_user_id": int(service_user_id) if service_user_id else False,
            "ai_request_timeout": int(params.get_param("ob_ai_assistant.request_timeout", default="60")),
            "ai_max_retries": int(params.get_param("ob_ai_assistant.max_retries", default="1")),
            "ai_max_prompt_chars": int(params.get_param("ob_ai_assistant.max_prompt_chars", default="6000")),
            "ai_max_response_chars": int(params.get_param("ob_ai_assistant.max_response_chars", default="6000")),
            "ai_document_summary_enabled": params.get_param("ob_ai_assistant.document_summary_enabled", default="True") == "True",
            "ai_conversation_summary_enabled": params.get_param("ob_ai_assistant.conversation_summary_enabled", default="True") == "True",
            "ai_allow_chatter_posting": params.get_param("ob_ai_assistant.allow_chatter_posting", default="False") == "True",
            "ai_allow_activity_creation": params.get_param("ob_ai_assistant.allow_activity_creation", default="False") == "True",
            "ai_allow_reminder_creation": params.get_param("ob_ai_assistant.allow_reminder_creation", default="False") == "True",
            "ai_dashboard_enabled": params.get_param("ob_ai_assistant.dashboard_enabled", default="False") == "True",
            "ai_validation_enabled": params.get_param("ob_ai_assistant.validation_enabled", default="False") == "True",
            "ai_generic_engine_enabled": params.get_param("ob_ai_assistant.generic_engine_enabled", default="True") == "True",
            "ai_true_ai_orchestration_enabled": params.get_param("ob_ai_assistant.true_ai_orchestration_enabled", default="True") == "True",
            "ai_orchestrator_force_for_all": params.get_param("ob_ai_assistant.orchestrator_force_for_all", default="True") == "True",
            "ai_orchestrator_force_for_admin": params.get_param("ob_ai_assistant.orchestrator_force_for_admin", default="True") == "True",
            "ai_admin_global_scope_enabled": params.get_param("ob_ai_assistant.admin_global_scope_enabled", default="True") == "True",
            "ai_schema_auto_refresh_enabled": params.get_param("ob_ai_assistant.schema_auto_refresh_enabled", default="True") == "True",
            "ai_semantic_auto_sync_enabled": params.get_param("ob_ai_assistant.semantic_auto_sync_enabled", default="True") == "True",
            "ai_orchestrator_max_iterations": int(
                params.get_param("ob_ai_assistant.orchestrator_max_iterations", default="2")
            ),
            "ai_orchestrator_max_tools": int(
                params.get_param("ob_ai_assistant.orchestrator_max_tools", default="12")
            ),
            "ai_request_token_ttl_minutes": int(params.get_param("ob_ai_assistant.request_token_ttl_minutes", default="15")),
            "ai_gateway_enabled": params.get_param("ob_ai_assistant.gateway_enabled", default="True") == "True",
            "ai_gateway_require_signature": params.get_param("ob_ai_assistant.gateway_require_signature", default="True") == "True",
            "ai_gateway_max_clock_skew_seconds": int(
                params.get_param(
                    "ob_ai_assistant.gateway_max_clock_skew_seconds",
                    default="180",
                )
            ),
            "ai_gateway_allow_action_scope": params.get_param("ob_ai_assistant.gateway_allow_action_scope", default="True") == "True",
            "ai_gateway_action_scope_admin_only": params.get_param("ob_ai_assistant.gateway_action_scope_admin_only", default="True") == "True",
            "ai_gateway_auto_action_scope": params.get_param("ob_ai_assistant.gateway_auto_action_scope", default="True") == "True",
            "ai_max_investigation_steps": int(params.get_param("ob_ai_assistant.max_investigation_steps", default="3")),
            "ai_max_models_per_request": int(params.get_param("ob_ai_assistant.max_models_per_request", default="6")),
            "ai_max_records_per_fetch": int(params.get_param("ob_ai_assistant.max_records_per_fetch", default="25")),
            "ai_schema_snapshot_retention": int(params.get_param("ob_ai_assistant.schema_snapshot_retention", default="5")),
            "ai_human_approval_required": params.get_param("ob_ai_assistant.human_approval_required", default="True") == "True",
            "ai_prompt_retention_days": int(params.get_param("ob_ai_assistant.prompt_retention_days", default="30")),
            "ai_response_retention_days": int(params.get_param("ob_ai_assistant.response_retention_days", default="30")),
            "ai_store_raw_payload": params.get_param("ob_ai_assistant.store_raw_payload", default="True") == "True",
            "ai_shared_data_retention_days": int(
                params.get_param("ob_ai_assistant.shared_data_retention_days", default="1095")
            ),
            "ai_document_extract_max_chars": int(
                params.get_param("ob_ai_assistant.document_extract_max_chars", default="20000")
            ),
            "ai_document_extract_max_rows": int(
                params.get_param("ob_ai_assistant.document_extract_max_rows", default="500")
            ),
            "ai_document_extract_max_tables": int(
                params.get_param("ob_ai_assistant.document_extract_max_tables", default="5")
            ),
            "ai_feature_flags": params.get_param("ob_ai_assistant.feature_flags", default=""),
            "ai_openai_api_key": params.get_param("ob_ai_assistant.openai_api_key", default=""),
            "ai_anthropic_api_key": params.get_param("ob_ai_assistant.anthropic_api_key", default=""),
        })
        return values

    def set_values(self):
        super().set_values()
        params = self.env["ir.config_parameter"].sudo()
        self._set_bool_param("ob_ai_assistant.enabled", self.ai_assistant_enabled)
        params.set_param("ob_ai_assistant.default_provider_id", self.ai_default_provider_id.id or False)
        params.set_param("ob_ai_assistant.default_model_id", self.ai_default_model_id.id or False)
        params.set_param("ob_ai_assistant.service_user_id", self.ai_service_user_id.id or False)
        params.set_param("ob_ai_assistant.request_timeout", self.ai_request_timeout or 60)
        params.set_param("ob_ai_assistant.max_retries", self.ai_max_retries or 0)
        params.set_param("ob_ai_assistant.max_prompt_chars", self.ai_max_prompt_chars or 0)
        params.set_param("ob_ai_assistant.max_response_chars", self.ai_max_response_chars or 0)
        self._set_bool_param("ob_ai_assistant.document_summary_enabled", self.ai_document_summary_enabled)
        self._set_bool_param("ob_ai_assistant.conversation_summary_enabled", self.ai_conversation_summary_enabled)
        self._set_bool_param("ob_ai_assistant.allow_chatter_posting", self.ai_allow_chatter_posting)
        self._set_bool_param("ob_ai_assistant.allow_activity_creation", self.ai_allow_activity_creation)
        self._set_bool_param("ob_ai_assistant.allow_reminder_creation", self.ai_allow_reminder_creation)
        self._set_bool_param("ob_ai_assistant.dashboard_enabled", self.ai_dashboard_enabled)
        self._set_bool_param("ob_ai_assistant.validation_enabled", self.ai_validation_enabled)
        self._set_bool_param("ob_ai_assistant.generic_engine_enabled", self.ai_generic_engine_enabled)
        self._set_bool_param("ob_ai_assistant.true_ai_orchestration_enabled", self.ai_true_ai_orchestration_enabled)
        self._set_bool_param("ob_ai_assistant.orchestrator_force_for_all", self.ai_orchestrator_force_for_all)
        self._set_bool_param("ob_ai_assistant.orchestrator_force_for_admin", self.ai_orchestrator_force_for_admin)
        self._set_bool_param("ob_ai_assistant.admin_global_scope_enabled", self.ai_admin_global_scope_enabled)
        self._set_bool_param("ob_ai_assistant.schema_auto_refresh_enabled", self.ai_schema_auto_refresh_enabled)
        self._set_bool_param("ob_ai_assistant.semantic_auto_sync_enabled", self.ai_semantic_auto_sync_enabled)
        params.set_param("ob_ai_assistant.orchestrator_max_iterations", self.ai_orchestrator_max_iterations or 2)
        params.set_param("ob_ai_assistant.orchestrator_max_tools", self.ai_orchestrator_max_tools or 12)
        params.set_param("ob_ai_assistant.request_token_ttl_minutes", self.ai_request_token_ttl_minutes or 15)
        self._set_bool_param("ob_ai_assistant.gateway_enabled", self.ai_gateway_enabled)
        self._set_bool_param("ob_ai_assistant.gateway_require_signature", self.ai_gateway_require_signature)
        params.set_param("ob_ai_assistant.gateway_max_clock_skew_seconds", self.ai_gateway_max_clock_skew_seconds or 180)
        self._set_bool_param("ob_ai_assistant.gateway_allow_action_scope", self.ai_gateway_allow_action_scope)
        self._set_bool_param("ob_ai_assistant.gateway_action_scope_admin_only", self.ai_gateway_action_scope_admin_only)
        self._set_bool_param("ob_ai_assistant.gateway_auto_action_scope", self.ai_gateway_auto_action_scope)
        params.set_param("ob_ai_assistant.max_investigation_steps", self.ai_max_investigation_steps or 3)
        params.set_param("ob_ai_assistant.max_models_per_request", self.ai_max_models_per_request or 6)
        params.set_param("ob_ai_assistant.max_records_per_fetch", self.ai_max_records_per_fetch or 25)
        params.set_param("ob_ai_assistant.schema_snapshot_retention", self.ai_schema_snapshot_retention or 5)
        self._set_bool_param("ob_ai_assistant.human_approval_required", self.ai_human_approval_required)
        params.set_param("ob_ai_assistant.prompt_retention_days", self.ai_prompt_retention_days or 0)
        params.set_param("ob_ai_assistant.response_retention_days", self.ai_response_retention_days or 0)
        self._set_bool_param("ob_ai_assistant.store_raw_payload", self.ai_store_raw_payload)
        params.set_param(
            "ob_ai_assistant.shared_data_retention_days",
            1095 if self.ai_shared_data_retention_days is None else self.ai_shared_data_retention_days,
        )
        params.set_param("ob_ai_assistant.document_extract_max_chars", self.ai_document_extract_max_chars or 20000)
        params.set_param("ob_ai_assistant.document_extract_max_rows", self.ai_document_extract_max_rows or 500)
        params.set_param("ob_ai_assistant.document_extract_max_tables", self.ai_document_extract_max_tables or 5)
        params.set_param("ob_ai_assistant.feature_flags", self.ai_feature_flags or "")
        params.set_param("ob_ai_assistant.openai_api_key", self.ai_openai_api_key or "")
        params.set_param("ob_ai_assistant.anthropic_api_key", self.ai_anthropic_api_key or "")

    def _set_bool_param(self, key, value):
        self.env["ir.config_parameter"].sudo().set_param(key, "True" if value else "False")

    def action_open_ai_providers(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("AI Providers"),
            "res_model": "ob.ai.provider",
            "view_mode": "list,form",
        }

    def action_open_ai_allowed_models(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("Allowed Models"),
            "res_model": "ob.ai.allowed.model",
            "view_mode": "list,form",
        }

    def action_open_ai_access_templates(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("Access Templates"),
            "res_model": "ob.ai.access.template",
            "view_mode": "list,form",
        }

    def action_open_ai_prompt_templates(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("Prompt Templates"),
            "res_model": "ob.ai.prompt.template",
            "view_mode": "list,form",
        }

    def action_open_ai_reminders(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("AI Reminders"),
            "res_model": "ob.ai.reminder",
            "view_mode": "list,form",
        }

    def action_open_ai_approvals(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("AI Approvals"),
            "res_model": "ob.ai.approval",
            "view_mode": "list,form",
        }

    def action_open_ai_validation_rules(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("Validation Rules"),
            "res_model": "ob.ai.validation.rule",
            "view_mode": "list,form",
        }

    def action_open_ai_validation_results(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("Validation Results"),
            "res_model": "ob.ai.validation.result",
            "view_mode": "list,form",
        }

    def action_open_ai_kpi_snapshots(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("KPI Snapshots"),
            "res_model": "ob.ai.kpi.snapshot",
            "view_mode": "list,form",
        }

    def action_open_ai_document_contexts(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("Document Contexts"),
            "res_model": "ob.ai.document.context",
            "view_mode": "list,form",
        }

    def action_open_ai_conversations(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("AI Conversations"),
            "res_model": "ob.ai.conversation",
            "view_mode": "list,form",
        }

    def action_open_ai_schema_versions(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("Schema Registry"),
            "res_model": "ob.ai.schema.version",
            "view_mode": "list,form",
        }

    def action_open_ai_request_tokens(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("Communication Tokens"),
            "res_model": "ob.ai.request.token",
            "view_mode": "list,form",
        }

    def action_open_ai_model_semantics(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("Model Semantics"),
            "res_model": "ob.ai.model.semantic",
            "view_mode": "list,form",
        }

    def action_open_ai_investigation_traces(self):
        return {
            "type": "ir.actions.act_window",
            "name": _("Investigation Traces"),
            "res_model": "ob.ai.investigation.trace",
            "view_mode": "list,form",
        }

    def action_refresh_ai_schema_registry(self):
        version = self.env["ob.ai.schema.service"].refresh_schema_registry(trigger_source="manual")
        return {
            "type": "ir.actions.act_window",
            "name": _("Schema Registry"),
            "res_model": "ob.ai.schema.version",
            "res_id": version.id,
            "view_mode": "form",
        }

    def action_sync_ai_model_semantics(self):
        self.env["ob.ai.semantic.service"].sync_semantics(force_update=True)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("AI semantics synced"),
                "message": _("The generic AI model semantics were refreshed from the current schema registry."),
                "type": "success",
                "sticky": False,
            },
        }
