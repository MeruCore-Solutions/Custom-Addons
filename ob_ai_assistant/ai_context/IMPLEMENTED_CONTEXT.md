# Implemented Context

## Module Summary
`ob_ai_assistant` is an Odoo 19 module that provides a governed AI workspace inside ERP.
It supports multi-provider AI (OpenAI ChatGPT and Anthropic Claude), selectable models, and an agent-first reasoning loop with tool calling.
Users can ask business questions, run cross-model analysis, trigger governed actions, and upload documents for extraction/import.
The module enforces allowed-model and allowed-field policies through access templates and can grant full-access mode for admin templates.
Sensitive writes are approval-gated, auditable, and idempotent-aware.
It includes a signed communication gateway (`/ob_ai/gateway/v1/*`) for secure schema/data/action exchange.
Audit retention, token lifecycle cleanup, schema refresh, and reminder cron jobs are included.

## Technical Stack
- Odoo version: 19.0 (`__manifest__.py` version `19.0.1.0.0`)
- Python models: `models/*.py` (conversation, approvals, tool catalog/calls, schema registry, analytics, memory, tokens, etc.)
- Python services: `services/*.py` (agent solver, provider abstraction, tool dispatch, access control, communication gateway logic, document parsing, actions, export)
- Controllers: `controllers/ob_ai_gateway_controller.py`
- XML views/actions/menus: `views/*.xml`
- Security:
  - Groups + record rules: `security/security.xml`
  - ACLs: `security/ir.model.access.csv`
- JS assets:
  - `static/src/js/ob_ai_conversation_scroll.js`
  - `static/src/js/ob_ai_live_stream.js`
- SCSS assets:
  - `static/src/scss/ob_ai_conversation.scss`
  - `static/src/scss/ob_ai_live_stream.scss`
- External provider APIs:
  - OpenAI Responses API (`https://api.openai.com/v1/responses`)
  - Anthropic Messages API (`https://api.anthropic.com/v1/messages`)
- Optional runtime libraries used by features:
  - `openpyxl`, `reportlab`, `Pillow`/`PIL`, `pypdf`/`PyPDF2`, `pytesseract`
  - CLI fallbacks: `pdftotext`, `tesseract`

## Main Models

### ob.ai.conversation
Purpose: Main user conversation workspace and runtime state container.
Fields:
- `name`, `chat_mode`, `context_mode` (`global`/`focused`)
- `provider_id`, `model_id`
- `allowed_model_id`, `related_record_ref`
- `chat_attachment_ids`, `prompt_input`
- `state`, `intent_code`, `intent_confidence`, `human_review_status`, `last_error`
- `last_agent_session_id`, `last_agent_session_uuid`, `last_route_payload`
Relations:
- One2many to `ob.ai.message`, `ob.ai.audit.log`, `ob.ai.reminder`, `ob.ai.approval`, `ob.ai.validation.result`, `ob.ai.document.context`, `ob.ai.investigation.trace`, `ob.ai.memory.state`
Methods:
- `action_send_prompt()`, `_get_effective_provider()`, `_get_effective_model()`, `_link_chat_attachments()`
Notes:
- Conversation action default context sets `context_mode='global'`; model default is `focused`.

### ob.ai.message
Purpose: Stores user/assistant/system messages.
Fields:
- `role`, `content`, `provider_id`, `model_id`, `agent_session_id`, `audit_log_id`
Methods:
- `_cleanup_message_retention()`
Notes:
- Retention redacts old content to `[Removed by retention policy]`.

### ob.ai.agent.session
Purpose: One agent solve run per user prompt.
Fields:
- `session_uuid`, `conversation_id`, `provider_id`, `model_id`, `user_prompt`
- `status`, `stop_reason`, `final_answer`, `reasoning_trace`
- token/latency counters and limit fields
Relations:
- One2many `step_ids` to `ob.ai.agent.step`
Notes:
- `stop_reason` supports both `final` and `final_answer` for compatibility.

### ob.ai.agent.step
Purpose: One loop step (`plan`/`tool`/`reflect`/`answer`) in agent session.
Fields:
- `sequence`, `step_type`, `reasoning_text`, `raw_message_json`
- `status`, `input_tokens`, `output_tokens`, `latency_ms`, `error_message`
Relations:
- Many2one `session_id`
- One2many `tool_call_ids` to `ob.ai.tool.call`

### ob.ai.tool
Purpose: Tool registry exposed to AI function-calling.
Fields:
- `code`, `description`, `parameters_schema`, `handler_method`
- `requires_approval`, `auto_approve_for_admin`, `required_group_ids`
- `audit_level`, `max_per_session`, `timeout_seconds`, `active`
Methods:
- `to_openai_tool_spec()`, `to_anthropic_tool_spec()`, `get_available_tools_for_user()`

### ob.ai.tool.call
Purpose: Persistent audit for every tool dispatch/execute event.
Fields:
- `tool_code`, `arguments_json`, `result_json`, `status`, `error_message`
- `conversation_id`, `session_id`, `step_id`, `approval_id`, `latency_ms`

### ob.ai.approval
Purpose: Human governance record for pending AI actions/tools.
Fields:
- `requested_by_id`, `reviewer_id`, `action_type`, `review_status`, `approval_scope`
- `action_summary`, `payload_json`, `result_message`, `idempotency_key`
- `source_conversation_id`, `related_record_ref`
Methods:
- `action_approve()`, `action_reject()`, `action_apply()`
Notes:
- Legacy normalization maps old incoming keys:
  - `summary` -> `action_summary`
  - `conversation_id` -> `source_conversation_id`
  - `user_id` -> `requested_by_id`

### ob.ai.reminder
Purpose: AI-generated reminder workflow with due processing.
Fields:
- `requesting_user_id`, `assigned_user_id`, `related_record_ref`
- `reminder_text`, `due_datetime`, `status`, `idempotency_key`, `activity_id`
Methods:
- `action_mark_done()`, `action_cancel()`, `_cron_process_due_reminders()`

### ob.ai.allowed.model
Purpose: Base whitelist + capability policy per Odoo model.
Fields:
- `model_id`, `allowed_field_ids`, `blocked_field_ids`
- `reference_field_names`, `name_field_names`, `date_field_names`
- capability flags (`allow_*`) and `require_human_approval`
Methods:
- `ensure_default_models()`, `_default_allowed_field_names()`, `_sync_dynamic_default_allowed_fields()`

### ob.ai.access.template / ob.ai.access.template.line
Purpose: Template-based user scoping over allowed models and fields.
Fields:
- Template: `user_ids`, `allow_full_access`, `line_ids`
- Line: `allowed_model_id`, allowed/blocked fields, per-model limits/capabilities
Methods:
- `action_sync_model_lines()`, `action_reset_from_allowed_model()`

### ob.ai.request.token
Purpose: Short-lived signed communication token for gateway requests.
Fields:
- `token_digest`, `token_jti`, `scope_json`, `state`, `expires_at`, `use_count`
- governance limits (`max_models_per_request`, `max_records_per_fetch`, etc.)
Methods:
- `_cron_cleanup_expired_tokens()`, `action_revoke()`

### ob.ai.audit.log
Purpose: Full audit entry for each AI exchange.
Fields:
- provider/model metadata, token/latency/token-count metrics
- context/request/response payloads
- action/result metadata
Methods:
- `_cron_apply_retention_policies()`, `_cleanup_audit_payloads()`

### ob.ai.document.context
Purpose: Cached extraction state for uploaded/related attachments.
Fields:
- `attachment_id`, `extracted_text`, `structured_payload`, counts, engine, error state

### Schema/semantic/analytics persistence models
Purpose:
- schema registry: `ob.ai.schema.version`, `.module`, `.model`, `.field`
- semantics + KPI graph: `ob.ai.model.semantic`, `ob.ai.kpi.definition`, `ob.ai.metric.formula`, `ob.ai.model.relationship`, `ob.ai.dimension.map`
- benchmark + analytics: `ob.ai.benchmark.*`, `ob.ai.health.score`, `ob.ai.forecast.run`, `ob.ai.scenario.run`, `ob.ai.kpi.snapshot`

## Main Services

### services/ob_ai_assistant_service.py
Purpose: Conversation-level entry point and audit writer.
Important methods:
- `generate_response()`
- `_solve_via_agent()`
- `create_audit_log()`
Flow:
- Validates prompt -> runs `ob.ai.agent.solver` -> shapes conversation-compatible result payload -> writes audit.
Known assumptions:
- Agent-first path is default; legacy intent/router pipeline is removed.

### services/ob_ai_agent_solver.py
Purpose: ReAct-style loop (`plan -> tool -> reflect -> ... -> final`).
Important methods:
- `solve()`, `_run_loop()`, `_emit_event()`, `_retry_on_rate_limit()`
Flow:
- Builds system prompt + history, invokes provider with tools, dispatches tool calls via `ob.ai.tool.service`, reflects, finalizes session.
Known assumptions:
- Uses DB commits during streaming to flush bus events in near real-time.

### services/ob_ai_tool_service.py
Purpose: Tool dispatcher with validation, approval gate, and tool-call audit.
Important methods:
- `dispatch()`, `_validate_arguments()`, `_queue_for_approval()`, `execute_approved()`, `render_tool_specs_for_provider()`
Inputs/outputs:
- Input: tool code + JSON args + conversation/session/step/user context.
- Output: `{status, data|error}` with persisted `ob.ai.tool.call`.
Known assumptions:
- Write tools should use `requires_approval=True` in tool data.

### services/ob_ai_tool_handlers.py
Purpose: Concrete tool implementations.
Important methods:
- read tools: `tool_odoo_search_read`, `tool_odoo_count`, `tool_odoo_aggregate`, `tool_odoo_group_by`, etc.
- write tools: `tool_odoo_create_records`, `tool_odoo_update_records`, `tool_odoo_delete_records`, `tool_odoo_call_method`
- document tools: `tool_extract_attachment_data`, `tool_import_attachment_rows`
Known assumptions:
- Uses `ob.ai.access.service` + `with_user()` and sanitizers before CRUD/method calls.

### services/ob_ai_provider_service.py
Purpose: Provider abstraction for OpenAI/Anthropic, including tool-call format conversion and retries.
Important methods:
- `invoke_with_tools()`, `generate_text()`
- `_normalize_messages_to_openai_input()`, `_normalize_messages_to_anthropic()`
Known assumptions:
- Handles 429 throttling and payload shrinking; returns graceful rate-limit text when exhausted.

### services/ob_ai_access_service.py
Purpose: AI data access control core.
Important methods:
- `available_allowed_models()`, `get_allowed_model()`, `get_model_access_policy()`, `get_allowed_field_names()`
- `build_*_context()` helpers
Known assumptions:
- Admin global scope requires both:
  - `admin_global_scope_enabled=True`
  - user in full-access template and admin/AI-admin group.

### services/ob_ai_communication_service.py
Purpose: Signed gateway contract and secure data/action operations.
Important methods:
- token lifecycle: `issue_request_token()`, `validate_request_token()`
- signature: `prepare_gateway_auth_headers()`, `validate_signed_gateway_request()`
- data: `fetch_schema_bundle*`, `fetch_record_bundle*`, `count/aggregate/group`
- action: `dispatch_tool_calls*`
Known assumptions:
- `execute_actions` scope is gated by config + admin full-access policy.

### services/ob_ai_action_service.py
Purpose: Reminder/activity/chatter workflows + approval apply logic.
Important methods:
- `create_reminder_from_prompt()`, `create_activity_from_prompt()`
- memory-based bulk variants
- `post_chatter_from_prompt()`, `apply_approved_action()`
Known assumptions:
- Uses idempotency keys and template capability checks.

### services/ob_ai_document_service.py
Purpose: Attachment extraction and structured table parsing.
Important methods:
- `build_attachment_context()`, `get_attachment_tabular_rows()`
Supported formats:
- text/csv/tsv/json, excel, pdf, image OCR
Known assumptions:
- Optional libs/CLI availability affects extraction quality.

### services/ob_ai_schema_service.py
Purpose: Schema snapshots, checksums, and ecosystem metadata.
Important methods:
- `ensure_current_schema()`, `refresh_schema_registry()`, `get_model_schema_payload()`
Known assumptions:
- Auto-refresh compares live checksum and age (`schema_max_age_hours`).

### services/ob_ai_memory_service.py
Purpose: Follow-up memory state validation and actionable record grouping.
Important methods:
- `get_valid_memory_state()`, `get_actionable_result_groups()`, `capture_investigation_state()`

### services/ob_ai_export_service.py
Purpose: KPI snapshot export to PDF/PNG attachments.
Important methods:
- `export_snapshot_assets()`, `_render_snapshot_pdf()`, `_render_snapshot_image()`

## Current Workflow
1. User opens `AI Assistant > Conversations` (`ob.ai.conversation` form).
2. User enters prompt and optional `chat_attachment_ids`.
3. `action_send_prompt()` creates user message, sets processing state.
4. `ob.ai.assistant.service.generate_response()` runs agent solver.
5. `ob.ai.agent.solver` creates `ob.ai.agent.session` + `ob.ai.agent.step`.
6. Provider call returns either final text or tool calls.
7. Tool calls are dispatched by `ob.ai.tool.service`.
8. If tool requires approval and not admin auto-approve, dispatcher queues `ob.ai.approval` + `ob.ai.tool.call(status=pending_approval)`.
9. Solver emits bus events (`ob_ai_user_<uid>` and `ob_ai_session_<uuid>`) for live stream UI.
10. Final answer is written as assistant message, audit log is created, conversation state becomes `done` or `error`.

## Approval Workflow
1. Risky tool/action is marked `requires_approval` in `ob.ai.tool` data or route.
2. Dispatcher/action service creates `ob.ai.approval` with `payload_json`, `action_summary`, scope, and idempotency key.
3. Reviewer opens `AI Assistant > Approvals`.
4. Reviewer clicks:
- `Approve` -> status `approved`
- `Reject` -> status `rejected`
- `Apply` -> executes via `ob.ai.action.service.apply_approved_action()`, then status `applied`
5. Tool-call approvals are recorded in `ob.ai.tool.call.approval_id`.

## Tool Execution Workflow
1. Tool specs are loaded from `data/ob_ai_tool_data.xml`.
2. `ob.ai.tool.service.render_tool_specs_for_provider()` converts tool schema per provider.
3. Provider emits tool call(s).
4. `dispatch()` validates:
- tool availability and group permissions
- JSON schema required/type checks
- session max-per-tool limits
5. If approval needed: queue and return `pending_approval`.
6. Else execute handler method from `ob_ai_tool_handlers.py`.
7. Persist `ob.ai.tool.call` audit record with result/error and latency.

## Provider / Model Abstraction
- Providers in `ob.ai.provider`:
  - `openai` uses Responses API
  - `anthropic` uses Messages API
- Models in `ob.ai.model` are provider-scoped via `provider_id`.
- Conversation picks effective provider/model from explicit fields or global defaults (`ir.config_parameter`).
- On throttle/failure, assistant service can fallback to another active provider/model if available.

## Views and Menus
Key user-facing views:
- `views/ob_ai_conversation_views.xml`
- `views/ob_ai_approval_views.xml`
- `views/ob_ai_reminder_views.xml`
- `views/ob_ai_validation_views.xml`
- `views/ob_ai_dashboard_views.xml`
- `views/res_config_settings_views.xml`
- `views/ob_ai_tool_views.xml`
Main menu tree:
- Root: `AI Assistant`
- Conversations, Reminders, Dashboards, Validation Results, Approvals
- Analytics submenu (health scores/forecasts/scenarios)
- Configuration submenu (providers/models/allowed models/access templates/schema/tokens/traces/tools/audit/settings)

## Security
Files:
- `security/security.xml`
- `security/ir.model.access.csv`
Groups:
- `group_ai_user`, `group_ai_manager`, `group_ai_administrator`
- reviewer groups for accounting/hr/healthcare
Record rules:
- company/user scoping is defined for most conversation/audit/reminder/approval/memory/investigation/validation/document models.
ACLs:
- broad model coverage including tool catalog/calls and agent session/steps.

## Known Implemented Features
- Multi-provider AI with per-provider model selection.
- Agent-first tool-calling loop with reflection and streaming events.
- Secure gateway (`schema`, `records/query`, `records/count`, `records/aggregate`, `records/group`, `tools/execute`, `tools/dispatch`).
- Access templates with per-model field/capability controls and optional admin full-access mode.
- Approval workflows for risky writes.
- Generic create/update/delete/method-call tools with dry-run support.
- Document upload, OCR/table extraction, and row import to Odoo models.
- KPI snapshot generation with PDF/PNG export.
- Audit + retention + token cleanup + schema refresh cron jobs.

## Known Bugs / Mismatches
- Odoo 19 warning persists for legacy `_sql_constraints` declarations in some models; should migrate to `models.Constraint`.
- Legacy artifacts drift:
  - Full test suite still contains references to removed/router-era services (`ob.ai.router.service`, `ob.ai.investigation.service`, etc.).
  - `README.md` still has some legacy narrative fragments despite agent-first runtime.
- Security gap to review:
  - No explicit record rules for `ob.ai.agent.session`, `ob.ai.agent.step`, `ob.ai.tool.call`, and `ob.ai.request.token` (ACL exists, record-domain isolation is weaker than conversation-level models).
- `tool_odoo_group_by()` currently does not enforce template allowed-field checks on groupby/aggregate fields as strictly as aggregate/search-read paths.
- `tool_list_models()` accepts a `category` parameter but currently does not apply a category filter.
- Provider throttling can still surface user-facing “retry in X seconds” responses when retries are exhausted.

## Do Not Break
- Keep provider abstraction independent (`openai`/`anthropic` must both work).
- Preserve approval gate for risky write tools and action workflows.
- Preserve access-template + allowed-model/field enforcement path.
- Keep gateway request signature validation (`Authorization`, timestamp, sequence, HMAC) intact.
- Keep JSON-safe serialization for audit and approval payloads (avoid `date/datetime` serialization crashes).
- Keep retention defaults (`shared_data_retention_days=1095`) and cleanup cron behavior.
- Keep bus event channel conventions (`ob_ai_user_<uid>`, `ob_ai_session_<uuid>`) used by live stream JS.

---
Operational rule for future AI tasks in this module:
1. Read `ai_context/IMPLEMENTED_CONTEXT.md`
2. Read `ai_context/CURRENT_GOAL.md`
3. Read `ai_context/FUTURE_GOALS.md`
Then inspect only the specific source files needed for the task.
