import json
import logging

from odoo import _, http
from odoo.exceptions import AccessError, MissingError, UserError, ValidationError
from odoo.http import request
from werkzeug.wrappers import Response

_logger = logging.getLogger(__name__)


class OBAIGatewayController(http.Controller):

    def _json_response(self, payload, status=200):
        return Response(
            json.dumps(payload, ensure_ascii=False, default=str),
            status=status,
            content_type="application/json; charset=utf-8",
        )

    def _load_json_payload(self):
        raw_body = request.httprequest.get_data(cache=False) or b"{}"
        try:
            payload = json.loads(raw_body.decode("utf-8") or "{}")
        except Exception as exc:  # noqa: BLE001
            raise UserError(_("Gateway request body must be valid JSON.")) from exc
        if payload is None:
            payload = {}
        if not isinstance(payload, dict):
            raise UserError(_("Gateway request body must be a JSON object."))
        return raw_body, payload

    def _execute(self, required_scope, callback):
        communication_service = request.env["ob.ai.communication.service"].sudo()
        if not communication_service.gateway_is_enabled():
            return self._json_response(
                {
                    "ok": False,
                    "error": "gateway_disabled",
                    "message": _("The AI communication gateway is disabled."),
                },
                status=503,
            )
        try:
            raw_body, payload = self._load_json_payload()
            token_record = communication_service.validate_signed_gateway_request(
                request.httprequest.headers,
                raw_body,
                required_scope=required_scope,
            )
            result_payload = callback(communication_service, token_record, payload)
            return self._json_response(
                {
                    "ok": True,
                    "token_id": token_record.id,
                    "data": result_payload,
                },
                status=200,
            )
        except (UserError, AccessError, MissingError, ValidationError) as exc:
            return self._json_response(
                {
                    "ok": False,
                    "error": "invalid_request",
                    "message": str(exc),
                },
                status=400,
            )
        except Exception as exc:  # noqa: BLE001
            _logger.exception("Unhandled AI gateway controller error: %s", exc)
            return self._json_response(
                {
                    "ok": False,
                    "error": "internal_error",
                    "message": _("Unexpected AI gateway error."),
                },
                status=500,
            )

    @http.route("/ob_ai/gateway/v1/schema", type="http", auth="public", methods=["POST"], csrf=False)
    def ob_ai_gateway_schema(self, **kwargs):  # noqa: ARG002
        def _handler(service, token_record, payload):
            model_names = payload.get("model_names")
            if model_names and not isinstance(model_names, list):
                raise UserError(_("model_names must be a list of model names."))
            return service.fetch_schema_bundle_for_token(token_record, model_names=model_names or None)

        return self._execute("read_schema", _handler)

    @http.route("/ob_ai/gateway/v1/records/query", type="http", auth="public", methods=["POST"], csrf=False)
    def ob_ai_gateway_query_records(self, **kwargs):  # noqa: ARG002
        def _handler(service, token_record, payload):
            model_name = payload.get("model")
            if not model_name:
                raise UserError(_("model is required."))
            return service.fetch_record_bundle_for_token(
                token_record,
                model_name,
                domain=payload.get("domain") or [],
                limit=payload.get("limit"),
                field_names=payload.get("fields") or payload.get("field_names"),
                order=payload.get("order"),
            )

        return self._execute("read_context", _handler)

    @http.route("/ob_ai/gateway/v1/records/count", type="http", auth="public", methods=["POST"], csrf=False)
    def ob_ai_gateway_count_records(self, **kwargs):  # noqa: ARG002
        def _handler(service, token_record, payload):
            model_name = payload.get("model")
            if not model_name:
                raise UserError(_("model is required."))
            return service.count_records_for_token(
                token_record,
                model_name,
                domain=payload.get("domain") or [],
            )

        return self._execute("read_context", _handler)

    @http.route("/ob_ai/gateway/v1/records/aggregate", type="http", auth="public", methods=["POST"], csrf=False)
    def ob_ai_gateway_aggregate_records(self, **kwargs):  # noqa: ARG002
        def _handler(service, token_record, payload):
            model_name = payload.get("model")
            if not model_name:
                raise UserError(_("model is required."))
            return service.aggregate_records_for_token(
                token_record,
                model_name,
                domain=payload.get("domain") or [],
                field_name=payload.get("field_name"),
                operator=payload.get("operator") or "sum",
            )

        return self._execute("read_context", _handler)

    @http.route("/ob_ai/gateway/v1/records/group", type="http", auth="public", methods=["POST"], csrf=False)
    def ob_ai_gateway_group_records(self, **kwargs):  # noqa: ARG002
        def _handler(service, token_record, payload):
            model_name = payload.get("model")
            groupby_field = payload.get("groupby_field")
            if not model_name or not groupby_field:
                raise UserError(_("model and groupby_field are required."))
            aggregate_specs = payload.get("aggregate_specs")
            if aggregate_specs is not None and not isinstance(aggregate_specs, list):
                raise UserError(_("aggregate_specs must be a list when provided."))
            return service.group_records_for_token(
                token_record,
                model_name,
                groupby_field,
                domain=payload.get("domain") or [],
                aggregate_specs=aggregate_specs or ["__count"],
                limit=payload.get("limit"),
                order=payload.get("order"),
            )

        return self._execute("read_context", _handler)

    @http.route("/ob_ai/gateway/v1/tools/execute", type="http", auth="public", methods=["POST"], csrf=False)
    def ob_ai_gateway_execute_tools(self, **kwargs):  # noqa: ARG002
        def _handler(service, token_record, payload):
            requests = payload.get("requests")
            if requests is None:
                requests = []
            if not isinstance(requests, list):
                raise UserError(_("requests must be provided as a list."))
            return service.execute_tool_plan_for_token(
                token_record,
                requests,
                max_requests=payload.get("max_requests"),
            )

        return self._execute("read_context", _handler)

    @http.route("/ob_ai/gateway/v1/tools/dispatch", type="http", auth="public", methods=["POST"], csrf=False)
    def ob_ai_gateway_dispatch_tools(self, **kwargs):  # noqa: ARG002
        def _handler(service, token_record, payload):
            tool_calls = payload.get("tool_calls")
            if tool_calls is None:
                tool_calls = payload.get("requests")
            if tool_calls is None:
                tool_calls = []
            if not isinstance(tool_calls, list):
                raise UserError(_("tool_calls must be provided as a list."))
            return service.dispatch_tool_calls_for_token(
                token_record,
                tool_calls,
                max_requests=payload.get("max_requests"),
            )

        return self._execute("execute_actions", _handler)
