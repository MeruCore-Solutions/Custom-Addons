# -*- coding: utf-8 -*-
{
    "name": "AI Assistant",
    "version": "19.0.1.0.0",
    "summary": "Advanced AI orchestration layer for Odoo with ChatGPT/Claude, secure tools, audit, approvals, and KPIs",
    "description": """
Smart AI Tool for Odoo 19
=========================

This module adds a governed AI workspace to Odoo with both conversational
assistance and deterministic ERP logic.

Key capabilities
----------------

* ChatGPT (OpenAI) and Claude (Anthropic) provider support
* Selectable AI models per provider
* Conversation workspace with message history inside Odoo
* True AI orchestration runtime with planner + secure query/count/aggregate/group tools
* Safe allowed-model and allowed-field whitelisting
* Deterministic sales, delivery, KPI, and ranking answers
* Reminder, activity, chatter, and approval workflows
* Validation rules and validation result tracking
* Document-context extraction for related attachments
* Audit logs with provider, model, tokens, latency, and action metadata

Why it is different
-------------------

The module is designed so Odoo remains the system of record.
Important operational answers come from real Odoo calculations before the AI
provider adds narrative quality. Access rights, action permissions, and human
approval rules are respected throughout the flow.

Business examples
-----------------

* What is my current month sales?
* What are my delivered sales for this month?
* Which is the most selling product in the current month?
* What are the delivery orders we need to process today?
* Create activities for the responsible users.
* Show me the invoices that are overdue today.
* Validate this record and tell me what is missing.

Governance controls
-------------------

* Explicit allowed-model configuration
* Explicit allowed-field configuration
* Optional human approval for sensitive actions
* Retention controls for prompts and responses
* Optional raw payload storage
* Duplicate prevention with idempotency keys

This makes the addon suitable for teams that want practical AI automation in
Odoo without losing traceability, access control, or business discipline.
""",
    "category": "Productivity",
    "author": "OpenAI Codex",
    "license": "AGPL-3",
    "depends": [
        "base_setup",
        "mail",
        "bus",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/ob_ai_provider_data.xml",
        "data/ob_ai_model_data.xml",
        "data/ob_ai_config_data.xml",
        "data/ob_ai_prompt_template_data.xml",
        "data/ob_ai_kpi_data.xml",
        "data/ob_ai_tool_data.xml",
        "data/ir_cron.xml",
        "views/ob_ai_provider_views.xml",
        "views/ob_ai_access_template_views.xml",
        "views/ob_ai_allowed_model_views.xml",
        "views/ob_ai_model_semantic_views.xml",
        "views/ob_ai_schema_registry_views.xml",
        "views/ob_ai_investigation_trace_views.xml",
        "views/ob_ai_memory_state_views.xml",
        "views/ob_ai_prompt_template_views.xml",
        "views/ob_ai_reminder_views.xml",
        "views/ob_ai_approval_views.xml",
        "views/ob_ai_validation_views.xml",
        "views/ob_ai_dashboard_views.xml",
        "views/ob_ai_document_context_views.xml",
        "views/ob_ai_conversation_views.xml",
        "views/ob_ai_audit_log_views.xml",
        "views/res_config_settings_views.xml",
        "views/ob_ai_kpi_definition_views.xml",
        "views/ob_ai_benchmark_views.xml",
        "views/ob_ai_analytics_views.xml",
        "views/ob_ai_tool_views.xml",
        "views/menu_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "ob_ai_assistant/static/src/js/ob_ai_conversation_scroll.js",
            "ob_ai_assistant/static/src/js/ob_ai_live_stream.js",
            "ob_ai_assistant/static/src/scss/ob_ai_conversation.scss",
            "ob_ai_assistant/static/src/scss/ob_ai_live_stream.scss",
        ],
    },
    "installable": True,
    "application": True,
}
