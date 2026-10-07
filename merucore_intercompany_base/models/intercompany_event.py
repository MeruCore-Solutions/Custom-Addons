from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError


class MeruCoreIntercompanyEvent(models.Model):
    _name = "merucore.intercompany.event"
    _description = "MeruCore Intercompany Event"
    _order = "m_event_at desc, id desc"

    m_transaction_id = fields.Many2one(
        "merucore.intercompany.transaction",
        required=True,
        index=True,
        ondelete="restrict",
    )
    m_company_id = fields.Many2one(
        "res.company",
        required=True,
        index=True,
        ondelete="restrict",
    )
    m_event_type = fields.Selection(
        selection=[
            ("info", "Info"),
            ("sync", "Synchronization"),
            ("warning", "Warning"),
            ("error", "Error"),
            ("retry", "Retry"),
            ("state_change", "State Change"),
        ],
        required=True,
        default="info",
        index=True,
    )
    m_summary = fields.Char(required=True, translate=True)
    m_message = fields.Text(translate=True)
    m_event_at = fields.Datetime(required=True, default=fields.Datetime.now, index=True)
    m_user_id = fields.Many2one(
        "res.users",
        default=lambda self: self.env.user,
        ondelete="set null",
    )
    m_model_name = fields.Char()
    m_res_id = fields.Integer()
    m_old_value = fields.Text()
    m_new_value = fields.Text()
    m_technical_details = fields.Text(
        groups="merucore_intercompany_base.m_group_intercompany_manager"
    )
    m_retry_number = fields.Integer()
    m_resolved = fields.Boolean(default=False, index=True)
    m_resolved_at = fields.Datetime()
    m_resolved_by_id = fields.Many2one("res.users", ondelete="set null")

    @api.depends("m_event_type", "m_summary", "m_event_at")
    def _compute_display_name(self):
        for event in self:
            event.display_name = _(
                "%(type)s - %(summary)s",
                type=dict(self._fields["m_event_type"].selection).get(event.m_event_type, _("Event")),
                summary=event.m_summary,
            )

    def m_action_resolve(self):
        self.m_check_manager_permissions()
        for event in self.filtered(lambda current: not current.m_resolved):
            event.with_context(m_intercompany_event_resolve=True).write(
                {
                    "m_resolved": True,
                    "m_resolved_at": fields.Datetime.now(),
                    "m_resolved_by_id": self.env.user.id,
                }
            )
            event.m_transaction_id.m_close_issue_activities(event)

    def m_action_reopen(self):
        self.m_check_manager_permissions()
        for event in self.filtered("m_resolved"):
            event.with_context(m_intercompany_event_resolve=True).write(
                {
                    "m_resolved": False,
                    "m_resolved_at": False,
                    "m_resolved_by_id": False,
                }
            )
            if event.m_event_type in {"warning", "error"}:
                event.m_transaction_id.m_schedule_issue_activity(event)

    def m_check_manager_permissions(self):
        if not self.env.user.has_group("merucore_intercompany_base.m_group_intercompany_manager"):
            raise AccessError(_("Only intercompany managers can resolve or reopen events."))

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su and not self.env.context.get("m_intercompany_event_create"):
            raise AccessError(_("Events can only be created through controlled intercompany methods."))
        return super().create(vals_list)

    def write(self, vals):
        if self.env.context.get("module_uninstall"):
            return super().write(vals)
        allowed_fields = {"m_resolved", "m_resolved_at", "m_resolved_by_id"}
        if set(vals) - allowed_fields:
            raise AccessError(_("Intercompany events are immutable. Only resolution fields can be updated."))
        if not self.env.su:
            if not self.env.context.get("m_intercompany_event_resolve"):
                raise AccessError(_("Event resolution must use the dedicated actions."))
            self.m_check_manager_permissions()
        return super().write(vals)

    def unlink(self):
        if self.env.context.get("module_uninstall"):
            return super().unlink()
        self.check_access("unlink")
        raise ValidationError(_("Intercompany audit events cannot be deleted."))
