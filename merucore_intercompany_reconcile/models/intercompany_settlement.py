from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.float_utils import float_compare, float_is_zero


class MeruCoreIntercompanySettlement(models.Model):
    _name = "merucore.intercompany.settlement"
    _description = "MeruCore Intercompany Settlement"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    m_name = fields.Char(
        required=True,
        copy=False,
        readonly=True,
        default="/",
        index=True,
        tracking=True,
    )
    m_match_id = fields.Many2one(
        "merucore.intercompany.match",
        required=True,
        index=True,
        ondelete="restrict",
        tracking=True,
    )
    m_rule_id = fields.Many2one(
        "merucore.intercompany.rule",
        required=True,
        index=True,
        ondelete="restrict",
        tracking=True,
    )
    m_transaction_id = fields.Many2one(
        "merucore.intercompany.transaction",
        index=True,
        ondelete="set null",
        check_company=False,
        tracking=True,
    )
    m_source_company_id = fields.Many2one(
        "res.company",
        required=True,
        index=True,
        ondelete="restrict",
        tracking=True,
    )
    m_destination_company_id = fields.Many2one(
        "res.company",
        required=True,
        index=True,
        ondelete="restrict",
        tracking=True,
    )
    m_source_company_currency_id = fields.Many2one(
        "res.currency",
        related="m_source_company_id.currency_id",
        store=True,
        readonly=True,
        string="Source Company Currency",
    )
    m_destination_company_currency_id = fields.Many2one(
        "res.currency",
        related="m_destination_company_id.currency_id",
        store=True,
        readonly=True,
        string="Destination Company Currency",
    )
    m_strategy = fields.Selection(
        selection=[
            ("record_external_payment", "Record External Payment"),
            ("create_internal_payments", "Create Internal Payments"),
            ("bilateral_clearing", "Bilateral Clearing"),
            ("multilateral_clearing", "Multilateral Clearing"),
        ],
        required=True,
        default="bilateral_clearing",
        tracking=True,
    )
    m_state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("awaiting_approval", "Awaiting Approval"),
            ("approved", "Approved"),
            ("posted", "Posted"),
            ("partially_posted", "Partially Posted"),
            ("reversed", "Reversed"),
            ("cancelled", "Cancelled"),
            ("failed", "Failed"),
        ],
        default="draft",
        required=True,
        index=True,
        tracking=True,
    )
    m_proposal_date = fields.Date(
        default=fields.Date.context_today,
        tracking=True,
    )
    m_posting_date = fields.Date(
        default=fields.Date.context_today,
        tracking=True,
    )
    m_reversal_date = fields.Date(
        copy=False,
        tracking=True,
    )
    m_source_amount = fields.Monetary(
        currency_field="m_source_company_currency_id",
        tracking=True,
    )
    m_destination_amount = fields.Monetary(
        currency_field="m_destination_company_currency_id",
        tracking=True,
    )
    m_amount_difference = fields.Float(
        compute="m_compute_amount_health",
        digits="Account",
    )
    m_within_tolerance = fields.Boolean(
        compute="m_compute_amount_health",
    )
    m_line_ids = fields.One2many(
        "merucore.intercompany.settlement.line",
        "m_settlement_id",
        string="Settlement Lines",
    )
    m_line_count = fields.Integer(
        compute="m_compute_line_count",
    )
    m_source_entry_move_id = fields.Many2one(
        "account.move",
        copy=False,
        check_company=False,
        ondelete="set null",
    )
    m_destination_entry_move_id = fields.Many2one(
        "account.move",
        copy=False,
        check_company=False,
        ondelete="set null",
    )
    m_source_reversal_move_id = fields.Many2one(
        "account.move",
        copy=False,
        check_company=False,
        ondelete="set null",
    )
    m_destination_reversal_move_id = fields.Many2one(
        "account.move",
        copy=False,
        check_company=False,
        ondelete="set null",
    )
    m_source_payment_id = fields.Many2one(
        "account.payment",
        copy=False,
        check_company=False,
        ondelete="set null",
    )
    m_destination_payment_id = fields.Many2one(
        "account.payment",
        copy=False,
        check_company=False,
        ondelete="set null",
    )
    m_source_approved_by_id = fields.Many2one(
        "res.users",
        copy=False,
        ondelete="set null",
        tracking=True,
    )
    m_source_approved_at = fields.Datetime(copy=False)
    m_destination_approved_by_id = fields.Many2one(
        "res.users",
        copy=False,
        ondelete="set null",
        tracking=True,
    )
    m_destination_approved_at = fields.Datetime(copy=False)
    m_is_fully_approved = fields.Boolean(
        compute="m_compute_approval_state",
    )
    m_error_message = fields.Text(copy=False)
    m_note = fields.Html()

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault(
                "m_name",
                self.env["ir.sequence"].next_by_code("merucore.intercompany.settlement") or "/",
            )
            match = self.env["merucore.intercompany.match"].browse(vals.get("m_match_id"))
            if match:
                vals.setdefault("m_rule_id", match.m_rule_id.id)
                vals.setdefault("m_transaction_id", match.m_transaction_id.id)
                vals.setdefault("m_source_company_id", match.m_source_company_id.id)
                vals.setdefault("m_destination_company_id", match.m_destination_company_id.id)
                vals.setdefault("m_strategy", match.m_rule_id.m_settlement_strategy)
        return super().create(vals_list)

    @api.depends("m_source_amount", "m_destination_amount", "m_rule_id.m_match_amount_tolerance")
    def m_compute_amount_health(self):
        for settlement in self:
            settlement.m_amount_difference = settlement.m_source_amount - settlement.m_destination_amount
            settlement.m_within_tolerance = (
                abs(settlement.m_amount_difference) <= settlement.m_rule_id.m_match_amount_tolerance
            )

    @api.depends("m_line_ids")
    def m_compute_line_count(self):
        for settlement in self:
            settlement.m_line_count = len(settlement.m_line_ids)

    @api.depends(
        "m_source_approved_by_id",
        "m_destination_approved_by_id",
        "m_rule_id.m_require_dual_approval",
    )
    def m_compute_approval_state(self):
        for settlement in self:
            if settlement.m_rule_id.m_require_dual_approval:
                settlement.m_is_fully_approved = bool(
                    settlement.m_source_approved_by_id and settlement.m_destination_approved_by_id
                )
            else:
                settlement.m_is_fully_approved = bool(
                    settlement.m_source_approved_by_id or settlement.m_destination_approved_by_id
                )

    @api.constrains(
        "m_match_id",
        "m_rule_id",
        "m_source_company_id",
        "m_destination_company_id",
        "m_source_amount",
        "m_destination_amount",
    )
    def m_check_settlement(self):
        for settlement in self:
            if settlement.m_rule_id != settlement.m_match_id.m_rule_id:
                raise ValidationError(_("The settlement rule must match the linked match rule."))
            if settlement.m_source_company_id != settlement.m_match_id.m_source_company_id:
                raise ValidationError(_("The settlement source company must match the linked match source company."))
            if settlement.m_destination_company_id != settlement.m_match_id.m_destination_company_id:
                raise ValidationError(_("The settlement destination company must match the linked match destination company."))
            if settlement.m_source_amount <= 0 or settlement.m_destination_amount <= 0:
                raise ValidationError(_("Settlement amounts must be strictly positive."))

    def m_action_open_form(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "merucore.intercompany.settlement",
            "res_id": self.id,
            "view_mode": "form",
            "target": "current",
            "context": {
                "allowed_company_ids": [self.m_source_company_id.id, self.m_destination_company_id.id],
            },
        }

    def m_action_request_approval(self):
        self.filtered(lambda settlement: settlement.m_state == "draft").write({"m_state": "awaiting_approval"})

    def m_check_approval_access(self, m_side):
        self.ensure_one()
        company = self.m_source_company_id if m_side == "source" else self.m_destination_company_id
        approvers = (
            self.m_rule_id.m_source_approver_ids
            if m_side == "source"
            else self.m_rule_id.m_destination_approver_ids
        )
        if company not in self.env.user.company_ids:
            raise AccessError(_("You do not have access to company %(company)s.", company=company.display_name))
        if approvers and self.env.user not in approvers:
            raise AccessError(_("You are not configured as an approver for this settlement side."))
        if not (
            self.env.user.has_group("account.group_account_user")
            or self.env.user.has_group("account.group_account_manager")
            or self.env.user.has_group("merucore_intercompany_base.m_group_intercompany_manager")
        ):
            raise AccessError(_("Approving a settlement requires accounting or intercompany manager access."))

    def m_action_approve_source(self):
        for settlement in self:
            settlement.m_check_approval_access("source")
            settlement.write(
                {
                    "m_state": "awaiting_approval" if settlement.m_state == "draft" else settlement.m_state,
                    "m_source_approved_by_id": self.env.user.id,
                    "m_source_approved_at": fields.Datetime.now(),
                }
            )
            if settlement.m_is_fully_approved:
                settlement.m_state = "approved"

    def m_action_approve_destination(self):
        for settlement in self:
            settlement.m_check_approval_access("destination")
            settlement.write(
                {
                    "m_state": "awaiting_approval" if settlement.m_state == "draft" else settlement.m_state,
                    "m_destination_approved_by_id": self.env.user.id,
                    "m_destination_approved_at": fields.Datetime.now(),
                }
            )
            if settlement.m_is_fully_approved:
                settlement.m_state = "approved"

    def m_action_cancel(self):
        for settlement in self:
            if settlement.m_state in {"posted", "partially_posted", "reversed"}:
                raise UserError(_("Posted or reversed settlements cannot be cancelled."))
            settlement.write({"m_state": "cancelled"})

    def m_get_lines(self, m_side):
        self.ensure_one()
        return self.m_line_ids.filtered(lambda line: line.m_company_role == m_side)

    def m_validate_ready_to_post(self):
        self.ensure_one()
        if not self.m_rule_id.m_reconcile_enabled:
            raise UserError(_("Reconciliation is not enabled on the selected rule."))
        if self.m_state in {"posted", "reversed", "cancelled"}:
            raise UserError(_("This settlement is already finalized and cannot be posted again."))
        if not self.m_line_ids:
            raise UserError(_("The settlement does not contain any allocation lines."))
        if self.m_rule_id.m_require_dual_approval and not self.m_is_fully_approved:
            raise UserError(_("Dual approval is required before posting this settlement."))
        if (
            not self.m_rule_id.m_require_dual_approval
            and not (
                self.m_source_approved_by_id
                or self.m_destination_approved_by_id
                or self.env.user.has_group("merucore_intercompany_base.m_group_intercompany_manager")
            )
        ):
            raise UserError(_("Approve at least one side before posting the settlement."))

    def m_action_post(self):
        for settlement in self:
            settlement.m_validate_ready_to_post()
            settlement.write({"m_error_message": False})
            source_ok = False
            destination_ok = False
            if settlement.m_strategy == "record_external_payment":
                raise UserError(
                    _("Record External Payment is not posted by this addon because it requires separate accounting evidence.")
                )
            if settlement.m_strategy == "multilateral_clearing":
                raise UserError(_("Multilateral clearing is not enabled in this repository."))

            try:
                with self.env.cr.savepoint():
                    if settlement.m_strategy == "create_internal_payments":
                        settlement.m_post_internal_payment("source")
                    else:
                        settlement.m_post_bilateral_clearing("source")
                    source_ok = True
            except Exception as error:
                settlement.write(
                    {
                        "m_state": "failed",
                        "m_error_message": str(error),
                    }
                )
                if settlement.m_transaction_id:
                    settlement.m_transaction_id.m_mark_failed(
                        m_summary=_("Source-side settlement posting failed"),
                        m_message=str(error),
                    )
                continue

            try:
                with self.env.cr.savepoint():
                    if settlement.m_strategy == "create_internal_payments":
                        settlement.m_post_internal_payment("destination")
                    else:
                        settlement.m_post_bilateral_clearing("destination")
                    destination_ok = True
            except Exception as error:
                settlement.write(
                    {
                        "m_state": "partially_posted" if source_ok else "failed",
                        "m_error_message": str(error),
                    }
                )
                if settlement.m_transaction_id:
                    settlement.m_transaction_id.m_mark_warning(
                        m_summary=_("Settlement is only partially posted"),
                        m_message=str(error),
                    )
                continue

            if source_ok and destination_ok:
                settlement.write(
                    {
                        "m_state": "posted",
                        "m_error_message": False,
                    }
                )
                if settlement.m_transaction_id:
                    settlement.m_transaction_id.m_mark_healthy(
                        m_summary=_("Settlement posted"),
                        m_message=_("Settlement %(settlement)s posted successfully.", settlement=settlement.m_name),
                    )
                settlement.message_post(
                    body=_("Settlement %(settlement)s has been posted.", settlement=settlement.m_name),
                    message_type="comment",
                    subtype_xmlid="mail.mt_note",
                )
        return True

    def m_get_payment_method_line(self, m_journal, m_payment_type):
        method_lines = (
            m_journal.inbound_payment_method_line_ids
            if m_payment_type == "inbound"
            else m_journal.outbound_payment_method_line_ids
        )
        if not method_lines:
            raise ValidationError(
                _("Journal %(journal)s does not provide a payment method for %(type)s payments.", journal=m_journal.display_name, type=m_payment_type)
            )
        return method_lines[:1]

    def m_post_internal_payment(self, m_side):
        self.ensure_one()
        company = self.m_source_company_id if m_side == "source" else self.m_destination_company_id
        line_ids = self.m_get_lines(m_side)
        account_types = set(line_ids.mapped("m_move_line_id.account_type"))
        if len(account_types) != 1:
            raise ValidationError(_("Internal payment settlements require one account type per company side."))
        account_type = account_types.pop()
        journal = self.m_rule_id.m_get_reconcile_payment_journal(m_side)
        total_amount = sum(line_ids.mapped("m_allocated_amount"))
        payment_type = "inbound" if account_type == "asset_receivable" else "outbound"
        partner_type = "customer" if account_type == "asset_receivable" else "supplier"
        partner = line_ids[:1].m_partner_id
        payment = (
            self.env["account.payment"]
            .with_company(company)
            .with_context(allowed_company_ids=[company.id])
            .create(
                {
                    "journal_id": journal.id,
                    "payment_method_line_id": self.m_get_payment_method_line(journal, payment_type).id,
                    "payment_type": payment_type,
                    "partner_type": partner_type,
                    "partner_id": partner.id,
                    "company_id": company.id,
                    "currency_id": company.currency_id.id,
                    "amount": total_amount,
                    "date": self.m_posting_date,
                    "memo": self.m_name,
                    "m_intercompany_settlement_id": self.id,
                }
            )
        )
        payment.action_post()
        original_lines = line_ids.mapped("m_move_line_id")
        payment_lines = payment.move_id.line_ids.filtered(
            lambda line: line.account_id == original_lines[:1].account_id and not line.reconciled
        )
        (payment_lines + original_lines).reconcile()
        if m_side == "source":
            self.m_source_payment_id = payment
        else:
            self.m_destination_payment_id = payment

    def m_post_bilateral_clearing(self, m_side):
        self.ensure_one()
        company = self.m_source_company_id if m_side == "source" else self.m_destination_company_id
        other_company = self.m_destination_company_id if m_side == "source" else self.m_source_company_id
        line_ids = self.m_get_lines(m_side)
        journal = self.m_rule_id.m_get_reconcile_clearing_journal(m_side)
        move_line_commands = []
        balance_totals = {"asset_receivable": 0.0, "liability_payable": 0.0}

        for index, settlement_line in enumerate(line_ids, start=1):
            original_line = settlement_line.m_move_line_id
            amount = settlement_line.m_allocated_amount
            if original_line.account_type == "asset_receivable":
                debit, credit = 0.0, amount
            elif original_line.account_type == "liability_payable":
                debit, credit = amount, 0.0
            else:
                raise ValidationError(_("Only receivable and payable lines can be cleared."))
            balance_totals[original_line.account_type] += amount
            move_line_commands.append(
                fields.Command.create(
                    {
                        "sequence": index * 10,
                        "name": f"{self.m_name} - {original_line.move_name}",
                        "partner_id": original_line.partner_id.id,
                        "account_id": original_line.account_id.id,
                        "debit": debit,
                        "credit": credit,
                    }
                )
            )

        sequence = 10000
        for account_type, total in balance_totals.items():
            if float_is_zero(total, precision_rounding=company.currency_id.rounding):
                continue
            counterpart_account = self.m_rule_id.m_get_reconcile_counterpart_account(m_side, account_type)
            if not counterpart_account:
                raise ValidationError(
                    _("No counterpart account is configured on the rule for %(side)s %(type)s settlements.", side=m_side, type=account_type)
                )
            if account_type == "asset_receivable":
                debit, credit = total, 0.0
            else:
                debit, credit = 0.0, total
            move_line_commands.append(
                fields.Command.create(
                    {
                        "sequence": sequence,
                        "name": f"{self.m_name} - Intercompany Counterpart",
                        "partner_id": other_company.partner_id.id,
                        "account_id": counterpart_account.id,
                        "debit": debit,
                        "credit": credit,
                    }
                )
            )
            sequence += 10

        move = (
            self.env["account.move"]
            .with_company(company)
            .with_context(allowed_company_ids=[company.id], default_move_type="entry")
            .create(
                {
                    "company_id": company.id,
                    "journal_id": journal.id,
                    "date": self.m_posting_date,
                    "ref": self.m_name,
                    "line_ids": move_line_commands,
                }
            )
        )
        move.action_post()

        for index, settlement_line in enumerate(line_ids, start=1):
            counterpart_line = move.line_ids.filtered(lambda line: line.sequence == index * 10)[:1]
            settlement_line.m_posting_move_line_id = counterpart_line
            (settlement_line.m_move_line_id + counterpart_line).reconcile()

        if m_side == "source":
            self.m_source_entry_move_id = move
        else:
            self.m_destination_entry_move_id = move

    def m_action_reverse(self):
        for settlement in self:
            if settlement.m_state not in {"posted", "partially_posted"}:
                raise UserError(_("Only posted or partially posted settlements can be reversed."))
            if settlement.m_source_payment_id or settlement.m_destination_payment_id:
                raise UserError(_("Payment-based settlements are not reversible by this addon yet."))
            settlement.m_reverse_company_move("source")
            settlement.m_reverse_company_move("destination")
            settlement.write(
                {
                    "m_state": "reversed",
                    "m_reversal_date": fields.Date.context_today(self),
                }
            )
            if settlement.m_transaction_id:
                settlement.m_transaction_id.m_log_event(
                    m_event_type="info",
                    m_summary=_("Settlement reversed"),
                    m_message=_("Settlement %(settlement)s has been reversed.", settlement=settlement.m_name),
                )

    def m_reverse_company_move(self, m_side):
        self.ensure_one()
        move = self.m_source_entry_move_id if m_side == "source" else self.m_destination_entry_move_id
        if not move:
            return False
        company = self.m_source_company_id if m_side == "source" else self.m_destination_company_id
        settlement_lines = self.m_get_lines(m_side)
        posted_lines = settlement_lines.mapped("m_posting_move_line_id").filtered("reconciled")
        if posted_lines:
            posted_lines.remove_move_reconcile()
        reversal = (
            move.with_company(company)
            .with_context(allowed_company_ids=[company.id])
            ._reverse_moves(
                default_values_list=[
                    {
                        "ref": _("Reversal of %(move)s", move=move.name),
                        "date": self.m_reversal_date or fields.Date.context_today(self),
                    }
                ],
                cancel=False,
            )
        )
        reversal.action_post()
        for account in move.line_ids.filtered(lambda line: line.account_id.reconcile).mapped("account_id"):
            lines_to_reconcile = (move.line_ids + reversal.line_ids).filtered(
                lambda line: line.account_id == account and not line.reconciled
            )
            if len(lines_to_reconcile) >= 2:
                lines_to_reconcile.reconcile()
        if m_side == "source":
            self.m_source_reversal_move_id = reversal
        else:
            self.m_destination_reversal_move_id = reversal
        return reversal
