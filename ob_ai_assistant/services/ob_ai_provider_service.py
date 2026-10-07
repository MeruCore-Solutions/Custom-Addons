import json
import logging
import re
import time

import requests
from requests.exceptions import RequestException

from odoo import _, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class OBAIProviderService(models.AbstractModel):
    _name = "ob.ai.provider.service"
    _description = "AI Provider Service"

    # ================================================================== #
    # Function/Tool-calling entrypoint — primary agent path
    # ================================================================== #

    def invoke_with_tools(self, provider, model, system_prompt, messages, tools=None, tool_choice="auto"):
        """Single-turn LLM call with native function-calling support.

        Args:
            provider, model: ob.ai.provider / ob.ai.model records
            system_prompt: str
            messages: list of dicts in normalized format:
                - {"role": "user"|"assistant", "content": "..."}
                - {"role": "assistant", "tool_calls": [{"id", "name", "arguments_json"}]}
                - {"role": "tool", "tool_call_id": "...", "content": "..."}
            tools: list of tool-catalog specs (OpenAI-style nested format)
                e.g. [{"type": "function", "function": {"name", "description", "parameters"}}]
            tool_choice: "auto" | "required" | "none" | {"name": "specific_tool"}

        Returns dict:
            {
                "text": str | None,            # final text answer if no tool calls
                "tool_calls": [                # tool calls AI wants executed
                    {"id": "...", "name": "...", "arguments": {...}},
                ],
                "stop_reason": "tool_calls" | "final" | "max_tokens" | "error",
                "input_tokens", "output_tokens", "latency_ms",
                "request_payload", "response_payload",
            }
        """
        provider.ensure_one()
        model.ensure_one()
        api_key = provider.get_api_key()
        if not api_key:
            raise UserError(_("No API key is configured for %s.") % provider.display_name)

        if provider.provider_type == "anthropic":
            payload = self._build_anthropic_tools_payload(provider, model, system_prompt, messages, tools, tool_choice)
        else:
            payload = self._build_openai_tools_payload(provider, model, system_prompt, messages, tools, tool_choice)

        headers = self._build_headers(provider, api_key)
        attempt_count = max(self._get_retry_count(provider), 0) + 1
        # Keep at least one retry for transient throttling/network spikes.
        attempt_count = max(attempt_count, 2)
        last_error = False
        last_status = False

        for attempt in range(attempt_count):
            started_at = time.time()
            try:
                response = requests.post(
                    provider.endpoint_url,
                    headers=headers,
                    json=payload,
                    timeout=self._get_timeout(provider),
                )
                latency_ms = int((time.time() - started_at) * 1000)
                last_status = response.status_code
                response.raise_for_status()
                response_payload = response.json()

                if provider.provider_type == "anthropic":
                    parsed = self._parse_anthropic_response_with_tools(response_payload)
                else:
                    parsed = self._parse_openai_response_with_tools(response_payload)

                parsed.update({
                    "request_payload": payload,
                    "response_payload": response_payload,
                    "http_status": response.status_code,
                    "latency_ms": latency_ms,
                })
                return parsed
            except RequestException as exc:
                last_error = exc
                wait_seconds = self._get_retry_wait_seconds(exc, attempt=attempt)
                self._shrink_payload_for_retry(payload, attempt=attempt, error=exc)
                if attempt < attempt_count - 1:
                    _logger.warning(
                        "AI provider tool call failed for %s (attempt %s/%s): %s",
                        provider.display_name, attempt + 1, attempt_count, exc,
                    )
                    if wait_seconds > 0:
                        time.sleep(wait_seconds)
            except ValueError as exc:
                last_error = exc
                break

        if last_status == 429:
            wait_seconds = self._get_retry_wait_seconds(last_error, attempt=attempt_count)
            _logger.warning(
                "AI provider stayed rate-limited after %s attempts (%s). Returning graceful final response.",
                attempt_count,
                provider.display_name,
            )
            return self._rate_limited_tool_result(wait_seconds, payload, error=last_error, http_status=429)
        raise UserError(
            _("The AI provider tool-call request failed (%s): %s")
            % (last_status or "n/a", self._format_error(last_error))
        )

    # ================================================================== #
    # OpenAI Responses API — tool-call payload + response parsing
    # ================================================================== #

    def _build_openai_tools_payload(self, provider, model, system_prompt, messages, tools, tool_choice):
        max_output_tokens = model.max_output_tokens or provider.max_output_tokens or 2000
        input_items = self._normalize_messages_to_openai_input(messages)
        payload = {
            "model": model.model_key,
            "instructions": system_prompt,
            "input": input_items,
            "store": False,
            "max_output_tokens": max_output_tokens,
            "temperature": provider.temperature,
        }
        if tools:
            payload["tools"] = self._normalize_tools_to_openai_responses_format(tools)
            if tool_choice == "required":
                payload["tool_choice"] = "required"
            elif tool_choice == "none":
                payload["tool_choice"] = "none"
            elif isinstance(tool_choice, dict) and tool_choice.get("name"):
                payload["tool_choice"] = {"type": "function", "name": tool_choice["name"]}
            else:
                payload["tool_choice"] = "auto"
        return payload

    def _normalize_tools_to_openai_responses_format(self, tools):
        """Convert canonical OpenAI chat-completions tool spec (nested
        {type, function: {...}}) to OpenAI Responses API spec (flat).
        Already-flat specs pass through.
        """
        flat = []
        for spec in tools or []:
            if not isinstance(spec, dict):
                continue
            if spec.get("type") == "function" and "function" in spec:
                fn = spec["function"]
                flat.append({
                    "type": "function",
                    "name": fn.get("name"),
                    "description": fn.get("description"),
                    "parameters": fn.get("parameters") or {"type": "object", "properties": {}},
                })
            elif spec.get("type") == "function" and "name" in spec:
                flat.append(spec)
        return flat

    def _normalize_messages_to_openai_input(self, messages):
        """Convert internal message format to OpenAI Responses API input items.

        Internal format → OpenAI Responses input items:
        - {"role": "user", "content": "..."} → {"role": "user", "content": "..."}
        - {"role": "assistant", "content": "..."} → {"role": "assistant", "content": "..."}
        - {"role": "assistant", "tool_calls": [...]} → one function_call item per tool call
        - {"role": "tool", "tool_call_id": "...", "content": "..."} → {"type": "function_call_output", "call_id": "...", "output": "..."}

        An assistant message may have BOTH text content AND tool_calls; both must
        be emitted as separate items (text first, then each function_call). The
        function_call items MUST appear before any matching function_call_output
        item, otherwise the Responses API rejects the request with:
        "No tool call found for function call output with call_id ...".
        """
        items = []
        for msg in messages or []:
            role = msg.get("role")
            if role == "user" and msg.get("content"):
                items.append({"role": "user", "content": str(msg["content"])})
            elif role == "assistant":
                text_content = msg.get("content")
                if text_content:
                    items.append({"role": "assistant", "content": str(text_content)})
                for tc in msg.get("tool_calls") or []:
                    args = tc.get("arguments")
                    if isinstance(args, dict):
                        args = json.dumps(args)
                    call_id = tc.get("id") or tc.get("call_id")
                    if not call_id:
                        continue
                    items.append({
                        "type": "function_call",
                        "call_id": call_id,
                        "name": tc.get("name"),
                        "arguments": args or "{}",
                    })
            elif role == "tool":
                call_id = msg.get("tool_call_id")
                if not call_id:
                    continue
                items.append({
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": str(msg.get("content", "")),
                })
        return items

    def _parse_openai_response_with_tools(self, payload):
        """Extract text + tool_calls from an OpenAI Responses API response."""
        text_parts = []
        tool_calls = []
        stop_reason = "final"

        for item in payload.get("output") or []:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type == "function_call":
                args_raw = item.get("arguments") or "{}"
                try:
                    args = json.loads(args_raw) if isinstance(args_raw, str) else args_raw
                except json.JSONDecodeError:
                    args = {"_raw": args_raw, "_parse_error": True}
                tool_calls.append({
                    "id": item.get("call_id"),
                    "name": item.get("name"),
                    "arguments": args,
                })
                stop_reason = "tool_calls"
            elif item_type == "message":
                for content in item.get("content") or []:
                    if isinstance(content, dict) and content.get("text"):
                        text_parts.append(content["text"])
                    elif isinstance(content, dict) and content.get("type") == "output_text":
                        text_parts.append(content.get("text") or "")
            elif item.get("text"):
                text_parts.append(item["text"])

        if payload.get("output_text") and not text_parts:
            text_parts.append(payload["output_text"])

        incomplete = payload.get("incomplete_details") or {}
        if isinstance(incomplete, dict) and incomplete.get("reason") == "max_output_tokens":
            stop_reason = "max_tokens"

        usage = payload.get("usage") or {}
        return {
            "text": "\n".join(text_parts).strip() or None,
            "tool_calls": tool_calls,
            "stop_reason": stop_reason,
            "provider_response_id": payload.get("id"),
            "input_tokens": usage.get("input_tokens") or usage.get("prompt_tokens"),
            "output_tokens": usage.get("output_tokens") or usage.get("completion_tokens"),
        }

    # ================================================================== #
    # Anthropic Messages API — tool_use payload + response parsing
    # ================================================================== #

    def _build_anthropic_tools_payload(self, provider, model, system_prompt, messages, tools, tool_choice):
        max_output_tokens = model.max_output_tokens or provider.max_output_tokens or 2000
        anthropic_messages = self._normalize_messages_to_anthropic(messages)
        payload = {
            "model": model.model_key,
            "system": system_prompt,
            "messages": anthropic_messages,
            "max_tokens": max_output_tokens,
            "temperature": provider.temperature,
        }
        if tools:
            payload["tools"] = self._normalize_tools_to_anthropic_format(tools)
            if tool_choice == "required":
                payload["tool_choice"] = {"type": "any"}
            elif tool_choice == "none":
                payload["tool_choice"] = {"type": "none"}
            elif isinstance(tool_choice, dict) and tool_choice.get("name"):
                payload["tool_choice"] = {"type": "tool", "name": tool_choice["name"]}
            else:
                payload["tool_choice"] = {"type": "auto"}
        return payload

    def _normalize_tools_to_anthropic_format(self, tools):
        out = []
        for spec in tools or []:
            if not isinstance(spec, dict):
                continue
            if spec.get("type") == "function" and "function" in spec:
                fn = spec["function"]
                out.append({
                    "name": fn.get("name"),
                    "description": fn.get("description"),
                    "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
                })
            elif "name" in spec and "input_schema" in spec:
                out.append(spec)
            elif spec.get("type") == "function" and "name" in spec:
                out.append({
                    "name": spec.get("name"),
                    "description": spec.get("description"),
                    "input_schema": spec.get("parameters") or {"type": "object", "properties": {}},
                })
        return out

    def _normalize_messages_to_anthropic(self, messages):
        """Convert internal format to Anthropic messages.

        Anthropic message content can be a string OR a list of content blocks.
        Tool calls are 'tool_use' blocks in an assistant message.
        Tool results are 'tool_result' blocks in a user message.
        """
        result = []
        pending_tool_results = []

        def flush_pending_tool_results():
            if pending_tool_results:
                result.append({"role": "user", "content": list(pending_tool_results)})
                pending_tool_results.clear()

        for msg in messages or []:
            role = msg.get("role")
            if role == "tool":
                pending_tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": msg.get("tool_call_id"),
                    "content": str(msg.get("content", "")),
                })
                continue
            flush_pending_tool_results()
            if role == "user" and msg.get("content"):
                result.append({"role": "user", "content": str(msg["content"])})
            elif role == "assistant":
                blocks = []
                if msg.get("content"):
                    blocks.append({"type": "text", "text": str(msg["content"])})
                for tc in msg.get("tool_calls") or []:
                    args = tc.get("arguments")
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:  # noqa: BLE001
                            args = {"_raw": args}
                    blocks.append({
                        "type": "tool_use",
                        "id": tc.get("id"),
                        "name": tc.get("name"),
                        "input": args or {},
                    })
                if blocks:
                    result.append({"role": "assistant", "content": blocks})
        flush_pending_tool_results()
        return result

    def _parse_anthropic_response_with_tools(self, payload):
        text_parts = []
        tool_calls = []
        for block in payload.get("content") or []:
            if not isinstance(block, dict):
                continue
            block_type = block.get("type")
            if block_type == "text":
                text_parts.append(block.get("text") or "")
            elif block_type == "tool_use":
                tool_calls.append({
                    "id": block.get("id"),
                    "name": block.get("name"),
                    "arguments": block.get("input") or {},
                })
        stop_reason_raw = payload.get("stop_reason")
        if stop_reason_raw == "tool_use":
            stop_reason = "tool_calls"
        elif stop_reason_raw == "max_tokens":
            stop_reason = "max_tokens"
        elif stop_reason_raw in ("end_turn", "stop_sequence"):
            stop_reason = "final"
        else:
            stop_reason = stop_reason_raw or "final"
        usage = payload.get("usage") or {}
        return {
            "text": "\n".join(p for p in text_parts if p).strip() or None,
            "tool_calls": tool_calls,
            "stop_reason": stop_reason,
            "provider_response_id": payload.get("id"),
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
        }

    # ================================================================== #
    # Legacy text-only entrypoint (kept for callers without tools)
    # ================================================================== #

    def generate_text(self, provider, model, system_prompt, messages):
        provider.ensure_one()
        model.ensure_one()
        api_key = provider.get_api_key()
        if not api_key:
            raise UserError(_("No API key is configured for %s.") % provider.display_name)

        payload = self._build_payload(provider, model, system_prompt, messages)
        headers = self._build_headers(provider, api_key)
        attempt_count = max(self._get_retry_count(provider), 0) + 1
        attempt_count = max(attempt_count, 2)
        last_error = False
        last_status = False
        last_payload = False
        for attempt in range(attempt_count):
            started_at = time.time()
            try:
                response = requests.post(
                    provider.endpoint_url,
                    headers=headers,
                    json=payload,
                    timeout=self._get_timeout(provider),
                )
                latency_ms = int((time.time() - started_at) * 1000)
                last_status = response.status_code
                response.raise_for_status()
                last_payload = response.json()
                return {
                    "text": self._extract_text(provider, last_payload),
                    "provider_response_id": last_payload.get("id"),
                    "request_payload": payload,
                    "response_payload": last_payload,
                    "http_status": response.status_code,
                    "latency_ms": latency_ms,
                    "input_tokens": self._extract_usage(last_payload).get("input_tokens"),
                    "output_tokens": self._extract_usage(last_payload).get("output_tokens"),
                }
            except RequestException as exc:
                last_error = exc
                wait_seconds = self._get_retry_wait_seconds(exc, attempt=attempt)
                self._shrink_payload_for_retry(payload, attempt=attempt, error=exc)
                if attempt < attempt_count - 1:
                    _logger.warning(
                        "AI provider request failed for %s (attempt %s/%s): %s",
                        provider.display_name,
                        attempt + 1,
                        attempt_count,
                        exc,
                    )
                    if wait_seconds > 0:
                        time.sleep(wait_seconds)
            except ValueError as exc:
                last_error = exc
                break
        if last_status == 429:
            wait_seconds = self._get_retry_wait_seconds(last_error, attempt=attempt_count)
            _logger.warning(
                "AI provider text request stayed rate-limited after %s attempts (%s). Returning graceful message.",
                attempt_count,
                provider.display_name,
            )
            return self._rate_limited_text_result(wait_seconds, payload, error=last_error, http_status=429)
        raise UserError(
            _("The AI provider request failed (%s): %s")
            % (last_status or "n/a", self._format_error(last_error))
        )

    def _build_headers(self, provider, api_key):
        if provider.provider_type == "anthropic":
            return {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            }
        return {
            "Authorization": "Bearer %s" % api_key,
            "Content-Type": "application/json",
        }

    def _build_payload(self, provider, model, system_prompt, messages):
        cleaned_messages = [
            {
                "role": message.get("role"),
                "content": message.get("content"),
            }
            for message in messages
            if message.get("role") in ("user", "assistant") and message.get("content")
        ]
        max_output_tokens = model.max_output_tokens or provider.max_output_tokens or 1200
        if provider.provider_type == "anthropic":
            return {
                "model": model.model_key,
                "system": system_prompt,
                "messages": cleaned_messages,
                "max_tokens": max_output_tokens,
                "temperature": provider.temperature,
            }
        return {
            "model": model.model_key,
            "instructions": system_prompt,
            "input": cleaned_messages,
            "store": False,
            "max_output_tokens": max_output_tokens,
            "temperature": provider.temperature,
        }

    def _extract_text(self, provider, payload):
        if provider.provider_type == "anthropic":
            parts = []
            for block in payload.get("content") or []:
                text = block.get("text") if isinstance(block, dict) else False
                if text:
                    parts.append(text)
            return "\n".join(parts).strip()

        if payload.get("output_text"):
            return (payload.get("output_text") or "").strip()
        parts = []
        for item in payload.get("output") or []:
            if not isinstance(item, dict):
                continue
            direct_text = item.get("text")
            if direct_text:
                parts.append(direct_text)
            for content in item.get("content") or []:
                if not isinstance(content, dict):
                    continue
                text = content.get("text")
                if text:
                    parts.append(text)
        return "\n".join(parts).strip()

    def _extract_usage(self, payload):
        usage = payload.get("usage") or {}
        if "output_tokens" in usage or "input_tokens" in usage:
            return usage
        return {
            "input_tokens": usage.get("input_tokens"),
            "output_tokens": usage.get("output_tokens"),
        }

    def _get_timeout(self, provider):
        return provider.timeout_seconds or int(
            self.env["ir.config_parameter"].sudo().get_param("ob_ai_assistant.request_timeout", default="60")
        )

    def _get_retry_count(self, provider):
        return provider.max_retries or int(
            self.env["ir.config_parameter"].sudo().get_param("ob_ai_assistant.max_retries", default="1")
        )

    def _format_error(self, error):
        if not error:
            return _("Unknown provider error")
        response = getattr(error, "response", False)
        if response not in (False, None):
            try:
                payload = response.json()
            except ValueError:
                payload = response.text
            return "%s" % payload
        return str(error)

    def _get_retry_wait_seconds(self, error, attempt=0):
        """Return a bounded sleep duration for retryable failures."""
        response = getattr(error, "response", None)
        if response is None:
            return min(0.5 * (attempt + 1), 3.0)

        # RFC7231 Retry-After header
        retry_after = response.headers.get("Retry-After") if response.headers else None
        if retry_after:
            try:
                return max(min(float(retry_after), 10.0), 0.2)
            except (TypeError, ValueError):
                pass

        # OpenAI error messages often include "Please try again in 763ms."
        message = ""
        try:
            payload = response.json() or {}
            message = (
                ((payload.get("error") or {}).get("message"))
                or payload.get("message")
                or ""
            )
        except ValueError:
            message = response.text or ""
        if message:
            match = re.search(r"try again in\s+(\d+)\s*ms", message, flags=re.IGNORECASE)
            if match:
                return max(min(int(match.group(1)) / 1000.0, 10.0), 0.2)

        return min(0.8 * (attempt + 1), 5.0)

    def _rate_limited_tool_result(self, wait_seconds, request_payload, error=None, http_status=429):
        wait_seconds = max(round(wait_seconds or 1.0, 1), 1.0)
        return {
            "text": _(
                "The AI provider is temporarily rate-limited. "
                "I retried automatically, but it is still busy. "
                "Please retry in about %(seconds)s seconds.",
                seconds=wait_seconds,
            ),
            "tool_calls": [],
            "stop_reason": "final",
            "provider_response_id": False,
            "input_tokens": 0,
            "output_tokens": 0,
            "request_payload": request_payload,
            "response_payload": {
                "rate_limited": True,
                "retry_after_seconds": wait_seconds,
                "error": self._format_error(error),
            },
            "http_status": http_status,
            "latency_ms": 0,
            "rate_limited": True,
            "retry_after_seconds": wait_seconds,
        }

    def _rate_limited_text_result(self, wait_seconds, request_payload, error=None, http_status=429):
        wait_seconds = max(round(wait_seconds or 1.0, 1), 1.0)
        return {
            "text": _(
                "The AI provider is temporarily rate-limited. "
                "I retried automatically, but it is still busy. "
                "Please retry in about %(seconds)s seconds.",
                seconds=wait_seconds,
            ),
            "provider_response_id": False,
            "request_payload": request_payload,
            "response_payload": {
                "rate_limited": True,
                "retry_after_seconds": wait_seconds,
                "error": self._format_error(error),
            },
            "http_status": http_status,
            "latency_ms": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "rate_limited": True,
            "retry_after_seconds": wait_seconds,
        }

    def _shrink_payload_for_retry(self, payload, attempt=0, error=None):
        """Trim very large requests on retries to reduce token pressure."""
        if not isinstance(payload, dict):
            return
        response = getattr(error, "response", None)
        status_code = response.status_code if response is not None else None
        if status_code not in (413, 429):
            return

        max_output_tokens = payload.get("max_output_tokens")
        if isinstance(max_output_tokens, int) and max_output_tokens > 512:
            payload["max_output_tokens"] = max(512, int(max_output_tokens * 0.7))
        max_tokens = payload.get("max_tokens")
        if isinstance(max_tokens, int) and max_tokens > 512:
            payload["max_tokens"] = max(512, int(max_tokens * 0.7))

        if isinstance(payload.get("input"), list):
            self._trim_message_items(payload["input"], attempt=attempt)
        if isinstance(payload.get("messages"), list):
            self._trim_message_items(payload["messages"], attempt=attempt)

    def _trim_message_items(self, items, attempt=0):
        if not isinstance(items, list):
            return
        # Never trim across tool-call chains, otherwise providers can reject
        # inputs with "No tool call found for function call output ...".
        if self._contains_tool_chain(items):
            self._sanitize_tool_chain(items)
            self._shrink_textual_items(items, attempt=attempt)
            return
        # Progressively keep fewer historical messages on repeated retries.
        hard_limit = 18 if attempt == 0 else 12 if attempt == 1 else 8
        if len(items) > hard_limit:
            del items[:-hard_limit]

    def _contains_tool_chain(self, items):
        for item in items:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type in ("function_call", "function_call_output"):
                return True
            content = item.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") in ("tool_use", "tool_result"):
                        return True
        return False

    def _sanitize_tool_chain(self, items):
        # OpenAI Responses API tool chain sanitizer.
        call_ids = {
            item.get("call_id")
            for item in items
            if isinstance(item, dict)
            and item.get("type") == "function_call"
            and item.get("call_id")
        }
        if call_ids:
            sanitized = []
            for item in items:
                if (
                    isinstance(item, dict)
                    and item.get("type") == "function_call_output"
                    and item.get("call_id") not in call_ids
                ):
                    continue
                sanitized.append(item)
            if len(sanitized) != len(items):
                _logger.warning(
                    "Dropped %s orphan function_call_output items during retry payload sanitation.",
                    len(items) - len(sanitized),
                )
            items[:] = sanitized

        # Anthropic tool chain sanitizer.
        tool_use_ids = set()
        for item in items:
            if not isinstance(item, dict):
                continue
            for block in item.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("id"):
                    tool_use_ids.add(block.get("id"))
        if tool_use_ids:
            for item in items:
                if not isinstance(item, dict) or not isinstance(item.get("content"), list):
                    continue
                filtered_blocks = []
                for block in item.get("content"):
                    if (
                        isinstance(block, dict)
                        and block.get("type") == "tool_result"
                        and block.get("tool_use_id") not in tool_use_ids
                    ):
                        continue
                    filtered_blocks.append(block)
                item["content"] = filtered_blocks

    def _shrink_textual_items(self, items, attempt=0):
        """Reduce token load without breaking tool-call graph semantics."""
        if not isinstance(items, list):
            return
        max_chars = 1400 if attempt == 0 else 1000 if attempt == 1 else 700
        for item in items:
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("content"), str):
                content = item["content"]
                if len(content) > max_chars:
                    item["content"] = content[-max_chars:]
            elif isinstance(item.get("content"), list):
                for block in item["content"]:
                    if not isinstance(block, dict):
                        continue
                    text_value = block.get("text")
                    if isinstance(text_value, str) and len(text_value) > max_chars:
                        block["text"] = text_value[-max_chars:]
                    output_value = block.get("output")
                    if isinstance(output_value, str) and len(output_value) > 4000:
                        block["output"] = output_value[-4000:]
