from odoo import _, api, fields, models
from odoo.exceptions import UserError


class OBAIConversation(models.Model):
    _name = "ob.ai.conversation"
    _description = "AI Conversation"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"

    name = fields.Char(required=True, default="New Conversation", tracking=True)
    chat_mode = fields.Boolean()
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, tracking=True)
    user_id = fields.Many2one("res.users", string="Owner", default=lambda self: self.env.user, required=True, tracking=True)
    provider_id = fields.Many2one("ob.ai.provider", string="Provider", tracking=True)
    model_id = fields.Many2one(
        "ob.ai.model",
        string="Model",
        domain="[('provider_id', '=', provider_id)]",
        tracking=True,
    )
    context_mode = fields.Selection(
        [
            ("global", "Global Overview"),
            ("focused", "Focused Context"),
        ],
        default="focused",
        required=True,
        tracking=True,
        help="Global Overview allows the router to switch models dynamically. Focused Context keeps routing anchored to the selected model/record.",
    )
    allowed_model_id = fields.Many2one("ob.ai.allowed.model", string="Allowed Odoo Model", tracking=True)
    available_allowed_model_ids = fields.Many2many(
        "ob.ai.allowed.model",
        compute="_compute_available_allowed_model_ids",
    )
    related_record_ref = fields.Reference(
        selection="_selection_reference_models",
        string="Related Record",
        tracking=True,
    )
    chat_attachment_ids = fields.Many2many(
        "ir.attachment",
        "ob_ai_conversation_attachment_rel",
        "conversation_id",
        "attachment_id",
        string="Chat Attachments",
        help="Upload documents directly in chat so the AI can analyze them.",
    )
    prompt_input = fields.Text(string="Prompt")
    intent_code = fields.Char(readonly=True, tracking=True)
    intent_confidence = fields.Float(readonly=True)
    human_review_status = fields.Selection(
        [
            ("draft", "Draft"),
            ("pending_review", "Pending Review"),
            ("approved", "Approved"),
            ("rejected", "Rejected"),
            ("applied", "Applied"),
        ],
        default="draft",
        readonly=True,
        tracking=True,
    )
    suggested_action_summary = fields.Text(readonly=True)
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("processing", "Processing"),
            ("done", "Done"),
            ("error", "Error"),
        ],
        default="draft",
        tracking=True,
    )
    last_error = fields.Text(readonly=True)
    ai_message_ids = fields.One2many("ob.ai.message", "conversation_id", string="Conversation Entries", readonly=True)
    audit_log_ids = fields.One2many("ob.ai.audit.log", "conversation_id", string="Audit Logs", readonly=True)
    reminder_ids = fields.One2many("ob.ai.reminder", "source_conversation_id", string="Reminders", readonly=True)
    approval_ids = fields.One2many("ob.ai.approval", "source_conversation_id", string="Approvals", readonly=True)
    validation_result_ids = fields.One2many("ob.ai.validation.result", "source_conversation_id", string="Validation Results", readonly=True)
    kpi_snapshot_ids = fields.One2many("ob.ai.kpi.snapshot", "source_conversation_id", string="KPI Snapshots", readonly=True)
    document_context_ids = fields.One2many("ob.ai.document.context", "source_conversation_id", string="Document Contexts", readonly=True)
    investigation_trace_ids = fields.One2many("ob.ai.investigation.trace", "conversation_id", string="Investigation Traces", readonly=True)
    memory_state_ids = fields.One2many("ob.ai.memory.state", "conversation_id", string="Memory States", readonly=True)
    last_snapshot_id = fields.Many2one("ob.ai.kpi.snapshot", string="Last KPI Snapshot", readonly=True)
    last_approval_id = fields.Many2one("ob.ai.approval", string="Last Approval", readonly=True)
    last_investigation_trace_id = fields.Many2one("ob.ai.investigation.trace", string="Last Investigation Trace", readonly=True)
    last_memory_state_id = fields.Many2one("ob.ai.memory.state", string="Last Memory State", readonly=True)
    last_agent_session_id = fields.Many2one("ob.ai.agent.session", string="Last Agent Session", readonly=True)
    last_agent_session_uuid = fields.Char(string="Last Agent Session UUID", readonly=True, copy=False, help="Bus channel suffix the frontend subscribes to: ob_ai_session_<uuid>.")
    last_route_payload = fields.Json(default=dict, readonly=True)
    message_count = fields.Integer(compute="_compute_counts")
    audit_log_count = fields.Integer(compute="_compute_counts")
    reminder_count = fields.Integer(compute="_compute_counts")
    approval_count = fields.Integer(compute="_compute_counts")
    validation_result_count = fields.Integer(compute="_compute_counts")
    kpi_snapshot_count = fields.Integer(compute="_compute_counts")
    document_context_count = fields.Integer(compute="_compute_counts")
    investigation_trace_count = fields.Integer(compute="_compute_counts")
    memory_state_count = fields.Integer(compute="_compute_counts")

    @api.depends(
        "ai_message_ids",
        "audit_log_ids",
        "reminder_ids",
        "approval_ids",
        "validation_result_ids",
        "kpi_snapshot_ids",
        "document_context_ids",
        "investigation_trace_ids",
        "memory_state_ids",
    )
    def _compute_counts(self):
        for record in self:
            record.message_count = len(record.ai_message_ids)
            record.audit_log_count = len(record.audit_log_ids)
            record.reminder_count = len(record.reminder_ids)
            record.approval_count = len(record.approval_ids)
            record.validation_result_count = len(record.validation_result_ids)
            record.kpi_snapshot_count = len(record.kpi_snapshot_ids)
            record.document_context_count = len(record.document_context_ids)
            record.investigation_trace_count = len(record.investigation_trace_ids)
            record.memory_state_count = len(record.memory_state_ids)

    def _compute_available_allowed_model_ids(self):
        available_models = self.env["ob.ai.access.service"].available_allowed_models()
        for record in self:
            record.available_allowed_model_ids = available_models

    def button_switch_mode(self):
        for record in self:
            record.chat_mode = not record.chat_mode

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        params = self.env["ir.config_parameter"].sudo()
        provider_id = int(params.get_param("ob_ai_assistant.default_provider_id", default="0") or 0)
        model_id = int(params.get_param("ob_ai_assistant.default_model_id", default="0") or 0)
        if "provider_id" in fields_list and provider_id:
            values.setdefault("provider_id", provider_id)
        if "model_id" in fields_list and model_id:
            values.setdefault("model_id", model_id)
        return values

    @api.onchange("provider_id")
    def _onchange_provider_id(self):
        for record in self:
            if record.provider_id and (not record.model_id or record.model_id.provider_id != record.provider_id):
                record.model_id = record.provider_id.default_model_id or record.provider_id.model_ids[:1]

    @api.onchange("allowed_model_id")
    def _onchange_allowed_model_id(self):
        for record in self:
            if (
                record.related_record_ref
                and record.allowed_model_id
                and record.related_record_ref._name != record.allowed_model_id.model_id.model
            ):
                record.related_record_ref = False

    @api.model
    def _selection_reference_models(self):
        configs = self.env["ob.ai.access.service"].available_allowed_models()
        return [(config.model_id.model, config.name or config.model_id.name) for config in configs]

    def _get_effective_provider(self):
        self.ensure_one()
        if self.provider_id:
            return self.provider_id
        params = self.env["ir.config_parameter"].sudo()
        provider_id = int(params.get_param("ob_ai_assistant.default_provider_id", default="0") or 0)
        provider = self.env["ob.ai.provider"].browse(provider_id).exists()
        return provider or self.env["ob.ai.provider"].search([("active", "=", True)], limit=1)

    def _get_effective_model(self, provider=False):
        self.ensure_one()
        provider = provider or self._get_effective_provider()
        if self.model_id and (not provider or self.model_id.provider_id == provider):
            return self.model_id
        params = self.env["ir.config_parameter"].sudo()
        model_id = int(params.get_param("ob_ai_assistant.default_model_id", default="0") or 0)
        model = self.env["ob.ai.model"].browse(model_id).exists()
        if model and (not provider or model.provider_id == provider):
            return model
        if not provider:
            return self.env["ob.ai.model"]
        return provider.default_model_id or provider.model_ids[:1]

    def _prepare_provider_messages(self, limit=12):
        self.ensure_one()
        history = self.ai_message_ids.sorted("id")
        if limit:
            history = history[-limit:]
        return [
            {
                "role": line.role,
                "content": line.content,
            }
            for line in history
            if line.role in ("user", "assistant") and line.content
        ]

    def action_open_audit_logs(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Audit Logs"),
            "res_model": "ob.ai.audit.log",
            "view_mode": "list,form",
            "domain": [("conversation_id", "=", self.id)],
            "context": {"default_conversation_id": self.id},
        }

    def _open_action_from_xmlid(self, xmlid, domain=None, context=None):
        self.ensure_one()
        try:
            action = self.env["ir.actions.actions"]._for_xml_id(xmlid)
        except ValueError as exc:
            raise UserError(_("The requested action is not available: %s", xmlid)) from exc
        action_context = dict(self.env.context)
        if context:
            action_context.update(context)
        if domain is not None:
            action["domain"] = domain
        action["context"] = action_context
        return action

    def action_open_reminders(self):
        self.ensure_one()
        return self._open_action_from_xmlid(
            "ob_ai_assistant.action_ob_ai_reminder",
            domain=[("source_conversation_id", "=", self.id)],
            context={"default_source_conversation_id": self.id},
        )

    def action_open_approvals(self):
        self.ensure_one()
        return self._open_action_from_xmlid(
            "ob_ai_assistant.action_ob_ai_approval",
            domain=[("source_conversation_id", "=", self.id)],
            context={"default_source_conversation_id": self.id},
        )

    def action_open_validation_results(self):
        self.ensure_one()
        return self._open_action_from_xmlid(
            "ob_ai_assistant.action_ob_ai_validation_result",
            domain=[("source_conversation_id", "=", self.id)],
            context={"default_source_conversation_id": self.id},
        )

    def action_open_investigation_traces(self):
        self.ensure_one()
        return self._open_action_from_xmlid(
            "ob_ai_assistant.action_ob_ai_investigation_trace",
            domain=[("conversation_id", "=", self.id)],
            context={"default_conversation_id": self.id},
        )

    def action_open_memory_states(self):
        self.ensure_one()
        return self._open_action_from_xmlid(
            "ob_ai_assistant.action_ob_ai_memory_state",
            domain=[("conversation_id", "=", self.id)],
            context={"default_conversation_id": self.id},
        )

    def action_send_prompt(self):
        message_model = self.env["ob.ai.message"]
        assistant_service = self.env["ob.ai.assistant.service"]
        for conversation in self:
            prompt = (conversation.prompt_input or "").strip()
            if not prompt:
                raise UserError(_("Enter a prompt before sending it to the AI assistant."))
            conversation._link_chat_attachments()
            provider = conversation._get_effective_provider()
            model = conversation._get_effective_model(provider=provider) if provider else False

            conversation.write({
                "state": "processing",
                "last_error": False,
                "provider_id": provider.id if provider else False,
                "model_id": model.id if model else False,
            })
            message_model.create({
                "conversation_id": conversation.id,
                "user_id": self.env.user.id,
                "role": "user",
                "content": prompt,
                "provider_id": provider.id if provider else False,
                "model_id": model.id if model else False,
            })

            if conversation.name == "New Conversation":
                conversation.name = prompt[:80]

            try:
                result = assistant_service.generate_response(
                    conversation,
                    prompt,
                    provider=provider,
                    model=model,
                )
                effective_provider = self.env["ob.ai.provider"].browse(result.get("provider_id") or 0).exists() or provider
                effective_model = self.env["ob.ai.model"].browse(result.get("model_id") or 0).exists() or model
                audit_log = assistant_service.create_audit_log(
                    conversation,
                    effective_provider,
                    effective_model,
                    prompt,
                    result=result,
                    status="success",
                    context_bundle=result.get("context_bundle"),
                )
                assistant_message = message_model.create({
                    "conversation_id": conversation.id,
                    "user_id": self.env.user.id,
                    "role": "assistant",
                    "content": result.get("text") or _("The AI provider returned an empty response."),
                    "provider_id": effective_provider.id if effective_provider else False,
                    "model_id": effective_model.id if effective_model else False,
                    "audit_log_id": audit_log.id,
                    "agent_session_id": result.get("agent_session_id") or False,
                    "input_tokens": result.get("input_tokens"),
                    "output_tokens": result.get("output_tokens"),
                })
                audit_log.message_id = assistant_message.id
                current_related_ref = False
                if conversation.related_record_ref:
                    current_related_ref = "%s,%s" % (
                        conversation.related_record_ref._name,
                        conversation.related_record_ref.id,
                    )
                focused_context = conversation.context_mode == "focused"
                next_allowed_model_id = (
                    result.get("allowed_model_id") or conversation.allowed_model_id.id or False
                ) if focused_context else (conversation.allowed_model_id.id or False)
                next_related_record_ref = (
                    result.get("target_record_ref") or current_related_ref or False
                ) if focused_context else (current_related_ref or False)
                conversation.write({
                    "state": "done",
                    "last_error": False,
                    "prompt_input": False,
                    "provider_id": effective_provider.id if effective_provider else False,
                    "model_id": effective_model.id if effective_model else False,
                    "allowed_model_id": next_allowed_model_id,
                    "related_record_ref": next_related_record_ref,
                    "intent_code": result.get("intent_code"),
                    "intent_confidence": result.get("confidence_score"),
                    "human_review_status": result.get("human_review_status") or "draft",
                    "suggested_action_summary": result.get("action_performed") or result.get("warning_message") or False,
                    "last_snapshot_id": result.get("snapshot_id") or conversation.last_snapshot_id.id or False,
                    "last_approval_id": result.get("approval_id") or conversation.last_approval_id.id or False,
                    "last_investigation_trace_id": result.get("investigation_trace_id") or conversation.last_investigation_trace_id.id or False,
                    "last_memory_state_id": result.get("memory_state_id") or conversation.last_memory_state_id.id or False,
                    "last_agent_session_id": result.get("agent_session_id") or conversation.last_agent_session_id.id or False,
                    "last_agent_session_uuid": result.get("agent_session_uuid") or False,
                    "last_route_payload": result.get("route_context") or {},
                })
            except UserError as exc:
                assistant_service.create_audit_log(
                    conversation,
                    provider,
                    model,
                    prompt,
                    result=False,
                    status="blocked",
                    error_message=str(exc),
                    context_bundle=False,
                )
                conversation.write({
                    "state": "error",
                    "last_error": str(exc),
                })
                raise
            except Exception as exc:  # noqa: BLE001
                assistant_service.create_audit_log(
                    conversation,
                    provider,
                    model,
                    prompt,
                    result=False,
                    status="error",
                    error_message=str(exc),
                    context_bundle=False,
                )
                conversation.write({
                    "state": "error",
                    "last_error": str(exc),
                })
                raise

    def _link_chat_attachments(self):
        for conversation in self:
            attachments = conversation.chat_attachment_ids.filtered(lambda attachment: attachment.type == "binary")
            if not attachments:
                continue
            # Link newly uploaded files to this conversation so they remain traceable and auditable.
            orphan_attachments = attachments.filtered(lambda attachment: not attachment.res_model and not attachment.res_id)
            if orphan_attachments:
                orphan_attachments.sudo().write({
                    "res_model": conversation._name,
                    "res_id": conversation.id,
                })
