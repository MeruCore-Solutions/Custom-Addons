"""AI Agent Solver — the true ReAct loop that replaces intent-based routing.

For every read question, this service:
  1. Creates an ob.ai.agent.session.
  2. Builds the initial conversation messages and a strict ERP-analyst system prompt.
  3. Loops up to max_steps iterations. Each iteration is one of:
       (a) plan_call: LLM with tools=auto; expects either tool_calls or final text
       (b) execute_tools: run each tool call via ob.ai.tool.service.dispatch()
       (c) reflect_call: LLM with tools=none; forces AI to summarize what it learned
       (a) again next loop
  4. Persists every step to ob.ai.agent.step and every tool call to ob.ai.tool.call.
  5. Emits live events (bus.bus and reasoning_trace) for streaming UI consumption.

The solver hard-fails gracefully: every error is caught, recorded, and the
user gets a useful error message in the final_answer field.
"""

import json
import logging
import re
import time
import traceback
import uuid
from datetime import datetime

from odoo import _, fields, models

_logger = logging.getLogger(__name__)


SYSTEM_PROMPT_TEMPLATE = """\
You are a senior business analyst embedded inside an Odoo ERP system. You answer
the user's questions by USING TOOLS to fetch real Odoo data — never invent
numbers, dates, names, or facts.

CORE RULES
1. For any data claim, you MUST first call a tool to get the data. No tool, no claim.
2. When you state a number, cite the tool that produced it (e.g. "per odoo_aggregate on sale.order").
3. Use the smallest set of tool calls that answers the question. Don't fetch what you don't need.
4. If a tool returns no data or an error, explain that to the user — don't fabricate.
5. If the question is ambiguous, you may either (a) make a reasonable assumption and state it,
   or (b) call list_models / describe_model / list_kpis to clarify what's available.
6. For "write" actions:
   - Use propose_* tools for reminders/activities/chatter.
   - Use odoo_create_records / odoo_update_records / odoo_delete_records / odoo_call_method for generic operations.
   - Run dry_run first for high-risk operations when possible.
   - If approval is required, tell the user the action is queued for review.
7. Be concise. Lead with the answer, then the supporting numbers, then any caveats.
8. Use plain text. Do not output markdown tables wider than the typical chat bubble.
9. Today's date: %(today)s. Current user: %(user_name)s. Current company: %(company_name)s.
10. If you have enough information to answer, ANSWER. Do not call more tools "just to be sure."
11. For general-knowledge questions that do not depend on ERP data, answer directly and clearly label it as external knowledge.
12. For cross-functional questions (sales + inventory + finance + CRM), combine multiple model/tool calls and synthesize one integrated answer.

REASONING DISCIPLINE (important)
- After each batch of tool results, your NEXT message in the loop will be a REFLECT step
  where you state in 1-3 sentences what you learned and what you still need.
- Only AFTER reflecting may you call more tools or provide the final answer.
- If you have nothing more to learn, just give the final answer directly.

You have access to tools that cover: Odoo data queries (search/read/aggregate/group),
schema introspection, KPI computation, strategic analytics (health score, forecast,
scenario), benchmarks, document analysis, and gated write actions. Use them.
"""


REFLECT_PROMPT = """\
You just received tool results. Before deciding your next move:
1. Briefly state what you learned (1-3 sentences).
2. State what you still need (or "I have enough — preparing final answer").
Do NOT call any tools in this turn. Reply with text only.
"""


class OBAIAgentSolver(models.AbstractModel):
    _name = "ob.ai.agent.solver"
    _description = "AI Agent Solver (ReAct loop)"

    # ================================================================== #
    # Public entrypoint
    # ================================================================== #

    def solve(self, conversation, user_prompt, provider=None, model=None, stream=True):
        """Run the agent loop. Returns the completed ob.ai.agent.session."""
        conversation.ensure_one()
        provider = provider or conversation._get_effective_provider()
        model = model or (conversation._get_effective_model(provider=provider) if provider else False)

        if not provider or not model:
            session = self._create_session(conversation, user_prompt, provider, model)
            session.write({
                "status": "failed",
                "stop_reason": "error",
                "error_message": "No AI provider/model configured.",
                "final_answer": _("No AI provider is configured. Please configure one in Settings → AI Assistant."),
                "finished_at": fields.Datetime.now(),
            })
            return session

        session = self._create_session(conversation, user_prompt, provider, model)
        self._emit_event(session, "session_started", {"prompt": user_prompt})

        try:
            self._run_loop(session, conversation, user_prompt, provider, model)
        except Exception as exc:  # noqa: BLE001
            _logger.exception("Agent solver crashed for session %s", session.session_uuid)
            tb = traceback.format_exc()
            session.write({
                "status": "failed",
                "stop_reason": "error",
                "error_message": "%s: %s\n\n%s" % (type(exc).__name__, exc, tb),
                "finished_at": fields.Datetime.now(),
            })
            if not session.final_answer:
                session.final_answer = _(
                    "An error occurred while processing your question: %(err)s\n\n"
                    "Open AI Assistant → Configuration → Agent Sessions to inspect the full trace.",
                    err=exc,
                )
            self._emit_event(session, "error", {"message": str(exc)})

        return session

    # ================================================================== #
    # Core loop
    # ================================================================== #

    def _run_loop(self, session, conversation, user_prompt, provider, model):
        tool_service = self.env["ob.ai.tool.service"]
        provider_service = self.env["ob.ai.provider.service"]

        tool_specs = tool_service.render_tool_specs_for_provider(provider.provider_type, user=session.user_id)
        system_prompt = self._build_system_prompt(session, conversation)
        messages = self._build_initial_messages(conversation, user_prompt)

        max_steps = session.max_steps or 15
        deadline = time.time() + (session.timeout_seconds or 120)
        reflect_after_tools = self._get_bool_param("ob_ai_assistant.solver_reflect_enabled", True)

        session.status = "running"
        sequence = 0

        for step_iteration in range(max_steps):
            if time.time() > deadline:
                session.stop_reason = "timeout"
                session.final_answer = session.final_answer or _("Reached the configured time limit before producing a final answer.")
                break

            # --- PLAN / EXECUTE PHASE ---
            sequence += 1
            plan_step = self._create_step(session, sequence, "plan")
            self._emit_event(session, "thinking", {"step": sequence, "phase": "plan"})

            try:
                plan_result = provider_service.invoke_with_tools(
                    provider, model, system_prompt, messages,
                    tools=tool_specs, tool_choice="auto",
                )
            except Exception as exc:  # noqa: BLE001
                if self._is_rate_limited_error(exc):
                    plan_result = self._retry_on_rate_limit(
                        provider_service,
                        provider,
                        model,
                        system_prompt,
                        messages,
                        tool_specs,
                        tool_choice="auto",
                        deadline=deadline,
                        session=session,
                        phase="plan",
                    )
                    if not plan_result:
                        plan_step.write({
                            "status": "success",
                            "reasoning_text": _(
                                "Planning was interrupted by temporary provider rate-limits."
                            ),
                        })
                        session.stop_reason = "timeout"
                        session.final_answer = _(
                            "The AI provider is temporarily busy. Please retry in a few seconds."
                        )
                        break
                else:
                    plan_step.write({"status": "error", "error_message": str(exc)})
                    raise

            self._record_step_metrics(plan_step, plan_result)

            tool_calls = plan_result.get("tool_calls") or []
            if not tool_calls:
                # Model returned a text-only answer — finalize
                plan_step.write({
                    "step_type": "answer",
                    "status": "success",
                    "reasoning_text": plan_result.get("text") or "",
                })
                session.final_answer = (plan_result.get("text") or "").strip()
                session.stop_reason = plan_result.get("stop_reason") or "final_answer"
                self._emit_event(session, "final_answer", {"text": session.final_answer})
                break

            # Persist assistant turn that requested tools, into message history
            plan_step.write({
                "step_type": "tool",
                "status": "success",
                "reasoning_text": plan_result.get("text") or "",
            })
            messages.append({
                "role": "assistant",
                "content": plan_result.get("text") or "",
                "tool_calls": tool_calls,
            })

            # Execute each tool call sequentially
            for tc in tool_calls:
                tool_name = tc.get("name")
                tool_args = tc.get("arguments") or {}
                self._emit_event(session, "tool_call", {
                    "step": sequence,
                    "tool": tool_name,
                    "arguments": tool_args,
                })
                dispatch_result = tool_service.dispatch(
                    tool_code=tool_name,
                    arguments=tool_args,
                    conversation=conversation,
                    session=session,
                    step=plan_step,
                    user=session.user_id,
                )
                self._emit_event(session, "tool_result", {
                    "step": sequence,
                    "tool": tool_name,
                    "status": dispatch_result.get("status"),
                    "preview": self._preview_for_event(dispatch_result),
                })
                # Feed tool result back into message history
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id"),
                    "content": json.dumps(dispatch_result, default=str)[:30000],  # cap per-tool feedback size
                })

            # --- REFLECT PHASE (if enabled) ---
            if reflect_after_tools and step_iteration < max_steps - 1:
                sequence += 1
                reflect_step = self._create_step(session, sequence, "reflect")
                self._emit_event(session, "thinking", {"step": sequence, "phase": "reflect"})

                reflect_messages = messages + [{"role": "user", "content": REFLECT_PROMPT}]
                try:
                    reflect_result = provider_service.invoke_with_tools(
                        provider, model, system_prompt, reflect_messages,
                        tools=tool_specs, tool_choice="none",
                    )
                except Exception as exc:  # noqa: BLE001
                    if self._is_rate_limited_error(exc):
                        reflect_result = self._retry_on_rate_limit(
                            provider_service,
                            provider,
                            model,
                            system_prompt,
                            reflect_messages,
                            tool_specs,
                            tool_choice="none",
                            deadline=deadline,
                            session=session,
                            phase="reflect",
                        )
                        if not reflect_result:
                            reflect_step.write({
                                "status": "success",
                                "reasoning_text": _(
                                    "Reflection was skipped due to temporary provider throttling."
                                ),
                            })
                            continue
                    else:
                        reflect_step.write({"status": "error", "error_message": str(exc)})
                        raise
                self._record_step_metrics(reflect_step, reflect_result)
                reflect_text = (reflect_result.get("text") or "").strip()
                reflect_step.write({
                    "status": "success",
                    "reasoning_text": reflect_text,
                })
                # Add reflection to history so next plan-call sees it
                if reflect_text:
                    messages.append({"role": "assistant", "content": reflect_text})
                    self._emit_event(session, "reflection", {
                        "step": sequence,
                        "text": reflect_text,
                    })

        else:
            session.stop_reason = "max_steps"
            if not session.final_answer:
                session.final_answer = self._fallback_answer_from_history(messages)

        # Finalize session
        finalize_vals = {
            "status": "done" if session.status != "failed" else "failed",
            "finished_at": fields.Datetime.now(),
        }
        # Persist reasoning trace
        finalize_vals["reasoning_trace"] = self._build_reasoning_trace_json(session)
        session.write(finalize_vals)
        if session.final_answer:
            self._emit_event(session, "done", {"text": session.final_answer})

    # ================================================================== #
    # Setup helpers
    # ================================================================== #

    def _create_session(self, conversation, user_prompt, provider, model):
        return self.env["ob.ai.agent.session"].create({
            "conversation_id": conversation.id,
            "user_id": self.env.user.id,
            "company_id": self.env.company.id,
            "provider_id": provider.id if provider else False,
            "model_id": model.id if model else False,
            "user_prompt": user_prompt,
            "status": "pending",
            "max_steps": max(self._get_int_param("ob_ai_assistant.solver_max_steps", 15), 1),
            "max_tokens": max(self._get_int_param("ob_ai_assistant.solver_max_tokens", 8000), 100),
            "timeout_seconds": max(self._get_int_param("ob_ai_assistant.solver_timeout_seconds", 120), 10),
        })

    def _create_step(self, session, sequence, step_type):
        return self.env["ob.ai.agent.step"].create({
            "session_id": session.id,
            "sequence": sequence,
            "step_type": step_type,
            "status": "running",
        })

    def _build_system_prompt(self, session, conversation):
        return SYSTEM_PROMPT_TEMPLATE % {
            "today": fields.Date.context_today(self),
            "user_name": session.user_id.name or "Unknown",
            "company_name": session.company_id.name or "",
        }

    def _build_initial_messages(self, conversation, user_prompt):
        """Build the initial message list. Includes a small slice of recent
        conversation history for continuity, then the new user prompt.
        """
        history = conversation.ai_message_ids.sorted("id")[-6:] if conversation.ai_message_ids else self.env["ob.ai.message"]
        messages = []
        for msg in history:
            if not msg.content:
                continue
            role = "assistant" if msg.role == "assistant" else "user"
            messages.append({"role": role, "content": (msg.content or "")[:4000]})
        messages.append({"role": "user", "content": user_prompt})
        return messages

    # ================================================================== #
    # Metrics + tracing
    # ================================================================== #

    def _record_step_metrics(self, step, result):
        step.write({
            "input_tokens": result.get("input_tokens") or 0,
            "output_tokens": result.get("output_tokens") or 0,
            "latency_ms": result.get("latency_ms") or 0,
            "raw_message_json": json.dumps({
                "text": result.get("text"),
                "tool_calls": result.get("tool_calls") or [],
                "stop_reason": result.get("stop_reason"),
            }, default=str)[:50000],
        })
        # Roll up to session
        session = step.session_id
        session.write({
            "total_input_tokens": (session.total_input_tokens or 0) + (result.get("input_tokens") or 0),
            "total_output_tokens": (session.total_output_tokens or 0) + (result.get("output_tokens") or 0),
            "total_latency_ms": (session.total_latency_ms or 0) + (result.get("latency_ms") or 0),
        })

    def _build_reasoning_trace_json(self, session):
        steps = session.step_ids.sorted("sequence")
        trace = []
        for s in steps:
            trace.append({
                "sequence": s.sequence,
                "type": s.step_type,
                "status": s.status,
                "reasoning": (s.reasoning_text or "")[:2000],
                "input_tokens": s.input_tokens,
                "output_tokens": s.output_tokens,
                "latency_ms": s.latency_ms,
                "tool_calls": [
                    {
                        "code": tc.tool_code,
                        "status": tc.status,
                        "latency_ms": tc.latency_ms,
                    }
                    for tc in s.tool_call_ids
                ],
            })
        return json.dumps(trace, default=str)

    def _fallback_answer_from_history(self, messages):
        # Find the last assistant text
        for msg in reversed(messages):
            if msg.get("role") == "assistant" and msg.get("content"):
                return msg["content"]
        return _("Reached the maximum number of reasoning steps without producing a final answer. Try narrowing the question.")

    def _preview_for_event(self, dispatch_result):
        if not isinstance(dispatch_result, dict):
            return str(dispatch_result)[:200]
        if dispatch_result.get("status") == "success":
            data = dispatch_result.get("data")
            if isinstance(data, dict):
                keys = list(data.keys())[:5]
                return {"keys": keys, "size": len(json.dumps(data, default=str))}
            return str(data)[:200]
        return {"status": dispatch_result.get("status"), "error": dispatch_result.get("error", "")[:200]}

    # ================================================================== #
    # Event emission (DB-persisted + Odoo bus if available)
    # ================================================================== #

    def _emit_event(self, session, event_type, payload):
        """Publish a streaming event. Persists to DB AND publishes to Odoo
        bus.bus so longpolling/websocket clients receive it. Commits the
        transaction so subscribers see it before the request finishes —
        without this, bus messages only flush at end-of-request and the
        UI sees the whole stream at once instead of step-by-step.
        """
        event = {
            "uuid": uuid.uuid4().hex,
            "ts": datetime.utcnow().isoformat(),
            "type": event_type,
            "payload": payload,
        }
        try:
            existing = []
            if session.reasoning_trace:
                try:
                    existing = json.loads(session.reasoning_trace)
                except Exception:  # noqa: BLE001
                    existing = []
            existing.append({"event": event_type, "ts": event["ts"], "payload": payload})
            session.reasoning_trace = json.dumps(existing[-200:], default=str)
        except Exception:  # noqa: BLE001
            pass

        # Enrich payload with routing metadata so listeners can multiplex
        bus_payload = dict(event)
        bus_payload["session_uuid"] = session.session_uuid
        bus_payload["conversation_id"] = session.conversation_id.id if session.conversation_id else False

        try:
            if "bus.bus" in self.env:
                bus = self.env["bus.bus"]
                # 1) Per-session channel (for direct subscribers)
                bus._sendone("ob_ai_session_%s" % session.session_uuid, "ob_ai_event", bus_payload)
                # 2) Per-user channel (what the conversation form actually subscribes to)
                if session.user_id:
                    bus._sendone("ob_ai_user_%d" % session.user_id.id, "ob_ai_event", bus_payload)
        except Exception:  # noqa: BLE001
            pass

        # Incremental commit so the bus event is visible to subscribers NOW.
        # The agent session/step records are already partly persisted and safe
        # to commit; if the solver later raises, we'll mark the session failed
        # in our top-level except handler.
        try:
            if self._streaming_enabled():
                self.env.cr.commit()
        except Exception:  # noqa: BLE001
            pass

    def _streaming_enabled(self):
        return self._get_bool_param("ob_ai_assistant.solver_stream_commits", True)

    def _get_bool_param(self, key, default=False):
        value = self.env["ir.config_parameter"].sudo().get_param(key, default=str(default))
        return value == "True"

    def _get_int_param(self, key, default=0):
        return int(self.env["ir.config_parameter"].sudo().get_param(key, default=str(default)) or default)

    def _is_rate_limited_error(self, exc):
        text = str(exc or "").lower()
        return (
            "rate-limit" in text
            or "rate limit" in text
            or "rate_limited" in text
            or "429" in text
            or "temporarily busy" in text
            or "too many requests" in text
        )

    def _extract_retry_wait_seconds(self, exc, default=2.0):
        text = str(exc or "")
        match = re.search(r"about\s+([0-9]+(?:\.[0-9]+)?)\s+seconds", text, flags=re.IGNORECASE)
        if match:
            try:
                return max(float(match.group(1)), 0.2)
            except (TypeError, ValueError):
                return default
        return default

    def _retry_on_rate_limit(
        self,
        provider_service,
        provider,
        model,
        system_prompt,
        messages,
        tool_specs,
        tool_choice,
        deadline,
        session,
        phase,
    ):
        max_attempts = max(self._get_int_param("ob_ai_assistant.solver_rate_limit_extra_retries", 2), 1)
        for attempt in range(max_attempts):
            remaining = deadline - time.time()
            if remaining <= 0:
                return False
            wait_seconds = min(
                self._extract_retry_wait_seconds(None, default=1.5),
                max(remaining - 0.1, 0.1),
            )
            self._emit_event(
                session,
                "rate_limit_retry",
                {
                    "phase": phase,
                    "attempt": attempt + 1,
                    "wait_seconds": round(wait_seconds, 2),
                },
            )
            if wait_seconds > 0:
                time.sleep(wait_seconds)
            try:
                return provider_service.invoke_with_tools(
                    provider,
                    model,
                    system_prompt,
                    messages,
                    tools=tool_specs,
                    tool_choice=tool_choice,
                )
            except Exception as exc:  # noqa: BLE001
                if not self._is_rate_limited_error(exc):
                    raise
                wait_seconds = min(
                    self._extract_retry_wait_seconds(exc, default=1.5),
                    max(deadline - time.time() - 0.1, 0.1),
                )
                if wait_seconds > 0 and time.time() < deadline:
                    time.sleep(wait_seconds)
                continue
        return False
