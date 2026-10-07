from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class AccountMove(models.Model):
    _name = "account.move"
    _inherit = ["account.move", "merucore.intercompany.mixin"]

    m_intercompany_rule_id = fields.Many2one(
        "merucore.intercompany.rule",
        compute="m_compute_intercompany_rule_id",
    )
    m_intercompany_document_mapping_ids = fields.One2many(
        "merucore.intercompany.document.mapping",
        "m_move_id",
        string="Intercompany Document Mappings",
    )
    m_intercompany_role = fields.Selection(
        selection=[
            ("source_customer_invoice", "Source Customer Invoice"),
            ("destination_vendor_bill", "Destination Vendor Bill"),
            ("source_vendor_bill", "Source Vendor Bill"),
            ("destination_customer_invoice", "Destination Customer Invoice"),
            ("source_customer_refund", "Source Customer Refund"),
            ("destination_vendor_refund", "Destination Vendor Refund"),
            ("source_vendor_refund", "Source Vendor Refund"),
            ("destination_customer_refund", "Destination Customer Refund"),
        ],
        compute="m_compute_intercompany_role",
        store=True,
    )
    m_intercompany_counterpart_move_ids = fields.Many2many(
        "account.move",
        compute="m_compute_intercompany_counterpart_move_ids",
        string="Intercompany Counterparts",
    )
    m_intercompany_counterpart_count = fields.Integer(
        compute="m_compute_intercompany_counterpart_move_ids",
    )
    m_intercompany_origin_move_id = fields.Many2one(
        "account.move",
        copy=False,
        index=True,
        check_company=False,
    )
    m_intercompany_document_key = fields.Char(copy=False, index=True)
    m_intercompany_sync_state = fields.Selection(
        selection=[
            ("not_applicable", "Not Applicable"),
            ("pending", "Pending"),
            ("draft_pair", "Draft Pair"),
            ("posted", "Posted"),
            ("conflict", "Conflict"),
            ("failed", "Failed"),
            ("reversed", "Reversed"),
        ],
        default="not_applicable",
        copy=False,
        readonly=True,
    )
    m_intercompany_sync_version = fields.Integer(default=0, copy=False, readonly=True)
    m_intercompany_last_sync_at = fields.Datetime(copy=False, readonly=True)
    m_intercompany_last_error = fields.Text(copy=False, readonly=True)
    m_intercompany_posting_pending = fields.Boolean(copy=False, readonly=True)
    m_intercompany_matching_state = fields.Selection(
        selection=[
            ("not_applicable", "Not Applicable"),
            ("waiting_counterpart", "Waiting Counterpart"),
            ("matched", "Matched"),
            ("mismatch", "Mismatch"),
        ],
        default="not_applicable",
        copy=False,
        readonly=True,
    )
    m_intercompany_dual_company_access = fields.Boolean(
        compute="m_compute_intercompany_dual_company_access",
    )

    @api.depends("m_intercompany_transaction_id")
    def m_compute_intercompany_rule_id(self):
        for move in self:
            rule = False
            if move.sudo().m_intercompany_transaction_id:
                rule = move.sudo().m_intercompany_transaction_id.m_rule_id
            elif move.is_invoice(include_receipts=False):
                rule = move.sudo().m_find_applicable_intercompany_rule()
            move.m_intercompany_rule_id = rule

    @api.depends("m_intercompany_transaction_id", "m_intercompany_rule_id", "company_id", "move_type")
    def m_compute_intercompany_role(self):
        for move in self:
            move.m_intercompany_role = move.m_get_intercompany_role()

    @api.depends("m_intercompany_transaction_id", "m_intercompany_document_mapping_ids")
    def m_compute_intercompany_counterpart_move_ids(self):
        for move in self:
            counterparts = self.env["account.move"]
            transaction = move.sudo().m_intercompany_transaction_id
            if transaction:
                counterparts = transaction.m_account_document_mapping_ids.mapped("m_move_id") - move
                if not move.m_intercompany_dual_company_access:
                    counterparts = self.env["account.move"]
            move.m_intercompany_counterpart_move_ids = [fields.Command.set(counterparts.ids)]
            move.m_intercompany_counterpart_count = len(counterparts)

    @api.depends("company_id", "partner_id", "m_intercompany_transaction_id")
    def m_compute_intercompany_dual_company_access(self):
        for move in self:
            companies = move.sudo().m_get_intercompany_company_pair()
            if not companies:
                move.m_intercompany_dual_company_access = False
                continue
            allowed_companies = self.env.user.company_ids
            move.m_intercompany_dual_company_access = all(company in allowed_companies for company in companies)

    @api.depends("m_intercompany_transaction_id", "move_type", "state")
    def m_compute_intercompany_document_context(self):
        super().m_compute_intercompany_document_context()

    @api.model_create_multi
    def create(self, vals_list):
        moves = super().create(vals_list)
        if self.env.context.get("m_skip_intercompany_account_sync"):
            return moves
        for move in moves.filtered(lambda current: current.state == "draft" and current.is_invoice(include_receipts=False)):
            rule = move.sudo().m_find_applicable_intercompany_rule()
            if not rule or rule.m_counterpart_creation_timing != "on_draft_creation":
                continue
            move.m_create_or_update_intercompany_counterpart(
                m_rule=rule,
                m_automatic=True,
                m_raise_on_error=rule.m_posting_failure_policy == "block_source_post",
            )
        return moves

    def write(self, vals):
        result = super().write(vals)
        if self.env.context.get("m_skip_intercompany_account_sync"):
            return result
        if self.m_should_mark_intercompany_pending(vals):
            self.m_mark_intercompany_pending()
        return result

    def copy_data(self, default=None):
        default = dict(default or {})
        default.update(
            {
                "m_intercompany_transaction_id": False,
                "m_intercompany_origin_move_id": False,
                "m_intercompany_document_key": False,
                "m_intercompany_sync_state": "not_applicable",
                "m_intercompany_sync_version": 0,
                "m_intercompany_last_sync_at": False,
                "m_intercompany_last_error": False,
                "m_intercompany_posting_pending": False,
                "m_intercompany_matching_state": "not_applicable",
            }
        )
        return super().copy_data(default=default)

    def unlink(self):
        if self.env.context.get("module_uninstall"):
            return super().unlink()
        if self.filtered("m_intercompany_transaction_id"):
            raise ValidationError(_("Linked intercompany accounting documents cannot be deleted."))
        return super().unlink()

    def read(self, fields=None, load="_classic_read"):
        rows = super().read(fields=fields, load=load)
        protected = {
            "m_intercompany_transaction_id",
            "m_intercompany_rule_id",
            "m_intercompany_health_state",
            "m_intercompany_role",
            "m_intercompany_counterpart_move_ids",
            "m_intercompany_origin_move_id",
            "m_intercompany_document_key",
            "m_intercompany_sync_state",
            "m_intercompany_last_sync_at",
            "m_intercompany_last_error",
            "m_intercompany_matching_state",
        }
        record_map = {move.id: move for move in self.browse([row["id"] for row in rows])}
        for row in rows:
            move = record_map.get(row["id"])
            if move and not move.m_intercompany_dual_company_access:
                for field_name in protected & set(row):
                    row[field_name] = False
        return rows

    def action_post(self):
        result = super().action_post()
        if self.env.context.get("m_skip_intercompany_account_sync"):
            return result
        for move in self.filtered(lambda current: current.is_invoice(include_receipts=False)):
            rule = move.sudo().m_find_applicable_intercompany_rule()
            if not rule or rule.m_counterpart_creation_timing != "on_source_post":
                continue
            try:
                move.m_create_or_update_intercompany_counterpart(
                    m_rule=rule,
                    m_automatic=True,
                    m_raise_on_error=rule.m_posting_failure_policy == "block_source_post",
                )
            except Exception:  # pylint: disable=broad-except
                if rule.m_posting_failure_policy == "block_source_post":
                    raise
        return result

    def button_cancel(self):
        result = super().button_cancel()
        if self.env.context.get("m_skip_intercompany_account_sync"):
            return result
        for move in self.filtered("m_intercompany_transaction_id"):
            move.m_handle_intercompany_cancellation()
        return result

    def m_should_mark_intercompany_pending(self, vals):
        tracked_fields = {
            "partner_id",
            "currency_id",
            "date",
            "invoice_date",
            "invoice_date_due",
            "invoice_payment_term_id",
            "fiscal_position_id",
            "payment_reference",
            "ref",
            "invoice_origin",
            "narration",
            "invoice_line_ids",
        }
        return bool(tracked_fields & set(vals) and self.filtered("m_intercompany_transaction_id"))

    def m_get_intercompany_company_pair(self):
        self.ensure_one()
        transaction = self.sudo().m_intercompany_transaction_id
        if transaction:
            return transaction.m_source_company_id | transaction.m_destination_company_id
        rule = self.sudo().m_find_applicable_intercompany_rule()
        return rule.m_source_company_id | rule.m_destination_company_id

    def m_get_other_intercompany_company(self, m_rule):
        self.ensure_one()
        if self.company_id == m_rule.m_source_company_id:
            return m_rule.m_destination_company_id
        if self.company_id == m_rule.m_destination_company_id:
            return m_rule.m_source_company_id
        return self.env["res.company"]

    def m_get_intercompany_role(self):
        self.ensure_one()
        rule = self.m_intercompany_rule_id or self.sudo().m_find_applicable_intercompany_rule()
        if not rule:
            return False
        if self.company_id == rule.m_source_company_id:
            prefix = "source"
        elif self.company_id == rule.m_destination_company_id:
            prefix = "destination"
        else:
            return False
        suffix_map = {
            "out_invoice": "customer_invoice",
            "in_invoice": "vendor_bill",
            "out_refund": "customer_refund",
            "in_refund": "vendor_refund",
        }
        suffix = suffix_map.get(self.move_type)
        return f"{prefix}_{suffix}" if suffix else False

    def m_find_applicable_intercompany_rule(self):
        self.ensure_one()
        if not self.is_invoice(include_receipts=False) or not self.partner_id:
            return self.env["merucore.intercompany.rule"]
        commercial_partner = self.partner_id.commercial_partner_id
        if self.move_type.startswith("out_"):
            trigger_types = ["customer_invoice", "both"]
        else:
            trigger_types = ["vendor_bill", "both"]
        domain = [
            ("m_active", "=", True),
            ("m_account_sync_enabled", "=", True),
            ("m_trigger_document", "in", trigger_types),
        ]
        if self.company_id:
            domain = [
                ("m_active", "=", True),
                ("m_account_sync_enabled", "=", True),
                ("m_trigger_document", "in", trigger_types),
                "|",
                "&",
                ("m_source_company_id", "=", self.company_id.id),
                ("m_sync_direction", "in", ["source_to_destination", "bidirectional"]),
                "&",
                ("m_destination_company_id", "=", self.company_id.id),
                ("m_sync_direction", "in", ["destination_to_source", "bidirectional"]),
            ]
        rules = self.env["merucore.intercompany.rule"].search(domain)
        rules = rules.filtered(
            lambda rule: rule.m_allows_account_trigger(self)
            and (
                (
                    self.company_id == rule.m_source_company_id
                    and rule.m_destination_company_id.partner_id.commercial_partner_id == commercial_partner
                )
                or (
                    self.company_id == rule.m_destination_company_id
                    and rule.m_source_company_id.partner_id.commercial_partner_id == commercial_partner
                )
            )
        )
        if len(rules) > 1:
            raise ValidationError(_("Multiple intercompany accounting rules match this invoice or bill."))
        return rules[:1]

    def m_has_intercompany_sync_access(self):
        self.ensure_one()
        return bool(
            self.env.user.has_group("merucore_intercompany_base.m_group_intercompany_user")
            and self.m_intercompany_dual_company_access
        )

    def m_validate_intercompany_account_eligibility(self, m_rule=False, m_purpose="sync", m_automatic=False):
        self.ensure_one()
        rule = m_rule or self.m_find_applicable_intercompany_rule()
        if not rule:
            raise UserError(_("No active invoice/bill synchronization rule applies to this document."))
        if not rule.m_allows_account_trigger(self):
            raise UserError(_("The selected rule is not configured to trigger from this accounting document."))
        if not self.company_id.m_intercompany_enabled or not self.m_get_other_intercompany_company(rule).m_intercompany_enabled:
            raise ValidationError(_("Both companies must have intercompany enabled."))
        if self.state == "cancel":
            raise UserError(_("Cancelled invoices and bills cannot run intercompany synchronization."))
        expected_partner = self.m_get_other_intercompany_company(rule).partner_id.commercial_partner_id
        if rule.m_partner_validation and self.partner_id.commercial_partner_id != expected_partner:
            raise ValidationError(
                _(
                    "The accounting partner must represent %(company)s for the selected company pair.",
                    company=expected_partner.display_name,
                )
            )
        if not m_automatic and not self.m_has_intercompany_sync_access():
            raise AccessError(_("You need access to both companies to synchronize this invoice or bill."))
        return rule

    def m_prepare_intercompany_transaction_values(self, m_rule):
        self.ensure_one()
        vals = {
            "m_rule_id": m_rule.id,
            "m_source_company_id": m_rule.m_source_company_id.id,
            "m_destination_company_id": m_rule.m_destination_company_id.id,
            "m_transaction_type": "invoice_bill",
            "m_reference": self.name or self.ref or self.payment_reference or "/",
            "m_responsible_user_id": m_rule.m_get_account_responsible_user().id,
        }
        if self.company_id == m_rule.m_source_company_id:
            vals.update(
                {
                    "m_source_model": self._name,
                    "m_source_res_id": self.id,
                }
            )
        else:
            vals.update(
                {
                    "m_destination_model": self._name,
                    "m_destination_res_id": self.id,
                }
            )
        return vals

    def m_get_commercial_lines(self):
        self.ensure_one()
        return self.invoice_line_ids.filtered(
            lambda line: line.display_type in {"product", "line_section", "line_subsection", "line_note"}
        )

    def m_mark_intercompany_pending(self):
        timestamp = fields.Datetime.now()
        for move in self.filtered("m_intercompany_transaction_id"):
            values = {
                "m_intercompany_sync_state": "pending",
                "m_intercompany_matching_state": "waiting_counterpart",
                "m_intercompany_last_sync_at": timestamp,
                "m_intercompany_sync_version": move.m_intercompany_sync_version + 1,
            }
            move.with_context(m_skip_intercompany_account_sync=True).write(values)
            transaction = move.m_intercompany_transaction_id
            transaction.with_context(m_intercompany_internal_write=True).write(
                {
                    "m_account_sync_state": "waiting_counterpart",
                    "m_pending_account_conflict": True,
                    "m_last_account_sync_at": timestamp,
                    "m_account_sync_version": transaction.m_account_sync_version + 1,
                }
            )

    def m_action_sync_intercompany_counterpart(self):
        for move in self:
            move.m_create_or_update_intercompany_counterpart(
                m_rule=move.m_intercompany_rule_id or move.m_find_applicable_intercompany_rule(),
                m_automatic=False,
                m_raise_on_error=True,
            )
        return True

    def m_action_open_intercompany_counterparts(self):
        self.ensure_one()
        counterpart_moves = self.m_intercompany_counterpart_move_ids
        if not counterpart_moves:
            raise UserError(_("There are no linked counterpart accounting documents."))
        action = {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [("id", "in", counterpart_moves.ids)],
            "context": {"create": False, "allowed_company_ids": self.m_get_intercompany_company_pair().ids},
        }
        if len(counterpart_moves) == 1:
            action.update({"view_mode": "form", "res_id": counterpart_moves.id, "domain": False})
        return action

    def m_create_or_update_intercompany_counterpart(
        self,
        m_rule=False,
        m_automatic=False,
        m_raise_on_error=True,
        m_from_retry=False,
    ):
        self.ensure_one()
        return self.env["merucore.intercompany.transaction"].m_sync_from_account_move(
            m_account_move=self,
            m_rule=m_rule,
            m_automatic=m_automatic,
            m_raise_on_error=m_raise_on_error,
            m_from_retry=m_from_retry,
        )

    def m_handle_intercompany_cancellation(self):
        for move in self.filtered("m_intercompany_transaction_id"):
            counterparts = move.m_intercompany_counterpart_move_ids.filtered(lambda current: current.state == "draft")
            rule = move.m_intercompany_rule_id
            if counterparts and rule and rule.m_cancel_counterpart_draft:
                counterparts.with_context(
                    m_skip_intercompany_account_sync=True,
                    m_skip_intercompany_sync=True,
                ).button_cancel()
                move.m_intercompany_transaction_id.with_context(m_intercompany_internal_write=True).write(
                    {"m_account_sync_state": "reversed"}
                )
            else:
                move.m_intercompany_transaction_id.m_mark_warning(
                    m_summary=_("Intercompany document cancelled"),
                    m_message=_("The source accounting document was cancelled and requires counterpart review."),
                )
