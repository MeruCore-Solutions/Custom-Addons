# ob_ai_assistant

Smart AI Tool for Odoo 19.

`ob_ai_assistant` is a governed AI workspace for Odoo that combines conversational UX with deterministic ERP actions. It lets business users ask operational questions, generate summaries, create follow-up work, and review AI-supported insights without giving the provider uncontrolled access to the database.

The module is designed around a simple principle:

- Odoo stays the system of record.
- AI is an assistant layer, not a hidden decision maker.
- Access, actions, and auditability are always explicit.

## What This Module Delivers

### Provider and model management

- Built-in providers for ChatGPT via OpenAI and Claude via Anthropic
- Selectable default provider and default model from Settings
- Provider-level endpoint, token, timeout, retry, and output-limit controls
- Per-conversation provider/model tracking in the audit trail

### AI conversations inside Odoo

- Conversation records with prompt history and assistant responses
- Chat-oriented form view for users who want a focused AI workspace
- Settings-oriented mode for governance, context selection, and traceability
- Sticky chat behavior with scrollable message history

### True AI orchestration runtime

- Agentic orchestration path for read prompts: plan, fetch, reason, answer
- Signed communication gateway tools for `query`, `count`, `aggregate`, `group`, and secure tool dispatch
- Dynamic multi-model exploration in global mode with access-template enforcement
- Admin global-scope mode for full-access administrators
- Tool-layer access validation unified with access templates and admin full-access policy
- Grounded response strategy that keeps deterministic ERP evidence attached to AI narrative
- Shared AI data packets persisted in audit payloads (default retention: 1095 days / 3 years)

### Deterministic Odoo business answers

The module does not rely only on model text generation. It includes deterministic business services so key answers come from real Odoo data:

- current month booked sales
- delivered sales
- invoiced sales
- top-selling product for the selected period
- deliveries to process today
- visible activity and overdue workload snapshots
- basic dashboard and KPI summaries

This makes the most important ERP answers safer, more reproducible, and easier to audit.

### Safe actions and workflow automation

- AI-triggered reminders
- AI-triggered `mail.activity` follow-ups
- chatter posting on supported records
- generic create/update/delete tools on allowed models (approval-gated, admin-aware)
- business workflow method execution (for `action_*` / `button_*` style methods)
- secure communication-layer action dispatch through signed request tokens (`execute_actions` scope)
- approval records for actions that should not run immediately
- duplicate prevention with idempotency keys

### Validation and document context

- configurable validation rules per Odoo model
- validation result records with explanations and suggested action
- related attachment extraction and cached document context records
- conversation-driven document summaries when allowed
- direct chat document upload (PDF/text/images/office files) for AI analysis without selecting a related record
- structured extraction from CSV/Excel/PDF/Image attachments with OCR-aware fallback
- AI tool support to map extracted table columns into Odoo model fields and import rows (approval-gated)
- dashboard export to PDF and image (PNG) from AI KPI snapshots or direct prompt requests

### Governance and auditability

- allowed-model whitelist
- allowed-field whitelist
- current-user access rights respected before context is sent
- raw payload storage (enabled by default, configurable)
- retention settings for prompts, responses, and shared AI audit payloads
- audit logs with provider, model, token, latency, action, and context metadata

## Typical Business Questions

Examples the module is already designed to handle well:

- `What is my current month sales?`
- `What are my delivered sales for this month?`
- `Which is the most selling product in the current month?`
- `What are the delivery orders we need to process today?`
- `What are the delivery orders we need to process today, and create activities for the responsible persons?`
- `Show me the invoices that are overdue today.`
- `What stock items are low or at risk today?`
- `Summarize this customer record and suggest the next follow-up action.`
- `Validate this record and tell me what is missing.`
- `Summarize the related documents and highlight risks.`

## Functional Architecture

### Core models

- `ob.ai.conversation`: master conversation, context, state, routing result
- `ob.ai.message`: user and assistant conversation messages
- `ob.ai.provider`: AI provider definitions
- `ob.ai.model`: selectable AI models per provider
- `ob.ai.allowed.model`: whitelist entry for an Odoo model and its safe behavior
- `ob.ai.prompt.template`: seeded and configurable prompt intent templates
- `ob.ai.audit.log`: request/response and governance trace
- `ob.ai.reminder`: AI-created reminder records
- `ob.ai.approval`: human approval queue for sensitive actions
- `ob.ai.validation.rule`: deterministic rule definitions
- `ob.ai.validation.result`: validation outcomes
- `ob.ai.kpi.snapshot`: generated KPI summaries and lines
- `ob.ai.document.context`: cached attachment/document extraction records

### Service layer

- `ob.ai.assistant.service`: orchestration entry point
- `ob.ai.agent.solver`: planner/executor loop with tool calling
- `ob.ai.tool.service`: tool dispatcher with approval gate and full call audit
- `ob.ai.provider.service`: OpenAI and Anthropic API calls
- `ob.ai.access.service`: whitelist enforcement and context building
- `ob.ai.communication.service`: signed tool-mesh gateway and token contract runtime
- `ob.ai.sales.service`: deterministic sales metrics
- `ob.ai.dashboard.service`: deterministic KPI and worklist generation
- `ob.ai.action.service`: reminders, activities, chatter, approvals
- `ob.ai.validation.service`: rule execution
- `ob.ai.document.service`: document-context extraction and caching

## How It Works

### 1. A user asks a question

The user types a prompt in an `AI Conversation`.

### 2. The agent solver plans with tools

The solver analyzes the prompt and decides which tools are needed:

- schema/model discovery when the target object is unclear
- read tools for counts, aggregates, groupings, and record details
- write tools (approval-gated) for actions
- reflection/finalization turns before the final answer

### 3. The access layer builds safe context

Only configured models and fields are eligible. The module checks:

- whether the model is allowed
- whether the current user can read the records
- whether document context is allowed
- whether the requested action is allowed on that model

### 4. The provider reasons over live ERP evidence

The provider receives only safe context and tool results. It must cite real ERP evidence and return a concise answer (or queue actions through approvals).

### 5b. The orchestration agent can call tools in background

When true orchestration is enabled, the module can:

- issue a short-lived signed token contract
- plan bounded data requests across allowed models
- call secure gateway tools (`query/count/aggregate/group`)
- call secure gateway tool dispatch for approved operator actions (`tools/dispatch`)
- synthesize an answer from real ERP payloads and deterministic service output
- persist shared data packets in audit payloads for traceability

### 6. Everything is tracked

The conversation, assistant output, metrics, action result, and audit trail are stored inside Odoo.

## Supported Out-of-the-Box Intents

The seeded routing/templates currently cover:

- general query
- document summary
- reminder creation
- activity creation
- dashboard generation
- sales overview
- product sales ranking
- delivery worklist
- record validation

The router also contains higher-specificity handling for delivery worklists and sales/product-sales prompts so these questions are answered from real Odoo calculations rather than generic model text.

## Safe Context and Default Allowed Models

The module lazily seeds default allowed models for common business flows, including:

- activities
- sales orders
- sales order lines
- transfers and deliveries
- stock moves
- invoices
- customers and contacts
- products
- purchase orders
- employees
- time off

Each allowed-model record can define:

- search aliases
- default ordering
- searchable fields
- allowed date/reference/name fields
- maximum context record count
- whether chatter/activity/reminder/dashboard/document/validation flows are allowed
- sensitivity level

## Configuration Guide

### Basic setup

1. Install the addon `ob_ai_assistant`.
2. Open `Settings > AI Assistant`.
3. Enable the module.
4. Enter your OpenAI and/or Anthropic API keys.
5. Choose the default provider and default model.
6. Review prompt/response limits and retention settings.

### Governance setup

Recommended next steps after installation:

1. Review the seeded Allowed Models.
2. Remove or tighten any models you do not want exposed to the assistant.
3. Confirm which models may create reminders, activities, or chatter notes.
4. Enable human approval for sensitive actions.
5. Decide whether raw request/response payloads should be stored.
6. Add validation rules for the records that matter most in your business.

### Operational settings available

- service user
- request timeout
- retry count
- max prompt length
- max response length
- document summary toggle
- conversation summary toggle
- chatter posting toggle
- activity creation toggle
- reminder creation toggle
- dashboard toggle
- validation toggle
- true AI orchestration toggle
- force orchestration for read prompts
- force orchestration for admins
- admin global scope mode
- orchestrator max iterations
- orchestrator max tool requests
- human approval requirement
- prompt retention days
- response retention days
- raw payload storage
- shared AI data retention days (default 1095 / 3 years)
- feature flags

## Daily Usage Patterns

### Read-only operational assistant

Use the module to answer:

- what needs attention today
- what is overdue
- how sales are trending this period
- what top products are selling
- what documents or record details matter most

### Guided action assistant

Use the assistant to:

- create reminders
- create follow-up activities
- post internal notes
- queue actions for approval instead of immediate execution

### Review and control

Managers or administrators can:

- inspect audit logs
- review approvals
- check validation results
- inspect generated KPI snapshots
- review extracted document context

## Validation Engine

The deterministic validation layer currently supports rules such as:

- required fields
- date must not be in the past
- numeric threshold must be positive or above a minimum
- attachment required
- state must be in an allowed set

Validation results are stored as records and can be surfaced back through the conversation.

## Approval and Idempotency

To make automation safer in ERP workflows, the module includes:

- approval records before executing sensitive actions
- idempotency keys to avoid duplicate reminders/activities/notes
- action summaries written back into the conversation

This is especially important for repeated prompts or when users retry an action after a partial failure.

## Scheduled Jobs

The module includes cron-driven maintenance features such as:

- reminder processing
- retention cleanup for old AI records and payloads

## What This Module Does Not Try To Do

The module is intentionally opinionated.

It does not:

- give the provider unrestricted database access
- silently run broad write actions across the ERP
- replace native Odoo permissions
- pretend every answer is purely AI-generated when deterministic ERP logic is available

## Extending the Module

The addon is structured so future phases can be added cleanly:

- add more prompt templates
- add more deterministic business services
- add more validation rule types
- add more provider adapters
- add industry-specific flows for manufacturing, projects, hospital workflows, HR, and procurement
- replace the current chat form with a dedicated OWL client action later if needed

## Installation Command Example

```bash
./odoo-bin --addons-path=addons/,../enterprise,../SH/GM/OCR \
    --limit-memory-hard=0 \
    -d 19.0-ob-ai \
    --dev=xml,reload,qweb \
    --with-demo \
    -i ob_ai_assistant
```

## Testing and Verification

Recommended verification after changes:

```bash
python3 -m compileall SH/GM/OCR/ob_ai_assistant
```

And for addon behavior:

```bash
./odoo-bin -d <database> -u ob_ai_assistant --test-tags /ob_ai_assistant
```

## Module Positioning

This addon is best understood as a controlled AI operating layer for Odoo:

- conversational for end users
- deterministic for business-critical answers
- audited for administrators
- configurable for governance teams
- extensible for future AI workflows
