# Future Goals

## Roadmap Summary
Evolve `ob_ai_assistant` from a strong internal AI module into a full enterprise AI operating layer for Odoo:
- flexible provider ecosystem,
- robust agent orchestration,
- secure and explainable tool execution,
- production-grade governance,
- and strong developer/operator observability.

The long-term direction is “human-level analyst + governed operator” with Odoo as the source of truth.

## Provider Improvements
- Add provider adapter classes to isolate protocol differences (OpenAI/Anthropic and future providers).
- Expand model registry metadata:
  - tool-call capability flags,
  - token/window limits,
  - latency/cost hints.
- Improve response normalization to a strict internal schema across all providers.
- Add multi-level fallback policy:
  - same provider alternate model,
  - secondary provider,
  - deterministic fallback messaging.
- Add per-company and per-user provider/model defaults and quotas.
- Add health probes for provider connectivity and credentials.

## Agent Improvements
- Add explicit planner policy profiles (fast/minimal vs deep-analysis mode).
- Improve max-iteration handling with structured “need-more-data” outputs.
- Add resumable sessions after human approval or provider interruption.
- Standardize structured final outputs:
  - answer text,
  - evidence references,
  - caveats,
  - recommended actions.
- Add memory/context compression for long conversations.
- Add richer per-step audit metadata and deterministic replay hooks.

## Tool System Improvements
- Introduce a stricter tool registry governance layer:
  - category risk levels,
  - mandatory dry-run for destructive actions,
  - explicit change previews.
- Enforce field policy checks consistently in all read/write tool paths.
- Expand JSON schema validation (nested schema support, enum/oneOf consistency checks).
- Add tool-level timeout + retry policy in dispatcher.
- Add structured tool execution logs with correlation IDs.
- Add policy-based auto-approval thresholds (e.g., low-risk writes).

## Approval System Improvements
- Add configurable reviewer groups per action type/model sensitivity.
- Add approval timeout/SLA and escalation rules.
- Add one-click approve/reject from list and kanban dashboards.
- Add explicit “resume session after approval” workflow.
- Add notifications:
  - chatter,
  - mail,
  - activities,
  - bus alerts.
- Add conflict detection for stale target records before apply.

## UI/UX Improvements
- Conversation sidebar with quick session switching and filters.
- Session timeline view (plan/tool/reflect/final) with drill-down.
- Tool call cards with arguments/result preview and approval status.
- Dedicated approval dashboard with risk badges.
- Gateway/debug panel for signed request diagnostics.
- Better cross-device responsive behavior for long chat sessions.

## Security Improvements
- Add missing record rules for agent/tool/token artifact models.
- Strengthen company isolation on all operational models.
- Add scoped masking for sensitive fields in logs and UI.
- Add stricter blocked-field enforcement in domain/group operations.
- Harden secret handling:
  - avoid unnecessary persistence exposure,
  - add secret rotation helpers.

## Testing Improvements
- Add focused unit tests for each service boundary (provider/tool/access/gateway).
- Add mocked provider tool-call tests for both OpenAI and Anthropic payload formats.
- Add approval lifecycle tests:
  - queue,
  - approve/reject,
  - apply,
  - resume behavior.
- Add gateway signature and replay-protection tests.
- Add module upgrade/forward-compat tests for schema/data/view/security consistency.
- Add performance tests for large model/tool histories.

## Documentation Improvements
- Keep README fully aligned with current runtime (agent-first, no stale router references).
- Add a developer architecture guide:
  - runtime flow,
  - extension points,
  - common pitfalls.
- Add provider setup/runbook and rate-limit handling guide.
- Add gateway integration guide with signed request examples.
- Add troubleshooting playbook with common stack traces and fixes.
- Maintain `ai_context/*` as mandatory handoff docs.

## Nice-to-Have Features
- Built-in benchmark packs by industry with update schedules.
- Scenario templates for CFO/COO/Head of Sales workflows.
- Scheduled AI briefings and digest emails.
- Multi-language analyst responses with locale-aware formatting.
- Explainability mode showing exactly which tools/records produced each claim.

## Risks / Design Warnings
- Do not tightly couple the module to one provider.
- Do not let raw provider stop reasons write directly into strict selection fields.
- Do not pass unknown fields into Odoo `create`/`write`.
- Do not bypass approval for risky actions unless policy allows it.
- Do not store secrets in plain text in business records.
- Do not force future AI tasks to re-read the entire module if `ai_context/*` is available.

---
Mandatory working protocol for future changes:
1. Read `ai_context/IMPLEMENTED_CONTEXT.md`
2. Read `ai_context/CURRENT_GOAL.md`
3. Read `ai_context/FUTURE_GOALS.md`
Then inspect only the minimal set of source files required for the task.
