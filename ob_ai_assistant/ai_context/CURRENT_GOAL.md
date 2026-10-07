# Current Goal

## Goal Summary
Stabilize the module as a true agentic Odoo integration layer, not a fixed-response chatbot.
The current direction is to keep the agent-first runtime (`ob.ai.agent.solver`) and secure communication gateway as the primary path for analysis and operations.
Admin users with full-access templates should be able to run broad cross-model analysis and governed actions without repeated manual code changes.
At the same time, access templates, approvals, auditability, and provider abstraction must remain intact.

## Active Problem
The core runtime is agent-first, but there is still implementation drift between:
- current production code (solver/tool/gateway architecture),
- legacy references/tests/docs from the old router/investigation stack,
- and user expectations for broad, flexible analyst behavior.

Practical impact:
- some scenarios still feel constrained or inconsistent,
- legacy artifacts make maintenance confusing,
- and a few security/policy edges still need hardening.

## Recent Errors / Tracebacks
Observed during recent development/testing cycles:

1. `TypeError: Object of type datetime/date is not JSON serializable`
- Where: audit/approval payload writes.
- Root cause: raw Python `date/datetime` objects were written to JSON fields.
- Current status: mitigation implemented via JSON-safe sanitizers (`ob.ai.assistant.service._json_safe`, `ob.ai.approval._json_safe`, tool handler result normalization).

2. `psycopg2.errors.UniqueViolation` on `ir_config_parameter.key`
- Where: module upgrade for `ob_ai_assistant.store_raw_payload`.
- Root cause: duplicate config parameter insertion during data load.
- Current status: mitigated by using `setdefault_param` in config data.

3. `Invalid field 'summary' in 'ob.ai.approval'`
- Where: approval creation from tool/action flows.
- Root cause: caller passed legacy key `summary` while model expects `action_summary`.
- Current status: mitigated with legacy normalization in `ob.ai.approval._normalize_legacy_values()`.

4. Provider tool-call API error:
`No tool call found for function call output with call_id ...`
- Where: OpenAI Responses tool loop.
- Root cause: malformed/trimmed tool-call chain on retries.
- Current status: mitigated via provider payload sanitation and tool-chain preservation logic.

5. Provider throttling / `429 rate_limit_exceeded`
- Where: provider calls under high token pressure.
- Root cause: upstream API token-per-minute limits.
- Current status: partial mitigation (retries + graceful fallback messaging + provider/model fallback attempts). Still operationally visible.

## Files Likely Involved
- `models/ob_ai_conversation.py`
- `models/ob_ai_approval.py`
- `models/ob_ai_agent_session.py`
- `models/ob_ai_request_token.py`
- `models/ob_ai_access_template.py`
- `services/ob_ai_assistant_service.py`
- `services/ob_ai_agent_solver.py`
- `services/ob_ai_tool_service.py`
- `services/ob_ai_tool_handlers.py`
- `services/ob_ai_access_service.py`
- `services/ob_ai_communication_service.py`
- `services/ob_ai_provider_service.py`
- `services/ob_ai_action_service.py`
- `controllers/ob_ai_gateway_controller.py`
- `security/security.xml`
- `security/ir.model.access.csv`
- `views/ob_ai_conversation_views.xml`
- `views/ob_ai_approval_views.xml`
- `views/res_config_settings_views.xml`

## Expected Behavior
- User asks any ERP question; agent chooses tools and produces grounded answer.
- Cross-model analysis (sales/invoice/delivery/CRM/etc.) is handled dynamically with template-governed access.
- Admin full-access users can analyze broad scope without per-question code edits.
- Risky operations are either approved or safely auto-approved per policy.
- Communication layer endpoints remain signed, token-scoped, and auditable.
- Conversation UI shows final answer and live reasoning events without crashing.

## Current Behavior
- Agent loop, tool dispatch, and gateway are operational.
- Generic Odoo CRUD/method tools exist and are approval-aware.
- Most previously reported crashes were patched.
- Remaining friction is mostly around consistency/hardening:
  - policy edge cases,
  - legacy drift in tests/docs,
  - throttling resilience,
  - and selective access-rule coverage for agent artifacts.

## Implementation Plan
1. Keep agent-first flow as canonical runtime path and remove remaining legacy references from docs/tests incrementally.
2. Strengthen model isolation record rules for `ob.ai.agent.session`, `ob.ai.agent.step`, `ob.ai.tool.call`, `ob.ai.request.token`.
3. Tighten field-level policy enforcement in all read tools (especially `group_by`) to match template restrictions.
4. Normalize/validate stop reasons and status values at service boundaries.
5. Improve throttle handling strategy:
- adaptive output token caps,
- queue/retry strategy where appropriate,
- clearer fallback path messaging.
6. Expand regression tests for:
- gateway action dispatch,
- approval queue/apply flows,
- template-scoped model/field restrictions,
- and cross-model analyst prompts.
7. Keep README and `ai_context/*` synchronized with actual code paths.

## Acceptance Criteria
- Agent can answer cross-model prompts using real tool evidence without crashing.
- Admin full-access users can query broad allowed scope without manual code toggles.
- Tool calls requiring approval are queued cleanly with valid `ob.ai.approval` records.
- Approval apply path executes without unknown-field or JSON serialization errors.
- Gateway signed requests (read + action scope) validate and dispatch correctly.
- Module upgrade runs without parse/field/security errors.
- Focused regression tests for solver/tool/gateway/approval pass.

## Testing Steps
1. Upgrade module:
```bash
.venv/bin/python community/odoo-bin -d 19.0-ob-ai --addons-path=community/addons,enterprise,SH/GM/OCR --stop-after-init -u ob_ai_assistant
```

2. Run targeted tests (adjust port if 8069 busy):
```bash
.venv/bin/python community/odoo-bin -d 19.0-ob-ai --http-port=8076 --addons-path=community/addons,enterprise,SH/GM/OCR --test-enable --stop-after-init -u ob_ai_assistant --test-tags /ob_ai_assistant:TestObAIAssistant.test_communication_service_dispatch_tool_calls_with_action_scope,/ob_ai_assistant:TestObAIAssistant.test_tool_list_models_respects_template_scope,/ob_ai_assistant:TestObAIAssistant.test_tool_odoo_create_records_supports_dry_run_and_execute,/ob_ai_assistant:TestObAIAssistant.test_tool_odoo_update_records_rejects_invalid_fields,/ob_ai_assistant:TestObAIAssistant.test_tool_odoo_call_method_can_run_business_button
```

3. Manual UI checks:
- Open `AI Assistant > Conversations`.
- Ask cross-model prompts and verify grounded answers.
- Trigger a write action and verify approval record creation.
- Approve/apply and verify execution.
- Verify audit logs and tool call logs.

4. Gateway check:
- Use a valid token/signature and call:
  - `/ob_ai/gateway/v1/records/query`
  - `/ob_ai/gateway/v1/tools/dispatch`
- Confirm scope enforcement and audit trail.

## Constraints
- Keep provider abstraction independent; do not hardcode one provider.
- Do not bypass approval for risky actions unless policy explicitly allows it.
- Preserve signed token + scope checks for gateway communication.
- Avoid duplicating relationship fields when a canonical link already exists.
- Keep behavior compatible with existing conversation/audit data.

---
Execution protocol for future tasks:
1. Read `ai_context/IMPLEMENTED_CONTEXT.md`
2. Read `ai_context/CURRENT_GOAL.md`
3. Read `ai_context/FUTURE_GOALS.md`
Then inspect only the source files required for the requested change.
