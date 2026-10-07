import json

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class OBAITool(models.Model):
    """Registry of AI-callable tools.

    Each record describes one function the agent can invoke during a
    reasoning loop. The schema is exposed to the LLM via native function
    calling (OpenAI tools / Anthropic tool_use), so descriptions and
    parameter schemas must be written for an LLM audience, not humans.
    """

    _name = "ob.ai.tool"
    _description = "AI Tool Specification"
    _order = "category, sequence, name"

    name = fields.Char(required=True, help="Human-readable name shown in UI.")
    code = fields.Char(
        required=True,
        index=True,
        help="Function name the AI calls. Must be a valid identifier: lowercase letters, digits, underscores.",
    )
    sequence = fields.Integer(default=10)
    description = fields.Text(
        required=True,
        help="Description shown to the LLM. Write this so an LLM knows exactly when and why to call this tool.",
    )
    category = fields.Selection(
        [
            ("data_read", "Data Read (Odoo)"),
            ("data_write", "Data Write (Odoo, needs approval)"),
            ("schema", "Schema Introspection"),
            ("kpi", "KPI Computation"),
            ("analytics", "Strategic Analytics"),
            ("benchmark", "Benchmark"),
            ("document", "Document Analysis"),
            ("memory", "Memory / Context"),
            ("utility", "Utility"),
        ],
        required=True,
        default="utility",
    )
    parameters_schema = fields.Text(
        required=True,
        default='{"type": "object", "properties": {}, "required": []}',
        help="JSON Schema describing the tool's parameters. Used for both LLM function-calling and runtime validation.",
    )
    handler_method = fields.Char(
        required=True,
        help="Method on ob.ai.tool.service that implements this tool. Will be called as service.<handler_method>(env, conversation, **args).",
    )
    requires_approval = fields.Boolean(
        default=False,
        help="If True, calls are queued for human approval before executing. Use for any write tool.",
    )
    auto_approve_for_admin = fields.Boolean(
        default=False,
        help="If True and the calling user is in group_ai_administrator, the approval gate is bypassed.",
    )
    required_group_ids = fields.Many2many(
        "res.groups",
        "ob_ai_tool_group_rel",
        "tool_id",
        "group_id",
        string="Required Groups",
        help="User must belong to ALL these groups to invoke the tool. Empty = available to any group_ai_user.",
    )
    max_per_session = fields.Integer(
        default=0,
        help="Maximum calls per conversation session. 0 = unlimited.",
    )
    timeout_seconds = fields.Integer(
        default=30,
        help="Hard timeout for tool execution.",
    )
    audit_level = fields.Selection(
        [
            ("none", "No audit"),
            ("summary", "Summary only"),
            ("full", "Full args + result"),
        ],
        default="summary",
    )
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", help="Leave empty to make available to all companies.")

    _sql_constraints = [
        ("code_uniq", "unique(code)", "Tool code must be unique."),
    ]

    @api.constrains("code")
    def _check_code_format(self):
        import re
        for rec in self:
            if not re.match(r"^[a-z][a-z0-9_]*$", rec.code or ""):
                raise ValidationError(_("Tool code must match ^[a-z][a-z0-9_]*$ (got '%s').", rec.code))

    @api.constrains("parameters_schema")
    def _check_parameters_schema(self):
        for rec in self:
            if not rec.parameters_schema:
                continue
            try:
                parsed = json.loads(rec.parameters_schema)
            except json.JSONDecodeError as exc:
                raise ValidationError(_("parameters_schema must be valid JSON: %s", exc)) from exc
            if not isinstance(parsed, dict):
                raise ValidationError(_("parameters_schema must be a JSON object."))
            if parsed.get("type") != "object":
                raise ValidationError(_('parameters_schema must have "type": "object" at the top level.'))

    def get_schema_dict(self):
        self.ensure_one()
        try:
            return json.loads(self.parameters_schema or "{}")
        except Exception:  # noqa: BLE001
            return {}

    def is_available_for_user(self, user):
        self.ensure_one()
        if not self.active:
            return False
        if self.company_id and self.company_id != user.company_id:
            return False
        if not self.required_group_ids:
            return True
        for group in self.required_group_ids:
            if not user.has_group(group.xml_id or "%s.%s" % (group._module, group.name)):
                # fallback: direct membership check
                if group not in user.groups_id:
                    return False
        return True

    @api.model
    def get_available_tools_for_user(self, user=None):
        """Return the recordset of tools the given user is allowed to invoke."""
        user = user or self.env.user
        tools = self.search([("active", "=", True)])
        return tools.filtered(lambda t: t.is_available_for_user(user))

    def to_openai_tool_spec(self):
        """Return the OpenAI function-calling spec dict for this tool."""
        self.ensure_one()
        return {
            "type": "function",
            "function": {
                "name": self.code,
                "description": self.description or "",
                "parameters": self.get_schema_dict(),
            },
        }

    def to_anthropic_tool_spec(self):
        """Return the Anthropic tool_use spec dict for this tool."""
        self.ensure_one()
        return {
            "name": self.code,
            "description": self.description or "",
            "input_schema": self.get_schema_dict(),
        }


class OBAIToolCall(models.Model):
    """Persistent audit log of every tool call made during agent reasoning.

    Used for: debugging, security review, evaluation harness, billing.
    """

    _name = "ob.ai.tool.call"
    _description = "AI Tool Call (Audit)"
    _order = "create_date desc, id desc"

    tool_id = fields.Many2one("ob.ai.tool", ondelete="set null")
    tool_code = fields.Char(string="Tool Code", index=True)
    conversation_id = fields.Many2one("ob.ai.conversation", ondelete="set null")
    session_id = fields.Many2one("ob.ai.agent.session", ondelete="set null")
    step_id = fields.Many2one("ob.ai.agent.step", ondelete="set null")
    user_id = fields.Many2one("res.users", default=lambda self: self.env.user)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)

    # Call detail
    arguments_json = fields.Text(string="Arguments (JSON)")
    result_json = fields.Text(string="Result (JSON)")
    truncated = fields.Boolean(string="Result Truncated", default=False)

    # Outcome
    status = fields.Selection(
        [
            ("pending_approval", "Pending Approval"),
            ("rejected", "Rejected"),
            ("running", "Running"),
            ("success", "Success"),
            ("error", "Error"),
            ("timeout", "Timeout"),
        ],
        default="success",
        required=True,
    )
    error_message = fields.Text()
    latency_ms = fields.Integer(string="Latency (ms)")

    # Approval reference (when requires_approval)
    approval_id = fields.Many2one("ob.ai.approval", ondelete="set null")
    create_date = fields.Datetime(readonly=True)
