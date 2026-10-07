"""AI Tool Service — dispatcher for AI-callable tools.

The agent solver calls dispatch() with a tool code and JSON arguments.
This service:
  1. Looks up the ob.ai.tool record.
  2. Checks user permission (via record's required_group_ids).
  3. Validates arguments against the tool's JSON Schema.
  4. If requires_approval — queues an ob.ai.approval and returns
     {"status": "pending_approval", "approval_id": ..., "message": ...}.
  5. Otherwise — invokes the handler method on this service class.
  6. Persists an ob.ai.tool.call audit record either way.

Tool handlers are methods on this class named tool_<code>. They MUST
return a JSON-serialisable dict. They MUST NOT raise — wrap errors in
{"ok": False, "error": "..."}.
"""

import json
import logging
import time
import traceback

from odoo import _, fields, models

_logger = logging.getLogger(__name__)

MAX_RESULT_BYTES = 200_000  # cap serialized result size; truncate beyond


class OBAIToolService(models.AbstractModel):
    _name = "ob.ai.tool.service"
    _description = "AI Tool Dispatcher Service"

    # ------------------------------------------------------------------ #
    # Public dispatch entrypoint
    # ------------------------------------------------------------------ #

    def dispatch(self, tool_code, arguments, conversation=None, session=None, step=None, user=None):
        """Validate, authorize, and execute a tool call. Returns a dict
        with at minimum a `status` key and either `data` or `error`.
        """
        user = user or self.env.user
        tool = self.env["ob.ai.tool"].sudo().search([("code", "=", tool_code)], limit=1)
        if not tool:
            return self._record_and_return(
                tool_code=tool_code, status="error", error="Unknown tool: %s" % tool_code,
                conversation=conversation, session=session, step=step, user=user,
            )

        if not tool.is_available_for_user(user):
            return self._record_and_return(
                tool=tool, status="rejected",
                error="User lacks required groups for tool '%s'." % tool_code,
                conversation=conversation, session=session, step=step, user=user,
            )

        # Validate arguments against schema
        validation_error = self._validate_arguments(tool, arguments)
        if validation_error:
            return self._record_and_return(
                tool=tool, status="error", error="Argument validation failed: %s" % validation_error,
                arguments=arguments,
                conversation=conversation, session=session, step=step, user=user,
            )

        # Enforce per-session call limit
        if tool.max_per_session and session:
            existing_count = self.env["ob.ai.tool.call"].sudo().search_count([
                ("session_id", "=", session.id), ("tool_code", "=", tool_code),
                ("status", "=", "success"),
            ])
            if existing_count >= tool.max_per_session:
                return self._record_and_return(
                    tool=tool, status="rejected",
                    error="Tool '%s' exceeded max calls per session (%d)." % (tool_code, tool.max_per_session),
                    arguments=arguments,
                    conversation=conversation, session=session, step=step, user=user,
                )

        # Write actions: approval gate
        if tool.requires_approval:
            if not (tool.auto_approve_for_admin and self._user_is_admin(user)):
                return self._queue_for_approval(
                    tool=tool, arguments=arguments,
                    conversation=conversation, session=session, step=step, user=user,
                )

        # Execute
        start = time.time()
        try:
            handler = getattr(self, tool.handler_method, None)
            if not handler or not callable(handler):
                return self._record_and_return(
                    tool=tool, status="error",
                    error="Handler '%s' not implemented." % tool.handler_method,
                    arguments=arguments,
                    conversation=conversation, session=session, step=step, user=user,
                )
            result = handler(conversation=conversation, user=user, **(arguments or {}))
            latency_ms = int((time.time() - start) * 1000)
            return self._record_and_return(
                tool=tool, status="success", data=result, latency_ms=latency_ms,
                arguments=arguments,
                conversation=conversation, session=session, step=step, user=user,
            )
        except Exception as exc:  # noqa: BLE001
            latency_ms = int((time.time() - start) * 1000)
            _logger.exception("Tool '%s' raised an exception", tool_code)
            return self._record_and_return(
                tool=tool, status="error",
                error="%s: %s" % (type(exc).__name__, exc),
                error_detail=traceback.format_exc(),
                latency_ms=latency_ms, arguments=arguments,
                conversation=conversation, session=session, step=step, user=user,
            )

    # ------------------------------------------------------------------ #
    # Approval-gated execution
    # ------------------------------------------------------------------ #

    def execute_approved(self, tool_call_record):
        """Called when an approval queued by dispatch() is approved.
        Re-executes the tool with the originally-validated arguments.
        """
        tool_call_record.ensure_one()
        if tool_call_record.status != "pending_approval":
            return {"status": "error", "error": "Tool call is not pending approval."}
        tool = tool_call_record.tool_id
        arguments = json.loads(tool_call_record.arguments_json or "{}")
        start = time.time()
        try:
            handler = getattr(self, tool.handler_method)
            result = handler(
                conversation=tool_call_record.conversation_id,
                user=tool_call_record.user_id,
                **arguments,
            )
            latency_ms = int((time.time() - start) * 1000)
            serialized = self._serialize_result(result)
            tool_call_record.write({
                "status": "success",
                "result_json": serialized["json"],
                "truncated": serialized["truncated"],
                "latency_ms": latency_ms,
            })
            return {"status": "success", "data": result}
        except Exception as exc:  # noqa: BLE001
            latency_ms = int((time.time() - start) * 1000)
            tool_call_record.write({
                "status": "error",
                "error_message": "%s: %s" % (type(exc).__name__, exc),
                "latency_ms": latency_ms,
            })
            return {"status": "error", "error": str(exc)}

    # ------------------------------------------------------------------ #
    # OpenAI / Anthropic spec rendering
    # ------------------------------------------------------------------ #

    def render_tool_specs_for_provider(self, provider_type, user=None):
        """Return list of tool spec dicts in the provider's expected format."""
        user = user or self.env.user
        available_tools = self.env["ob.ai.tool"].sudo().get_available_tools_for_user(user)
        if provider_type == "anthropic":
            return [t.to_anthropic_tool_spec() for t in available_tools]
        # default to OpenAI-compatible
        return [t.to_openai_tool_spec() for t in available_tools]

    # ------------------------------------------------------------------ #
    # Internal helpers
    # ------------------------------------------------------------------ #

    def _validate_arguments(self, tool, arguments):
        """Lightweight JSON Schema validation (type checks + required keys).
        Avoids hard dependency on jsonschema package.
        """
        schema = tool.get_schema_dict()
        if not schema or not isinstance(schema, dict):
            return None
        if not isinstance(arguments, dict):
            return "Arguments must be a JSON object."
        properties = schema.get("properties", {}) or {}
        required = schema.get("required", []) or []

        for req_key in required:
            if req_key not in arguments:
                return "Missing required parameter: %s" % req_key

        type_map = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        for key, value in (arguments or {}).items():
            if key not in properties:
                continue  # ignore unknown keys (forward-compat)
            expected_type = properties[key].get("type")
            if not expected_type:
                continue
            py_type = type_map.get(expected_type)
            if py_type is None:
                continue
            if expected_type == "integer" and isinstance(value, bool):
                return "Parameter '%s' must be integer, got boolean." % key
            if not isinstance(value, py_type):
                return "Parameter '%s' must be %s, got %s." % (key, expected_type, type(value).__name__)
            enum = properties[key].get("enum")
            if enum and value not in enum:
                return "Parameter '%s' must be one of %s, got %r." % (key, enum, value)
        return None

    def _queue_for_approval(self, tool, arguments, conversation, session, step, user):
        """Persist a tool call as pending_approval + create an approval record."""
        args_serialized = json.dumps(arguments or {}, default=str)
        approval = self.env["ob.ai.approval"].sudo().create({
            "name": _("AI tool: %(tool)s", tool=tool.name),
            "source_conversation_id": conversation.id if conversation else False,
            "user_id": user.id,
            "requested_by_id": user.id,
            "company_id": user.company_id.id,
            "action_type": "other",
            "approval_scope": "general",
            "action_summary": _("Tool '%(code)s' arguments: %(args)s", code=tool.code, args=args_serialized[:500]),
            "review_status": "pending_review",
        }) if "ob.ai.approval" in self.env else False

        tool_call = self.env["ob.ai.tool.call"].sudo().create({
            "tool_id": tool.id,
            "tool_code": tool.code,
            "conversation_id": conversation.id if conversation else False,
            "session_id": session.id if session else False,
            "step_id": step.id if step else False,
            "user_id": user.id,
            "company_id": user.company_id.id,
            "arguments_json": args_serialized,
            "status": "pending_approval",
            "approval_id": approval.id if approval else False,
        })
        return {
            "status": "pending_approval",
            "tool_call_id": tool_call.id,
            "approval_id": approval.id if approval else False,
            "message": "This tool call requires human approval before execution. The user has been notified.",
        }

    def _record_and_return(
        self,
        tool=None,
        tool_code=None,
        status="success",
        data=None,
        error=None,
        error_detail=None,
        latency_ms=0,
        arguments=None,
        conversation=None,
        session=None,
        step=None,
        user=None,
    ):
        user = user or self.env.user
        serialized = self._serialize_result(data) if data is not None else {"json": False, "truncated": False}
        vals = {
            "tool_id": tool.id if tool else False,
            "tool_code": (tool.code if tool else tool_code) or "",
            "conversation_id": conversation.id if conversation else False,
            "session_id": session.id if session else False,
            "step_id": step.id if step else False,
            "user_id": user.id,
            "company_id": user.company_id.id,
            "arguments_json": json.dumps(arguments or {}, default=str) if arguments is not None else False,
            "result_json": serialized["json"],
            "truncated": serialized["truncated"],
            "status": status,
            "error_message": error or False,
            "latency_ms": latency_ms,
        }
        # Honor audit_level
        if tool and tool.audit_level == "none":
            vals["arguments_json"] = False
            vals["result_json"] = False
        elif tool and tool.audit_level == "summary":
            # keep arguments, drop large result body
            if vals["result_json"] and len(vals["result_json"]) > 2000:
                vals["result_json"] = vals["result_json"][:2000] + "...[truncated]"
                vals["truncated"] = True

        self.env["ob.ai.tool.call"].sudo().create(vals)
        if status == "success":
            return {"status": "success", "data": data}
        return {
            "status": status,
            "error": error,
            "error_detail": error_detail if user.has_group("ob_ai_assistant.group_ai_administrator") else None,
        }

    def _serialize_result(self, data):
        try:
            payload = json.dumps(data, default=str, ensure_ascii=False)
        except Exception:  # noqa: BLE001
            payload = json.dumps({"_unserializable": str(type(data))}, default=str)
        truncated = False
        if len(payload.encode("utf-8")) > MAX_RESULT_BYTES:
            payload = payload[: MAX_RESULT_BYTES] + "...[truncated]"
            truncated = True
        return {"json": payload, "truncated": truncated}

    def _user_is_admin(self, user):
        return bool(
            user.has_group("base.group_system")
            or user.has_group("ob_ai_assistant.group_ai_administrator")
        )

    # ------------------------------------------------------------------ #
    # Handlers — stubs (real implementations in Step 5)
    # ------------------------------------------------------------------ #
    # These will be implemented by ob_ai_tool_handlers.py mixin in Step 5.
    # For now, having them here as stubs lets dispatch() find them.

    def _not_implemented(self, **kwargs):
        return {"ok": False, "error": "Handler not yet implemented."}
