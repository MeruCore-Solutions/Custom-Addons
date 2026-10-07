import json

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class PurchaseOrder(models.Model):
    _inherit = ["purchase.order", "merucore.intercompany.mixin"]

    m_intercompany_rule_id = fields.Many2one(
        "merucore.intercompany.rule",
        compute="m_compute_intercompany_rule_id",
    )
    m_intercompany_sync_state = fields.Selection(
        selection=[
            ("not_applicable", "Not Applicable"),
            ("pending", "Pending"),
            ("synced", "Synced"),
            ("warning", "Warning"),
            ("failed", "Failed"),
        ],
        default="not_applicable",
        copy=False,
        readonly=True,
    )
    m_intercompany_counterpart_id = fields.Many2one(
        "sale.order",
        compute="m_compute_intercompany_counterpart_id",
    )
    m_intercompany_last_sync_at = fields.Datetime(copy=False, readonly=True)
    m_intercompany_sync_version = fields.Integer(default=0, copy=False, readonly=True)
    m_intercompany_origin_company_id = fields.Many2one(
        "res.company",
        copy=False,
        readonly=True,
        check_company=False,
    )
    m_intercompany_locked_fields = fields.Text(copy=False, readonly=True)
    m_intercompany_dual_company_access = fields.Boolean(
        compute="m_compute_intercompany_dual_company_access",
    )

    @api.depends("m_intercompany_transaction_id")
    def m_compute_intercompany_rule_id(self):
        for order in self:
            rule = False
            if order.sudo().m_intercompany_transaction_id:
                rule = order.sudo().m_intercompany_transaction_id.m_rule_id
            else:
                rule = order.sudo().m_find_applicable_intercompany_rule()
            order.m_intercompany_rule_id = rule

    @api.depends("m_intercompany_transaction_id")
    def m_compute_intercompany_counterpart_id(self):
        for order in self:
            counterpart = order.sudo().m_intercompany_transaction_id.m_sale_order_id
            order.m_intercompany_counterpart_id = (
                counterpart if counterpart and order.m_intercompany_dual_company_access else False
            )

    @api.depends("company_id", "partner_id", "m_intercompany_transaction_id")
    def m_compute_intercompany_dual_company_access(self):
        for order in self:
            companies = order.sudo().m_get_intercompany_company_pair()
            if not companies:
                order.m_intercompany_dual_company_access = False
                continue
            allowed = self.env.user.company_ids
            order.m_intercompany_dual_company_access = all(company in allowed for company in companies)

    def copy(self, default=None):
        default = dict(default or {})
        default.update(self.m_prepare_copy_defaults())
        return super().copy(default=default)

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get("m_skip_intercompany_sync") and self.m_should_mark_pending(vals):
            self.m_mark_intercompany_pending()
        return result

    def unlink(self):
        if self.env.context.get("module_uninstall"):
            return super().unlink()
        if self.filtered("m_intercompany_transaction_id"):
            raise ValidationError(_("Linked intercompany purchase orders cannot be deleted."))
        return super().unlink()

    def read(self, fields=None, load="_classic_read"):
        rows = super().read(fields=fields, load=load)
        protected = {
            "m_intercompany_transaction_id",
            "m_intercompany_rule_id",
            "m_intercompany_health_state",
            "m_intercompany_counterpart_id",
            "m_intercompany_last_sync_at",
            "m_intercompany_sync_version",
            "m_intercompany_origin_company_id",
            "m_intercompany_locked_fields",
        }
        row_map = {record.id: record for record in self.browse([row["id"] for row in rows])}
        for row in rows:
            record = row_map.get(row["id"])
            if record and not record.m_intercompany_dual_company_access:
                for field_name in protected & set(row):
                    row[field_name] = False
        return rows

    def button_confirm(self):
        result = super().button_confirm()
        if self.env.context.get("m_skip_intercompany_sync"):
            return result
        for order in self:
            rule = order.sudo().m_find_applicable_intercompany_rule()
            if not rule or not rule.m_allows_purchase_trigger() or rule.m_creation_timing != "on_confirmation":
                continue
            order.m_create_or_update_counterpart(
                m_rule=rule,
                m_automatic=True,
                m_raise_on_error=False,
            )
        return result

    def button_cancel(self):
        result = super().button_cancel()
        if self.env.context.get("m_skip_intercompany_sync"):
            return result
        self.m_handle_counterpart_cancellation()
        return result

    def button_draft(self):
        result = super().button_draft()
        self.m_log_reset_divergence()
        return result

    def m_prepare_copy_defaults(self):
        self.ensure_one()
        return {
            "m_intercompany_transaction_id": False,
            "m_intercompany_sync_state": "not_applicable",
            "m_intercompany_last_sync_at": False,
            "m_intercompany_sync_version": 0,
            "m_intercompany_origin_company_id": False,
            "m_intercompany_locked_fields": False,
        }

    def m_should_mark_pending(self, vals):
        tracked_fields = {
            "partner_id",
            "currency_id",
            "date_order",
            "date_planned",
            "note",
            "origin",
            "partner_ref",
            "payment_term_id",
            "order_line",
        }
        return bool(tracked_fields & set(vals) and self.filtered("m_intercompany_transaction_id"))

    def m_get_intercompany_company_pair(self):
        self.ensure_one()
        transaction = self.sudo().m_intercompany_transaction_id
        if transaction:
            return transaction.m_source_company_id | transaction.m_destination_company_id
        rules = self.env["merucore.intercompany.rule"].sudo().search(
            [
                ("m_active", "=", True),
                ("m_sale_purchase_enabled", "=", True),
                ("m_destination_company_id", "=", self.company_id.id),
                (
                    "m_source_company_id.partner_id",
                    "child_of",
                    self.partner_id.commercial_partner_id.id,
                ),
            ],
            limit=1,
        )
        return rules.m_source_company_id | rules.m_destination_company_id

    def m_find_applicable_intercompany_rule(self):
        self.ensure_one()
        domain = [
            ("m_active", "=", True),
            ("m_sale_purchase_enabled", "=", True),
            ("m_destination_company_id", "=", self.company_id.id),
            (
                "m_source_company_id.partner_id",
                "child_of",
                self.partner_id.commercial_partner_id.id,
            ),
        ]
        rules = self.env["merucore.intercompany.rule"].search(domain)
        if len(rules) > 1:
            raise ValidationError(_("Multiple intercompany rules match this purchase order."))
        return rules[:1]

    def m_has_intercompany_sync_access(self):
        self.ensure_one()
        return bool(
            self.env.user.has_group("merucore_intercompany_base.m_group_intercompany_user")
            and self.m_intercompany_dual_company_access
        )

    def m_validate_intercompany_eligibility(self, m_rule=False, m_purpose="sync", m_automatic=False):
        self.ensure_one()
        rule = m_rule or self.m_find_applicable_intercompany_rule()
        if not rule:
            raise UserError(_("No active sale and purchase rule applies to this purchase order."))
        if not rule.m_allows_purchase_trigger():
            raise UserError(_("The selected rule is not configured to trigger from purchase orders."))
        if not self.company_id.m_intercompany_enabled or not rule.m_source_company_id.m_intercompany_enabled:
            raise ValidationError(_("Both companies must have intercompany enabled."))
        if self.state == "cancel":
            raise UserError(_("Cancelled purchase orders cannot run intercompany synchronization."))
        if any(line.is_downpayment for line in self.order_line):
            raise ValidationError(_("Down-payment purchase order lines are not supported for intercompany synchronization."))
        if rule.m_company_partner_validation:
            expected_partner = rule.m_source_company_id.partner_id.commercial_partner_id
            if self.partner_id.commercial_partner_id != expected_partner:
                raise ValidationError(
                    _(
                        "The purchase order vendor must represent %(company)s for the selected company pair.",
                        company=rule.m_source_company_id.display_name,
                    )
                )
        if not m_automatic and not self.m_has_intercompany_sync_access():
            raise AccessError(_("You need access to both companies to synchronize this purchase order."))
        return rule

    def m_prepare_intercompany_transaction_values(self, m_rule):
        self.ensure_one()
        return {
            "m_rule_id": m_rule.id,
            "m_source_company_id": m_rule.m_source_company_id.id,
            "m_destination_company_id": m_rule.m_destination_company_id.id,
            "m_transaction_type": "sale_purchase",
            "m_reference": self.name,
            "m_destination_model": self._name,
            "m_destination_res_id": self.id,
            "m_responsible_user_id": m_rule.m_responsible_user_id.id,
        }

    def m_create_or_update_counterpart(
        self,
        m_rule=False,
        m_automatic=False,
        m_raise_on_error=True,
        m_preview_only=False,
        m_from_retry=False,
    ):
        self.ensure_one()
        return self.env["merucore.intercompany.transaction"].m_sync_from_purchase_order(
            m_purchase_order=self,
            m_rule=m_rule,
            m_automatic=m_automatic,
            m_raise_on_error=m_raise_on_error,
            m_preview_only=m_preview_only,
            m_from_retry=m_from_retry,
        )

    def m_collect_sync_differences(self, m_rule=False):
        self.ensure_one()
        return self.env["merucore.intercompany.transaction"].m_collect_purchase_to_sale_preview(
            m_purchase_order=self,
            m_rule=m_rule,
        )

    def m_apply_sync_differences(self, m_rule=False):
        self.ensure_one()
        return self.m_create_or_update_counterpart(
            m_rule=m_rule,
            m_automatic=False,
            m_raise_on_error=True,
            m_preview_only=False,
        )

    def m_mark_intercompany_pending(self):
        linked_orders = self.filtered("m_intercompany_transaction_id")
        if not linked_orders:
            return
        linked_orders.with_context(m_skip_intercompany_sync=True).write(
            {"m_intercompany_sync_state": "pending"}
        )

    def m_mark_intercompany_sync_failed(self, m_message=False):
        self.with_context(m_skip_intercompany_sync=True).write(
            {
                "m_intercompany_sync_state": "failed",
                "m_intercompany_last_sync_at": False,
                "m_intercompany_locked_fields": json.dumps({"message": m_message or ""}),
            }
        )

    def m_mark_intercompany_synced(self, m_sync_version, m_snapshot, m_sync_at):
        self.with_context(m_skip_intercompany_sync=True).write(
            {
                "m_intercompany_sync_state": "synced",
                "m_intercompany_last_sync_at": m_sync_at,
                "m_intercompany_sync_version": m_sync_version,
                "m_intercompany_locked_fields": m_snapshot,
            }
        )

    def m_action_create_counterpart_order(self):
        self.ensure_one()
        self.m_create_or_update_counterpart(
            m_automatic=False,
            m_raise_on_error=True,
        )
        return True

    def m_action_open_intercompany_counterpart_order(self):
        self.ensure_one()
        if not self.m_intercompany_dual_company_access or not self.m_intercompany_counterpart_id:
            raise UserError(_("The counterpart sales order is unavailable or you do not have access to it."))
        return self.m_intercompany_transaction_id.m_action_open_sale_order()

    def m_action_preview_synchronization(self):
        self.ensure_one()
        if not self.m_has_intercompany_sync_access():
            raise AccessError(_("You need access to both companies to preview synchronization."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Intercompany Synchronization Preview"),
            "res_model": "merucore.intercompany.sync.preview",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_m_purchase_order_id": self.id,
                "allowed_company_ids": (self.m_get_intercompany_company_pair() or self.company_id).ids,
            },
        }

    def m_action_synchronize_now(self):
        self.ensure_one()
        if self.m_intercompany_counterpart_id and self.m_intercompany_rule_id.m_sync_direction not in {
            "destination_to_source",
            "bidirectional",
        }:
            raise UserError(_("This rule does not allow the purchase order side to drive synchronization updates."))
        self.m_apply_sync_differences(m_rule=self.m_intercompany_rule_id)
        return True

    def m_action_retry_failed_synchronization(self):
        self.ensure_one()
        if not self.m_intercompany_transaction_id:
            raise UserError(_("There is no intercompany transaction to retry."))
        return self.m_intercompany_transaction_id.m_action_open_retry_wizard()

    def m_handle_counterpart_cancellation(self):
        for order in self.filtered("m_intercompany_counterpart_id"):
            rule = order.sudo().m_intercompany_rule_id
            if not rule or not rule.m_cancel_counterpart:
                continue
            try:
                order.m_intercompany_counterpart_id.with_context(m_skip_intercompany_sync=True).action_cancel()
            except Exception as error:  # pylint: disable=broad-except
                order.m_intercompany_transaction_id.m_mark_warning(
                    m_summary=_("Counterpart cancellation blocked"),
                    m_message=_("The counterpart sales order could not be cancelled safely."),
                    m_technical_details=order.m_intercompany_transaction_id.m_sanitize_exception_message(error),
                )

    def m_log_reset_divergence(self):
        for order in self.filtered("m_intercompany_transaction_id"):
            counterpart = order.sudo().m_intercompany_transaction_id.m_sale_order_id
            if counterpart and counterpart.state not in {"draft", "sent", "cancel"}:
                order.m_intercompany_transaction_id.m_mark_warning(
                    m_summary=_("Purchase order reset diverged from counterpart"),
                    m_message=_("The purchase order was reset to draft while the linked sales order kept a different state."),
                )
