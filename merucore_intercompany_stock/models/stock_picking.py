from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class StockPicking(models.Model):
    _name = "stock.picking"
    _inherit = ["stock.picking", "merucore.intercompany.mixin"]

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
    m_intercompany_counterpart_picking_id = fields.Many2one(
        "stock.picking",
        copy=False,
        check_company=False,
    )
    m_intercompany_root_picking_id = fields.Many2one(
        "stock.picking",
        copy=False,
        check_company=False,
    )
    m_intercompany_origin_company_id = fields.Many2one(
        "res.company",
        copy=False,
        readonly=True,
        check_company=False,
    )
    m_intercompany_last_sync_at = fields.Datetime(copy=False, readonly=True)
    m_intercompany_manual_transfer_id = fields.Many2one(
        "merucore.intercompany.stock.transfer",
        copy=False,
        check_company=False,
    )
    m_intercompany_dual_company_access = fields.Boolean(
        compute="m_compute_intercompany_dual_company_access",
    )

    @api.depends("m_intercompany_transaction_id", "company_id", "partner_id", "picking_type_id")
    def m_compute_intercompany_rule_id(self):
        for picking in self:
            rule = False
            if picking.sudo().m_intercompany_transaction_id:
                rule = picking.sudo().m_intercompany_transaction_id.m_rule_id
            else:
                rule = picking.sudo().m_find_applicable_intercompany_rule()
            picking.m_intercompany_rule_id = rule

    @api.depends("company_id", "partner_id", "m_intercompany_transaction_id")
    def m_compute_intercompany_dual_company_access(self):
        for picking in self:
            companies = picking.sudo().m_get_intercompany_company_pair()
            if not companies:
                picking.m_intercompany_dual_company_access = False
                continue
            allowed = self.env.user.company_ids
            picking.m_intercompany_dual_company_access = all(company in allowed for company in companies)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault("m_intercompany_origin_company_id", vals.get("company_id"))
        pickings = super().create(vals_list)
        for picking in pickings.filtered(lambda record: not record.m_intercompany_root_picking_id):
            picking.with_context(m_skip_intercompany_sync=True).write(
                {"m_intercompany_root_picking_id": picking.id}
            )
        return pickings

    def copy_data(self, default=None):
        self.ensure_one()
        default = dict(default or {})
        default.setdefault("m_intercompany_transaction_id", False)
        default.setdefault("m_intercompany_counterpart_picking_id", False)
        default.setdefault("m_intercompany_last_sync_at", False)
        default.setdefault("m_intercompany_manual_transfer_id", False)
        default.setdefault(
            "m_intercompany_root_picking_id",
            self.m_intercompany_root_picking_id.id or self.id,
        )
        default.setdefault(
            "m_intercompany_origin_company_id",
            self.m_intercompany_origin_company_id.id or self.company_id.id,
        )
        default.setdefault("m_intercompany_sync_state", "pending")
        return super().copy_data(default=default)

    def action_cancel(self):
        result = super().action_cancel()
        if self.env.context.get("m_skip_intercompany_sync"):
            return result
        for picking in self.filtered(
            lambda record: record.m_intercompany_source_document and record.m_intercompany_counterpart_picking_id
        ):
            counterpart = picking.m_intercompany_counterpart_picking_id
            rule = picking.m_intercompany_transaction_id.m_rule_id or picking.m_find_applicable_intercompany_rule()
            if (
                rule
                and rule.m_stock_cancel_counterpart
                and counterpart.state not in {"done", "cancel"}
            ):
                counterpart.with_context(m_skip_intercompany_sync=True).action_cancel()
                picking.m_intercompany_transaction_id.m_log_event(
                    m_event_type="info",
                    m_summary=_("Counterpart picking cancelled"),
                    m_message=_(
                        "The counterpart picking %(picking)s was cancelled to match source cancellation.",
                        picking=counterpart.display_name,
                    ),
                    m_company_id=counterpart.company_id.id,
                )
        return result

    def _action_done(self):
        result = super()._action_done()
        if self.env.context.get("m_skip_intercompany_sync"):
            return result
        for picking in self:
            picking.m_run_intercompany_sync_on_done()
        return result

    def m_get_intercompany_company_pair(self):
        self.ensure_one()
        transaction = self.sudo().m_intercompany_transaction_id
        if transaction:
            return transaction.m_source_company_id | transaction.m_destination_company_id
        rule = self.m_find_applicable_intercompany_rule()
        return rule.m_source_company_id | rule.m_destination_company_id if rule else self.env["res.company"]

    def m_find_applicable_intercompany_rule(self):
        self.ensure_one()
        if not self.partner_id or self.picking_type_id.code != "outgoing":
            return False
        domain = [
            ("m_active", "=", True),
            ("m_stock_sync_enabled", "=", True),
            ("m_source_company_id", "=", self.company_id.id),
            ("m_destination_company_id", "!=", False),
            (
                "m_destination_company_id.partner_id",
                "child_of",
                self.partner_id.commercial_partner_id.id,
            ),
        ]
        rules = self.env["merucore.intercompany.rule"].search(domain)
        if len(rules) > 1:
            raise ValidationError(_("Multiple intercompany stock rules match this picking."))
        return rules[:1]

    def m_has_intercompany_stock_access(self):
        self.ensure_one()
        return bool(
            self.env.user.has_group("merucore_intercompany_base.m_group_intercompany_user")
            and self.m_intercompany_dual_company_access
        )

    def m_validate_intercompany_stock_eligibility(self, m_rule=False, m_automatic=False):
        self.ensure_one()
        rule = m_rule or self.m_find_applicable_intercompany_rule()
        if not rule:
            raise UserError(_("No active stock rule applies to this transfer."))
        if not rule.m_allows_stock_automatic_sync():
            raise UserError(_("The selected rule is not configured for automatic stock synchronization."))
        if self.state != "done":
            raise UserError(_("Only completed outgoing pickings can create an intercompany counterpart."))
        if self.picking_type_id.code != "outgoing":
            raise ValidationError(_("Only outgoing pickings can trigger automatic intercompany stock synchronization."))
        if not self.company_id.m_intercompany_enabled or not rule.m_destination_company_id.m_intercompany_enabled:
            raise ValidationError(_("Both companies must have intercompany enabled."))
        expected_partner = rule.m_destination_company_id.partner_id.commercial_partner_id
        if self.partner_id.commercial_partner_id != expected_partner:
            raise ValidationError(
                _(
                    "The transfer partner must represent %(company)s for the selected company pair.",
                    company=rule.m_destination_company_id.display_name,
                )
            )
        if not self.move_ids.filtered(lambda move: move.state == "done" and move.product_id.type != "service"):
            raise ValidationError(_("The transfer has no completed stockable or consumable product lines to synchronize."))
        if not m_automatic and not self.m_has_intercompany_stock_access():
            raise AccessError(_("You need access to both companies to synchronize this transfer."))
        return rule

    def m_prepare_intercompany_transaction_values(self, m_rule):
        self.ensure_one()
        return {
            "m_rule_id": m_rule.id,
            "m_source_company_id": m_rule.m_source_company_id.id,
            "m_destination_company_id": m_rule.m_destination_company_id.id,
            "m_transaction_type": "stock",
            "m_reference": self.name,
            "m_source_model": self._name,
            "m_source_res_id": self.id,
            "m_responsible_user_id": m_rule.m_responsible_user_id.id,
        }

    def m_mark_intercompany_sync_failed(self, m_message):
        self.with_context(m_skip_intercompany_sync=True).write(
            {"m_intercompany_sync_state": "failed"}
        )
        if self.m_intercompany_transaction_id:
            self.m_intercompany_transaction_id.with_context(m_intercompany_internal_write=True).write(
                {"m_last_error_message": m_message}
            )

    def m_mark_intercompany_synced(self):
        self.with_context(m_skip_intercompany_sync=True).write(
            {
                "m_intercompany_sync_state": "synced",
                "m_intercompany_last_sync_at": fields.Datetime.now(),
            }
        )

    def m_should_trigger_intercompany_sync(self):
        self.ensure_one()
        if self.env.context.get("m_skip_intercompany_sync"):
            return False
        if self.state != "done" or self.picking_type_id.code != "outgoing":
            return False
        if self.m_intercompany_counterpart_picking_id:
            return False
        if self.m_intercompany_transaction_id and not self.m_intercompany_source_document:
            return False
        return bool(self.m_intercompany_transaction_id or self.m_find_applicable_intercompany_rule())

    def m_run_intercompany_sync_on_done(self):
        for picking in self:
            if not picking.m_should_trigger_intercompany_sync():
                continue
            rule = picking.m_intercompany_transaction_id.m_rule_id or picking.m_find_applicable_intercompany_rule()
            picking.with_context(m_skip_intercompany_sync=True).write(
                {"m_intercompany_sync_state": "pending"}
            )
            picking.env["merucore.intercompany.transaction"].m_sync_from_stock_picking(
                picking,
                m_rule=rule,
                m_automatic=True,
            )

    def m_action_sync_intercompany_stock(self):
        for picking in self:
            rule = picking.m_intercompany_transaction_id.m_rule_id or picking.m_find_applicable_intercompany_rule()
            picking.env["merucore.intercompany.transaction"].m_sync_from_stock_picking(
                picking,
                m_rule=rule,
                m_automatic=False,
            )
        return True
