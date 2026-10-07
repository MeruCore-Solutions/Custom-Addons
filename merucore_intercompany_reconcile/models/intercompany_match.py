from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare, float_is_zero


class MeruCoreIntercompanyMatch(models.Model):
    _name = "merucore.intercompany.match"
    _description = "MeruCore Intercompany Match"
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
    m_active = fields.Boolean(default=True)
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
    m_source_move_id = fields.Many2one(
        "account.move",
        required=True,
        index=True,
        ondelete="restrict",
        check_company=False,
        tracking=True,
    )
    m_destination_move_id = fields.Many2one(
        "account.move",
        required=True,
        index=True,
        ondelete="restrict",
        check_company=False,
        tracking=True,
    )
    m_source_move_line_ids = fields.Many2many(
        "account.move.line",
        "m_intercompany_match_source_line_rel",
        "m_match_id",
        "m_move_line_id",
        string="Source Lines",
        check_company=False,
    )
    m_destination_move_line_ids = fields.Many2many(
        "account.move.line",
        "m_intercompany_match_destination_line_rel",
        "m_match_id",
        "m_move_line_id",
        string="Destination Lines",
        check_company=False,
    )
    m_source_partner_id = fields.Many2one(
        "res.partner",
        related="m_source_move_id.partner_id",
        store=True,
        readonly=True,
        string="Source Partner",
    )
    m_destination_partner_id = fields.Many2one(
        "res.partner",
        related="m_destination_move_id.partner_id",
        store=True,
        readonly=True,
        string="Destination Partner",
    )
    m_source_currency_id = fields.Many2one(
        "res.currency",
        related="m_source_move_id.currency_id",
        store=True,
        readonly=True,
        string="Source Document Currency",
    )
    m_destination_currency_id = fields.Many2one(
        "res.currency",
        related="m_destination_move_id.currency_id",
        store=True,
        readonly=True,
        string="Destination Document Currency",
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
    m_source_date = fields.Date(
        related="m_source_move_id.invoice_date",
        store=True,
        readonly=True,
        string="Source Invoice/Bill Date",
    )
    m_destination_date = fields.Date(
        related="m_destination_move_id.invoice_date",
        store=True,
        readonly=True,
        string="Destination Invoice/Bill Date",
    )
    m_source_reference = fields.Char(
        related="m_source_move_id.ref",
        store=True,
        readonly=True,
        string="Source Reference",
    )
    m_destination_reference = fields.Char(
        related="m_destination_move_id.ref",
        store=True,
        readonly=True,
        string="Destination Reference",
    )
    m_source_residual_amount = fields.Monetary(
        compute="m_compute_match_metrics",
        currency_field="m_source_company_currency_id",
        string="Source Residual",
    )
    m_destination_residual_amount = fields.Monetary(
        compute="m_compute_match_metrics",
        currency_field="m_destination_company_currency_id",
        string="Destination Residual",
    )
    m_difference_amount = fields.Float(
        compute="m_compute_match_metrics",
        digits="Account",
    )
    m_is_date_within_tolerance = fields.Boolean(
        compute="m_compute_match_metrics",
    )
    m_is_amount_within_tolerance = fields.Boolean(
        compute="m_compute_match_metrics",
    )
    m_is_cross_currency = fields.Boolean(
        compute="m_compute_match_metrics",
    )
    m_match_basis = fields.Char(
        compute="m_compute_match_metrics",
    )
    m_state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("proposed", "Proposed"),
            ("settled", "Settled"),
            ("mismatch", "Mismatch"),
            ("cancelled", "Cancelled"),
        ],
        compute="m_compute_state",
        store=True,
        tracking=True,
    )
    m_settlement_ids = fields.One2many(
        "merucore.intercompany.settlement",
        "m_match_id",
        string="Settlements",
    )
    m_settlement_count = fields.Integer(
        compute="m_compute_settlement_count",
    )
    m_note = fields.Html()

    def init(self):
        self.env.cr.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
                merucore_intercompany_match_move_pair_uniq
            ON merucore_intercompany_match (m_rule_id, m_source_move_id, m_destination_move_id)
            WHERE COALESCE(m_active, TRUE)
            """
        )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault("m_name", self.env["ir.sequence"].next_by_code("merucore.intercompany.match") or "/")
            rule = self.env["merucore.intercompany.rule"].browse(vals.get("m_rule_id"))
            if rule:
                vals.setdefault("m_source_company_id", rule.m_source_company_id.id)
                vals.setdefault("m_destination_company_id", rule.m_destination_company_id.id)
            source_move = self.env["account.move"].browse(vals.get("m_source_move_id"))
            destination_move = self.env["account.move"].browse(vals.get("m_destination_move_id"))
            if source_move and "m_source_move_line_ids" not in vals:
                vals["m_source_move_line_ids"] = [fields.Command.set(self.m_get_open_move_lines(source_move).ids)]
            if destination_move and "m_destination_move_line_ids" not in vals:
                vals["m_destination_move_line_ids"] = [
                    fields.Command.set(self.m_get_open_move_lines(destination_move).ids)
                ]
        return super().create(vals_list)

    @api.depends(
        "m_source_move_line_ids.amount_residual",
        "m_source_move_line_ids.reconciled",
        "m_destination_move_line_ids.amount_residual",
        "m_destination_move_line_ids.reconciled",
        "m_source_date",
        "m_destination_date",
        "m_source_reference",
        "m_destination_reference",
        "m_source_currency_id",
        "m_destination_currency_id",
        "m_rule_id.m_match_amount_tolerance",
        "m_rule_id.m_match_date_tolerance_days",
        "m_rule_id.m_matching_strategy",
    )
    def m_compute_match_metrics(self):
        for match in self:
            source_lines = match.m_get_source_lines()
            destination_lines = match.m_get_destination_lines()
            match.m_source_residual_amount = sum(abs(line.amount_residual) for line in source_lines)
            match.m_destination_residual_amount = sum(abs(line.amount_residual) for line in destination_lines)
            currency_diff = (
                match.m_source_company_currency_id != match.m_destination_company_currency_id
                or match.m_source_currency_id != match.m_destination_currency_id
            )
            match.m_is_cross_currency = bool(currency_diff)
            match.m_difference_amount = match.m_source_residual_amount - match.m_destination_residual_amount
            match.m_is_amount_within_tolerance = (
                abs(match.m_difference_amount) <= match.m_rule_id.m_match_amount_tolerance
            )
            if match.m_source_date and match.m_destination_date:
                match.m_is_date_within_tolerance = (
                    abs((match.m_source_date - match.m_destination_date).days)
                    <= match.m_rule_id.m_match_date_tolerance_days
                )
            else:
                match.m_is_date_within_tolerance = True
            if (
                match.m_rule_id.m_matching_strategy == "exact_reference"
                and match.m_source_reference
                and match.m_source_reference == match.m_destination_reference
            ):
                match.m_match_basis = "exact_reference"
            elif match.m_rule_id.m_matching_strategy == "linked_documents":
                match.m_match_basis = "linked_documents"
            elif match.m_is_amount_within_tolerance and match.m_is_date_within_tolerance:
                match.m_match_basis = "amount_currency_date"
            else:
                match.m_match_basis = "manual_only"

    @api.depends(
        "m_active",
        "m_is_amount_within_tolerance",
        "m_is_date_within_tolerance",
        "m_settlement_ids.m_state",
    )
    def m_compute_state(self):
        for match in self:
            if not match.m_active:
                match.m_state = "cancelled"
            elif match.m_settlement_ids.filtered(
                lambda settlement: settlement.m_state in {"posted", "partially_posted"}
            ):
                match.m_state = "settled"
            elif match.m_settlement_ids.filtered(
                lambda settlement: settlement.m_state in {"draft", "awaiting_approval", "approved"}
            ):
                match.m_state = "proposed"
            elif not match.m_is_amount_within_tolerance or not match.m_is_date_within_tolerance:
                match.m_state = "mismatch"
            else:
                match.m_state = "draft"

    def m_compute_settlement_count(self):
        grouped = self.env["merucore.intercompany.settlement"]._read_group(
            [("m_match_id", "in", self.ids)],
            ["m_match_id"],
            ["__count"],
        )
        counts = {match.id: count for match, count in grouped}
        for match in self:
            match.m_settlement_count = counts.get(match.id, 0)

    @api.constrains(
        "m_rule_id",
        "m_source_company_id",
        "m_destination_company_id",
        "m_source_move_id",
        "m_destination_move_id",
        "m_source_move_line_ids",
        "m_destination_move_line_ids",
    )
    def m_check_match_records(self):
        valid_move_types = {"out_invoice", "out_refund", "in_invoice", "in_refund"}
        for match in self:
            if match.m_source_company_id != match.m_rule_id.m_source_company_id:
                raise ValidationError(_("The source company must match the rule source company."))
            if match.m_destination_company_id != match.m_rule_id.m_destination_company_id:
                raise ValidationError(_("The destination company must match the rule destination company."))
            if match.m_source_move_id.company_id != match.m_source_company_id:
                raise ValidationError(_("The source move must belong to the source company."))
            if match.m_destination_move_id.company_id != match.m_destination_company_id:
                raise ValidationError(_("The destination move must belong to the destination company."))
            if match.m_source_move_id.state != "posted" or match.m_destination_move_id.state != "posted":
                raise ValidationError(_("Only posted accounting moves can be matched."))
            if match.m_source_move_id.move_type not in valid_move_types:
                raise ValidationError(_("The source move must be an invoice, bill, credit note, or refund."))
            if match.m_destination_move_id.move_type not in valid_move_types:
                raise ValidationError(_("The destination move must be an invoice, bill, credit note, or refund."))
            if not match.m_source_move_line_ids or not match.m_destination_move_line_ids:
                raise ValidationError(_("Both sides of a match require at least one open receivable or payable line."))
            for line in match.m_source_move_line_ids:
                if line.move_id != match.m_source_move_id:
                    raise ValidationError(_("Every source line must belong to the selected source move."))
            for line in match.m_destination_move_line_ids:
                if line.move_id != match.m_destination_move_id:
                    raise ValidationError(_("Every destination line must belong to the selected destination move."))

    @api.model
    def m_get_open_move_lines(self, m_move):
        return m_move.line_ids.filtered(
            lambda line: line.parent_state == "posted"
            and line.account_type in {"asset_receivable", "liability_payable"}
            and (not line.reconciled or not float_is_zero(line.amount_residual, precision_rounding=line.company_currency_id.rounding))
        )

    def m_get_source_lines(self):
        self.ensure_one()
        return self.m_source_move_line_ids or self.m_get_open_move_lines(self.m_source_move_id)

    def m_get_destination_lines(self):
        self.ensure_one()
        return self.m_destination_move_line_ids or self.m_get_open_move_lines(self.m_destination_move_id)

    def m_action_refresh_lines(self):
        for match in self:
            match.write(
                {
                    "m_source_move_line_ids": [fields.Command.set(match.m_get_open_move_lines(match.m_source_move_id).ids)],
                    "m_destination_move_line_ids": [
                        fields.Command.set(match.m_get_open_move_lines(match.m_destination_move_id).ids)
                    ],
                }
            )

    def m_action_open_source_move(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "res_id": self.m_source_move_id.id,
            "view_mode": "form",
            "target": "current",
            "context": {"allowed_company_ids": [self.m_source_company_id.id]},
        }

    def m_action_open_destination_move(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "res_id": self.m_destination_move_id.id,
            "view_mode": "form",
            "target": "current",
            "context": {"allowed_company_ids": [self.m_destination_company_id.id]},
        }

    def m_action_open_settlements(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "merucore_intercompany_reconcile.m_action_intercompany_settlements"
        )
        action["domain"] = [("m_match_id", "=", self.id)]
        action["context"] = {
            "default_m_match_id": self.id,
            "default_m_rule_id": self.m_rule_id.id,
            "allowed_company_ids": [self.m_source_company_id.id, self.m_destination_company_id.id],
        }
        return action

    def m_action_cancel(self):
        self.write({"m_active": False})

    def m_action_restore(self):
        self.write({"m_active": True})

    def m_prepare_settlement_allocation_commands(self, m_company_role, m_amount):
        self.ensure_one()
        line_ids = self.m_get_source_lines() if m_company_role == "source" else self.m_get_destination_lines()
        company = self.m_source_company_id if m_company_role == "source" else self.m_destination_company_id
        remaining = m_amount
        commands = []
        for line in line_ids:
            open_amount = abs(line.amount_residual)
            if float_is_zero(open_amount, precision_rounding=company.currency_id.rounding):
                continue
            allocated = min(open_amount, remaining)
            if float_is_zero(allocated, precision_rounding=company.currency_id.rounding):
                continue
            commands.append(
                fields.Command.create(
                    {
                        "m_company_role": m_company_role,
                        "m_company_id": company.id,
                        "m_move_line_id": line.id,
                        "m_allocated_amount": allocated,
                    }
                )
            )
            remaining -= allocated
            if float_is_zero(remaining, precision_rounding=company.currency_id.rounding):
                break
        return commands

    def m_get_proposal_amounts(self):
        self.ensure_one()
        source_amount = self.m_source_residual_amount
        destination_amount = self.m_destination_residual_amount
        if not self.m_rule_id.m_allow_cross_currency_settlement:
            if self.m_source_company_currency_id != self.m_destination_company_currency_id:
                raise UserError(
                    _("The two companies use different company currencies. Enable cross-currency settlement first.")
                )
            if self.m_source_currency_id != self.m_destination_currency_id:
                raise UserError(
                    _("The source and destination documents use different document currencies. Enable cross-currency settlement first.")
                )
        difference = abs(source_amount - destination_amount)
        if (
            not self.m_rule_id.m_allow_partial_settlement
            and difference > self.m_rule_id.m_match_amount_tolerance
        ):
            raise UserError(
                _("Partial settlement is disabled and the residual difference is larger than the allowed tolerance.")
            )
        proposed_amount = min(source_amount, destination_amount)
        if float_is_zero(
            proposed_amount,
            precision_rounding=self.m_source_company_currency_id.rounding,
        ):
            raise UserError(_("There is no residual balance left to settle."))
        return source_amount, destination_amount, proposed_amount

    def m_action_create_settlement(self):
        settlements = self.env["merucore.intercompany.settlement"]
        for match in self:
            if not match.m_rule_id.m_reconcile_enabled:
                raise UserError(_("Reconciliation is not enabled on the selected company-pair rule."))
            source_amount, destination_amount, proposed_amount = match.m_get_proposal_amounts()
            settlement = self.env["merucore.intercompany.settlement"].create(
                {
                    "m_match_id": match.id,
                    "m_rule_id": match.m_rule_id.id,
                    "m_transaction_id": match.m_transaction_id.id,
                    "m_source_company_id": match.m_source_company_id.id,
                    "m_destination_company_id": match.m_destination_company_id.id,
                    "m_strategy": match.m_rule_id.m_settlement_strategy,
                    "m_source_amount": min(source_amount, proposed_amount),
                    "m_destination_amount": min(destination_amount, proposed_amount),
                    "m_line_ids": match.m_prepare_settlement_allocation_commands("source", proposed_amount)
                    + match.m_prepare_settlement_allocation_commands("destination", proposed_amount),
                }
            )
            match.message_post(
                body=_("Settlement proposal %(settlement)s was created.", settlement=settlement.m_name),
                message_type="comment",
                subtype_xmlid="mail.mt_note",
            )
            if match.m_transaction_id:
                match.m_transaction_id.m_log_event(
                    m_event_type="info",
                    m_summary=_("Settlement proposal created"),
                    m_message=_("Settlement %(settlement)s was created from match %(match)s.", settlement=settlement.m_name, match=match.m_name),
                )
            settlements |= settlement
            if match.m_rule_id.m_auto_post_settlement:
                settlement.m_action_post()
        return settlements and settlements[0].m_action_open_form() or False
