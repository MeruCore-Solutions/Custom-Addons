from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError


class MeruCoreIntercompanyRetryWizard(models.TransientModel):
    _name = "merucore.intercompany.retry.wizard"
    _description = "MeruCore Intercompany Retry Wizard"

    m_transaction_id = fields.Many2one(
        "merucore.intercompany.transaction",
        required=True,
        readonly=True,
    )
    m_last_error_message = fields.Text(
        related="m_transaction_id.m_last_error_message",
        readonly=True,
    )
    m_current_retry_count = fields.Integer(
        related="m_transaction_id.m_retry_count",
        readonly=True,
    )
    m_max_retry_count = fields.Integer(
        related="m_transaction_id.m_rule_id.m_max_retry_count",
        readonly=True,
    )
    m_manager_note = fields.Text()
    m_force_retry = fields.Boolean(
        groups="merucore_intercompany_base.m_group_intercompany_manager"
    )

    @api.model
    def default_get(self, field_names):
        values = super().default_get(field_names)
        active_model = self.env.context.get("active_model")
        active_id = self.env.context.get("active_id")
        if active_model == "merucore.intercompany.transaction" and active_id and "m_transaction_id" in field_names:
            values["m_transaction_id"] = active_id
        return values

    def m_action_retry(self):
        self.ensure_one()
        transaction = self.m_transaction_id
        if transaction.m_state in {"done", "cancelled"}:
            raise UserError(_("Done or cancelled transactions cannot be retried."))
        if self.m_force_retry and not self.env.user.has_group(
            "merucore_intercompany_base.m_group_intercompany_manager"
        ):
            raise AccessError(_("Only intercompany managers can force a retry past the configured limit."))
        transaction.m_execute_retry(
            m_force_retry=self.m_force_retry,
            m_manager_note=self.m_manager_note,
        )
        return {"type": "ir.actions.act_window_close"}
