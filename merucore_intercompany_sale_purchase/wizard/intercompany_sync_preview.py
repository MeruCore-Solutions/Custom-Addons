from markupsafe import Markup, escape

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError


class MeruCoreIntercompanySyncPreview(models.TransientModel):
    _name = "merucore.intercompany.sync.preview"
    _description = "MeruCore Intercompany Synchronization Preview"

    m_sale_order_id = fields.Many2one("sale.order", check_company=False)
    m_purchase_order_id = fields.Many2one("purchase.order", check_company=False)
    m_transaction_id = fields.Many2one(
        "merucore.intercompany.transaction",
        compute="m_compute_preview",
    )
    m_rule_id = fields.Many2one(
        "merucore.intercompany.rule",
        compute="m_compute_preview",
    )
    m_source_label = fields.Char(compute="m_compute_preview")
    m_counterpart_label = fields.Char(compute="m_compute_preview")
    m_difference_html = fields.Html(
        compute="m_compute_preview",
        sanitize=False,
    )
    m_destructive_change = fields.Boolean(compute="m_compute_preview")
    m_manager_confirmation = fields.Boolean(string="Manager Approved")

    @api.depends("m_sale_order_id", "m_purchase_order_id")
    def m_compute_preview(self):
        for wizard in self:
            payload = wizard.m_get_preview_payload()
            wizard.m_transaction_id = wizard.m_get_preview_transaction()
            wizard.m_rule_id = (
                wizard.m_sale_order_id.m_intercompany_rule_id
                or wizard.m_purchase_order_id.m_intercompany_rule_id
            )
            wizard.m_source_label = payload.get("m_source_label")
            wizard.m_counterpart_label = payload.get("m_counterpart_label")
            wizard.m_destructive_change = payload.get("m_destructive_change", False)
            wizard.m_difference_html = wizard.m_render_preview_html(payload.get("m_changes", []))

    def m_get_preview_transaction(self):
        self.ensure_one()
        return (
            self.m_sale_order_id.m_intercompany_transaction_id
            or self.m_purchase_order_id.m_intercompany_transaction_id
        )

    def m_get_preview_payload(self):
        self.ensure_one()
        if self.m_sale_order_id:
            if not self.m_sale_order_id.m_has_intercompany_sync_access():
                raise AccessError(_("You need access to both companies to preview synchronization."))
            return self.m_sale_order_id.m_collect_sync_differences()
        if self.m_purchase_order_id:
            if not self.m_purchase_order_id.m_has_intercompany_sync_access():
                raise AccessError(_("You need access to both companies to preview synchronization."))
            return self.m_purchase_order_id.m_collect_sync_differences()
        return {}

    def m_render_preview_html(self, m_changes):
        if not m_changes:
            return Markup("<p>%s</p>") % escape(_("No synchronized changes are pending."))
        rows = []
        for change in m_changes:
            rows.append(
                "<tr>"
                f"<td>{escape(change.get('action') or '')}</td>"
                f"<td>{escape(change.get('target') or '')}</td>"
                f"<td>{escape(change.get('field') or '')}</td>"
                f"<td>{escape(change.get('old') or '')}</td>"
                f"<td>{escape(change.get('new') or '')}</td>"
                "</tr>"
            )
        table = (
            "<table class='table table-sm table-striped'>"
            "<thead><tr><th>Action</th><th>Target</th><th>Field</th><th>Current</th><th>Proposed</th></tr></thead>"
            f"<tbody>{''.join(rows)}</tbody></table>"
        )
        return Markup(table)

    def m_action_apply(self):
        self.ensure_one()
        if self.m_destructive_change:
            if not self.env.user.has_group("merucore_intercompany_base.m_group_intercompany_manager"):
                raise AccessError(_("Only intercompany managers can approve destructive synchronization changes."))
            if not self.m_manager_confirmation:
                raise UserError(_("Tick Manager Approved before applying destructive synchronization changes."))
        if self.m_sale_order_id:
            self.m_sale_order_id.m_action_synchronize_now()
        elif self.m_purchase_order_id:
            self.m_purchase_order_id.m_action_synchronize_now()
        return {"type": "ir.actions.act_window_close"}
