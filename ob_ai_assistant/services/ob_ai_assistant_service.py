"""AI Assistant Service — slim entry point for the conversation layer.

After the agent-first rewrite, this service has only two responsibilities:
  1. generate_response: validate the prompt, hand off to the agent solver,
     shape the result for the conversation model.
  2. create_audit_log: write the audit row for each completed exchange.

All intent-based routing, deterministic dashboards, and templated handlers
were removed in favor of the agent solver loop (ob.ai.agent.solver) which
uses native function calling against the ob.ai.tool catalog.
"""

import json
from datetime import date, datetime, time
from decimal import Decimal

from odoo import _, fields, models
from odoo.exceptions import UserError


class OBAIAssistantService(models.AbstractModel):
    _name = "ob.ai.assistant.service"
    _description = "AI Assistant Service"

    # ------------------------------------------------------------------ #
    # Entrypoint
    # ------------------------------------------------------------------ #

    def generate_response(self, conversation, prompt, provider=False, model=False, context_bundle=None):
        conversation.ensure_one()
        self._ensure_enabled()
        prompt = (prompt or "").strip()
        if not prompt:
            raise UserError(_("Enter a prompt before sending it to the AI assistant."))

        prompt_limit = self._get_int_param("ob_ai_assistant.max_prompt_chars", 6000)
        if prompt_limit > 0 and len(prompt) > prompt_limit:
            raise UserError(_("The prompt exceeds the configured maximum size of %s characters.") % prompt_limit)

        return self._solve_via_agent(conversation, prompt, provider=provider, model=model)

    # ------------------------------------------------------------------ #
    # Agent-first solve
    # ------------------------------------------------------------------ #

    def _solve_via_agent(self, conversation, prompt, provider=False, model=False):
        """Run the AI agent solver and shape its output for the conversation
        layer (which still expects the legacy result-dict shape for now).
        """
        provider = provider or conversation._get_effective_provider()
        model = model or (conversation._get_effective_model(provider=provider) if provider else False)

        solver = self.env["ob.ai.agent.solver"]
        session = solver.solve(conversation, prompt, provider=provider, model=model)
        fallback_notice = False
        if session.status == "failed" and self._looks_like_provider_throttle(session.error_message):
            fallback_provider, fallback_model = self._resolve_fallback_provider_model(provider, model=model)
            if fallback_provider and fallback_model:
                fallback_session = solver.solve(
                    conversation,
                    prompt,
                    provider=fallback_provider,
                    model=fallback_model,
                )
                if fallback_session.status == "done" and fallback_session.final_answer:
                    session = fallback_session
                    fallback_notice = _(
                        "Primary provider was temporarily rate-limited. The assistant continued with %(provider)s (%(model)s).",
                        provider=fallback_provider.display_name,
                        model=fallback_model.display_name,
                    )

        tool_calls = session.step_ids.mapped("tool_call_ids").sorted("id", reverse=True)
        approval_id = next((tc.approval_id.id for tc in tool_calls if tc.approval_id), False)
        tool_codes_used = list({tc.tool_code for tc in tool_calls if tc.tool_code})

        warning = fallback_notice or False
        if session.status == "failed":
            warning = session.error_message
        elif session.stop_reason == "max_steps":
            warning = _("The AI reached the maximum reasoning steps and returned a best-effort answer.")
        elif session.stop_reason == "timeout":
            warning = _("The AI hit the time limit and returned a best-effort answer.")

        return {
            "text": session.final_answer or "",
            "input_tokens": session.total_input_tokens or 0,
            "output_tokens": session.total_output_tokens or 0,
            "latency_ms": session.total_latency_ms or 0,
            "http_status": 200,
            "context_bundle": {
                "source": "agent_solver",
                "agent_session_uuid": session.session_uuid,
                "step_count": session.step_count,
                "tool_call_count": session.tool_call_count,
                "stop_reason": session.stop_reason,
                "tool_codes_used": tool_codes_used,
            },
            "intent_code": "agent_solve",
            "confidence_score": 1.0 if session.status == "done" else 0.0,
            "action_requested": "read",
            "action_performed": "agent_solve",
            "human_review_status": "pending_review" if approval_id else "draft",
            "related_model": False,
            "related_record_refs": [],
            "route_context": {
                "agent_session_id": session.id,
                "agent_session_uuid": session.session_uuid,
                "agent_step_count": session.step_count,
                "agent_tool_call_count": session.tool_call_count,
                "tool_codes_used": tool_codes_used,
            },
            "warning_message": warning,
            "approval_id": approval_id,
            "agent_orchestrated": True,
            "agent_session_id": session.id,
            "agent_session_uuid": session.session_uuid,
            "provider_id": session.provider_id.id if session.provider_id else False,
            "model_id": session.model_id.id if session.model_id else False,
        }

    # ------------------------------------------------------------------ #
    # Audit logging
    # ------------------------------------------------------------------ #

    def create_audit_log(self, conversation, provider, model, prompt, result=False,
                         status="success", error_message=False, context_bundle=None):
        conversation.ensure_one()
        result = result or {}
        context_bundle = context_bundle or result.get("context_bundle") or {}
        store_raw = self._get_bool_param("ob_ai_assistant.store_raw_payload", True)

        values = {
            "conversation_id": conversation.id,
            "company_id": conversation.company_id.id,
            "user_id": self.env.user.id,
            "provider_id": provider.id if provider else False,
            "model_id": model.id if model else False,
            "request_kind": "chat",
            "status": status,
            "prompt_char_count": len(prompt or ""),
            "response_char_count": len(result.get("text") or ""),
            "input_tokens": result.get("input_tokens"),
            "output_tokens": result.get("output_tokens"),
            "latency_ms": result.get("latency_ms"),
            "http_status": result.get("http_status"),
            "intent_code": result.get("intent_code") or "agent_solve",
            "action_requested": result.get("action_requested"),
            "action_performed": result.get("action_performed"),
            "confidence_score": result.get("confidence_score"),
            "human_review_status": result.get("human_review_status"),
            "input_stored": store_raw,
            "output_stored": store_raw,
            "warning_message": result.get("warning_message"),
            "error_message": error_message or False,
        }
        if store_raw:
            values.update({
                "context_payload": self._json_safe({
                    "source": context_bundle.get("source"),
                    "agent_session_uuid": context_bundle.get("agent_session_uuid"),
                    "tool_codes_used": context_bundle.get("tool_codes_used") or [],
                    "step_count": context_bundle.get("step_count"),
                    "tool_call_count": context_bundle.get("tool_call_count"),
                    "stop_reason": context_bundle.get("stop_reason"),
                }),
            })

        return self.env["ob.ai.audit.log"].create(values)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _ensure_enabled(self):
        if not self._get_bool_param("ob_ai_assistant.enabled", True):
            raise UserError(_("The AI assistant is disabled in Settings."))

    def _get_bool_param(self, key, default=False):
        value = self.env["ir.config_parameter"].sudo().get_param(key, default=str(default))
        return value == "True"

    def _get_int_param(self, key, default=0):
        return int(self.env["ir.config_parameter"].sudo().get_param(key, default=str(default)) or default)

    def _looks_like_provider_throttle(self, error_message):
        text = (error_message or "").lower()
        if not text:
            return False
        return (
            "rate limit" in text
            or "429" in text
            or "tokens per min" in text
            or "too many requests" in text
            or "rate_limit_exceeded" in text
        )

    def _resolve_fallback_provider_model(self, current_provider, model=False):
        current_model = model
        providers = self.env["ob.ai.provider"].search(
            [
                ("active", "=", True),
                "|",
                ("company_id", "=", False),
                ("company_id", "=", self.env.company.id),
            ],
            order="sequence asc, id asc",
        )
        for provider in providers:
            if current_provider and provider.id == current_provider.id:
                continue
            if not provider.get_api_key():
                continue
            candidate_model = provider.default_model_id or provider.model_ids.filtered("active")[:1]
            if candidate_model:
                return provider, candidate_model

        if current_provider:
            alt_models = current_provider.model_ids.filtered(
                lambda record: record.active and (not current_model or record.id != current_model.id)
            ).sorted("sequence")
            if alt_models:
                return current_provider, alt_models[:1]
        return False, False

    def _json_safe(self, value):
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, datetime):
            return fields.Datetime.to_string(value)
        if isinstance(value, date):
            return fields.Date.to_string(value)
        if isinstance(value, time):
            return value.isoformat()
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, bytes):
            return "<binary>"
        if isinstance(value, models.BaseModel):
            if len(value) == 1:
                return "%s,%s" % (value._name, value.id)
            return ["%s,%s" % (record._name, record.id) for record in value]
        if isinstance(value, dict):
            return {str(key): self._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self._json_safe(item) for item in value]
        return str(value)
