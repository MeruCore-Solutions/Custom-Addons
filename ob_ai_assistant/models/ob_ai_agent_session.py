import json
import uuid

from odoo import _, api, fields, models


class OBAIAgentSession(models.Model):
    """One run of the agent solver loop.

    A session corresponds to one user prompt → final answer. Within it,
    the AI may execute many tool calls (ob.ai.agent.step). The session
    tracks token usage, latency, status, and the final answer.
    """

    _name = "ob.ai.agent.session"
    _description = "AI Agent Session"
    _order = "create_date desc, id desc"

    name = fields.Char(compute="_compute_name", store=True)
    session_uuid = fields.Char(
        required=True,
        default=lambda self: uuid.uuid4().hex,
        index=True,
        copy=False,
        help="Stable identifier used by the SSE streaming endpoint.",
    )
    conversation_id = fields.Many2one("ob.ai.conversation", required=True, ondelete="cascade", index=True)
    user_id = fields.Many2one("res.users", required=True, default=lambda self: self.env.user)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
    provider_id = fields.Many2one("ob.ai.provider", ondelete="set null")
    model_id = fields.Many2one("ob.ai.model", ondelete="set null")

    # Input
    user_prompt = fields.Text(required=True)

    # Output
    final_answer = fields.Text()
    reasoning_trace = fields.Text(string="Reasoning Trace (JSON)")

    # Steps
    step_ids = fields.One2many("ob.ai.agent.step", "session_id", string="Steps")
    step_count = fields.Integer(compute="_compute_step_count", store=True)

    # Status
    status = fields.Selection(
        [
            ("pending", "Pending"),
            ("planning", "Planning"),
            ("running", "Running"),
            ("done", "Done"),
            ("failed", "Failed"),
            ("interrupted", "Interrupted"),
        ],
        default="pending",
        required=True,
        index=True,
    )
    stop_reason = fields.Selection(
        [
            ("final", "Final answer reached"),
            ("final_answer", "Final answer reached"),
            ("max_steps", "Max steps reached"),
            ("max_tokens", "Max tokens reached"),
            ("timeout", "Timeout"),
            ("error", "Error"),
            ("user_interrupted", "User interrupted"),
        ],
    )
    error_message = fields.Text()

    # Metrics
    total_input_tokens = fields.Integer(string="Input Tokens")
    total_output_tokens = fields.Integer(string="Output Tokens")
    total_latency_ms = fields.Integer(string="Total Latency (ms)")
    tool_call_count = fields.Integer(compute="_compute_tool_call_count", store=True)

    # Limits applied
    max_steps = fields.Integer(default=15)
    max_tokens = fields.Integer(default=8000)
    timeout_seconds = fields.Integer(default=120)

    create_date = fields.Datetime(readonly=True)
    finished_at = fields.Datetime()

    @api.depends("conversation_id", "create_date")
    def _compute_name(self):
        for rec in self:
            rec.name = _("Session %(uuid)s", uuid=(rec.session_uuid or "")[:8])

    @api.depends("step_ids")
    def _compute_step_count(self):
        for rec in self:
            rec.step_count = len(rec.step_ids)

    @api.depends("step_ids", "step_ids.tool_call_ids")
    def _compute_tool_call_count(self):
        for rec in self:
            rec.tool_call_count = sum(len(s.tool_call_ids) for s in rec.step_ids)


class OBAIAgentStep(models.Model):
    """One iteration of the agent solver loop.

    A step records: the LLM call's input context, the LLM's reasoning,
    any tool calls it requested in this step, and the tool results that
    were fed back into the next iteration.
    """

    _name = "ob.ai.agent.step"
    _description = "AI Agent Step"
    _order = "session_id, sequence, id"

    name = fields.Char(compute="_compute_name", store=True)
    session_id = fields.Many2one("ob.ai.agent.session", required=True, ondelete="cascade", index=True)
    sequence = fields.Integer(required=True, default=1, help="Step number within the session (1-based).")
    step_type = fields.Selection(
        [
            ("plan", "Plan"),
            ("tool", "Tool Call"),
            ("reflect", "Reflect"),
            ("answer", "Final Answer"),
        ],
        required=True,
        default="plan",
    )

    # LLM input/output for this step
    reasoning_text = fields.Text(string="Reasoning")
    raw_message_json = fields.Text(string="Raw LLM Message (JSON)")
    input_tokens = fields.Integer()
    output_tokens = fields.Integer()
    latency_ms = fields.Integer()

    # Tool calls made in this step (one step can request multiple parallel tools)
    tool_call_ids = fields.One2many("ob.ai.tool.call", "step_id", string="Tool Calls")
    tool_call_count = fields.Integer(compute="_compute_tool_call_count", store=True)

    # Outcome
    status = fields.Selection(
        [
            ("running", "Running"),
            ("success", "Success"),
            ("error", "Error"),
        ],
        default="running",
        required=True,
    )
    error_message = fields.Text()

    create_date = fields.Datetime(readonly=True)

    @api.depends("session_id", "sequence", "step_type")
    def _compute_name(self):
        for rec in self:
            rec.name = _("Step %(seq)s — %(type)s", seq=rec.sequence, type=rec.step_type or "")

    @api.depends("tool_call_ids")
    def _compute_tool_call_count(self):
        for rec in self:
            rec.tool_call_count = len(rec.tool_call_ids)
