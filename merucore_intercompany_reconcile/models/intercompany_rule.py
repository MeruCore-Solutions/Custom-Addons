from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class MeruCoreIntercompanyRule(models.Model):
    _inherit = "merucore.intercompany.rule"

    m_reconcile_enabled = fields.Boolean(
        string="Reconciliation Enabled",
        default=False,
        tracking=True,
    )
    m_matching_strategy = fields.Selection(
        selection=[
            ("linked_documents", "Linked Documents"),
            ("exact_reference", "Exact Reference"),
            ("amount_currency_date", "Amount / Currency / Date"),
            ("manual_only", "Manual Only"),
        ],
        string="Matching Strategy",
        default="manual_only",
        tracking=True,
    )
    m_match_date_tolerance_days = fields.Integer(
        default=7,
        tracking=True,
    )
    m_match_amount_tolerance = fields.Float(
        digits="Account",
        default=0.0,
        tracking=True,
    )
    m_match_residual_only = fields.Boolean(
        default=True,
        tracking=True,
    )
    m_settlement_strategy = fields.Selection(
        selection=[
            ("record_external_payment", "Record External Payment"),
            ("create_internal_payments", "Create Internal Payments"),
            ("bilateral_clearing", "Bilateral Clearing"),
            ("multilateral_clearing", "Multilateral Clearing"),
        ],
        string="Settlement Strategy",
        default="bilateral_clearing",
        tracking=True,
    )
    m_settlement_currency_strategy = fields.Selection(
        selection=[
            ("company_currency_each_side", "Company Currency On Each Side"),
            ("source_document_currency", "Source Document Currency"),
            ("configured_settlement_currency", "Configured Settlement Currency"),
        ],
        string="Settlement Currency Strategy",
        default="company_currency_each_side",
        tracking=True,
    )
    m_settlement_currency_id = fields.Many2one(
        "res.currency",
        tracking=True,
    )
    m_exchange_rate_date_strategy = fields.Selection(
        selection=[
            ("settlement_date", "Settlement Date"),
            ("invoice_date", "Invoice Date"),
            ("fixed_proposal_date", "Fixed Proposal Date"),
        ],
        string="Rate Date Strategy",
        default="settlement_date",
        tracking=True,
    )
    m_source_clearing_journal_id = fields.Many2one(
        "account.journal",
        string="Source Clearing Journal",
        check_company=False,
        tracking=True,
    )
    m_destination_clearing_journal_id = fields.Many2one(
        "account.journal",
        string="Destination Clearing Journal",
        check_company=False,
        tracking=True,
    )
    m_source_clearing_account_id = fields.Many2one(
        "account.account",
        string="Source Clearing Account",
        check_company=False,
        tracking=True,
    )
    m_destination_clearing_account_id = fields.Many2one(
        "account.account",
        string="Destination Clearing Account",
        check_company=False,
        tracking=True,
    )
    m_source_due_to_account_id = fields.Many2one(
        "account.account",
        string="Source Due To Account",
        check_company=False,
        tracking=True,
    )
    m_source_due_from_account_id = fields.Many2one(
        "account.account",
        string="Source Due From Account",
        check_company=False,
        tracking=True,
    )
    m_destination_due_to_account_id = fields.Many2one(
        "account.account",
        string="Destination Due To Account",
        check_company=False,
        tracking=True,
    )
    m_destination_due_from_account_id = fields.Many2one(
        "account.account",
        string="Destination Due From Account",
        check_company=False,
        tracking=True,
    )
    m_source_payment_journal_id = fields.Many2one(
        "account.journal",
        string="Source Payment Journal",
        check_company=False,
        tracking=True,
    )
    m_destination_payment_journal_id = fields.Many2one(
        "account.journal",
        string="Destination Payment Journal",
        check_company=False,
        tracking=True,
    )
    m_create_payments = fields.Boolean(
        default=False,
        tracking=True,
    )
    m_auto_post_settlement = fields.Boolean(
        default=False,
        tracking=True,
    )
    m_auto_reconcile = fields.Boolean(
        default=False,
        tracking=True,
    )
    m_allow_partial_settlement = fields.Boolean(
        default=True,
        tracking=True,
    )
    m_allow_cross_currency_settlement = fields.Boolean(
        default=False,
        tracking=True,
    )
    m_writeoff_strategy = fields.Selection(
        selection=[
            ("no_writeoff", "No Write-Off"),
            ("configured_account_with_tolerance", "Configured Account With Tolerance"),
        ],
        default="no_writeoff",
        tracking=True,
    )
    m_source_writeoff_account_id = fields.Many2one(
        "account.account",
        string="Source Write-Off Account",
        check_company=False,
        tracking=True,
    )
    m_destination_writeoff_account_id = fields.Many2one(
        "account.account",
        string="Destination Write-Off Account",
        check_company=False,
        tracking=True,
    )
    m_writeoff_tolerance = fields.Float(
        digits="Account",
        default=0.0,
        tracking=True,
    )
    m_require_dual_approval = fields.Boolean(
        default=True,
        tracking=True,
    )
    m_source_approver_ids = fields.Many2many(
        "res.users",
        "m_intercompany_rule_source_approver_rel",
        "m_rule_id",
        "m_user_id",
        string="Source Approvers",
    )
    m_destination_approver_ids = fields.Many2many(
        "res.users",
        "m_intercompany_rule_destination_approver_rel",
        "m_rule_id",
        "m_user_id",
        string="Destination Approvers",
    )
    m_responsible_treasury_user_id = fields.Many2one(
        "res.users",
        string="Treasury Responsible",
        ondelete="set null",
        tracking=True,
    )
    m_reconcile_match_count = fields.Integer(
        compute="m_compute_reconcile_counts",
    )
    m_reconcile_settlement_count = fields.Integer(
        compute="m_compute_reconcile_counts",
    )

    @api.depends("m_name")
    def m_compute_reconcile_counts(self):
        matches = self.env["merucore.intercompany.match"]._read_group(
            [("m_rule_id", "in", self.ids)],
            ["m_rule_id"],
            ["__count"],
        )
        settlements = self.env["merucore.intercompany.settlement"]._read_group(
            [("m_rule_id", "in", self.ids)],
            ["m_rule_id"],
            ["__count"],
        )
        match_counts = {rule.id: count for rule, count in matches}
        settlement_counts = {rule.id: count for rule, count in settlements}
        for rule in self:
            rule.m_reconcile_match_count = match_counts.get(rule.id, 0)
            rule.m_reconcile_settlement_count = settlement_counts.get(rule.id, 0)

    @api.constrains(
        "m_reconcile_enabled",
        "m_match_date_tolerance_days",
        "m_match_amount_tolerance",
        "m_writeoff_tolerance",
        "m_settlement_strategy",
        "m_settlement_currency_strategy",
        "m_settlement_currency_id",
        "m_source_clearing_journal_id",
        "m_destination_clearing_journal_id",
        "m_source_clearing_account_id",
        "m_destination_clearing_account_id",
        "m_source_due_to_account_id",
        "m_source_due_from_account_id",
        "m_destination_due_to_account_id",
        "m_destination_due_from_account_id",
        "m_source_payment_journal_id",
        "m_destination_payment_journal_id",
        "m_source_writeoff_account_id",
        "m_destination_writeoff_account_id",
        "m_source_approver_ids",
        "m_destination_approver_ids",
        "m_responsible_treasury_user_id",
        "m_auto_post_settlement",
        "m_auto_reconcile",
        "m_create_payments",
        "m_source_company_id",
        "m_destination_company_id",
    )
    def m_check_reconcile_configuration(self):
        for rule in self.filtered("m_reconcile_enabled"):
            if rule.m_match_date_tolerance_days < 0:
                raise ValidationError(_("The match date tolerance cannot be negative."))
            if rule.m_match_amount_tolerance < 0:
                raise ValidationError(_("The match amount tolerance cannot be negative."))
            if rule.m_writeoff_tolerance < 0:
                raise ValidationError(_("The write-off tolerance cannot be negative."))
            if (
                rule.m_settlement_currency_strategy == "configured_settlement_currency"
                and not rule.m_settlement_currency_id
            ):
                raise ValidationError(
                    _("A configured settlement currency is required for the selected currency strategy.")
                )
            if rule.m_settlement_strategy == "multilateral_clearing":
                raise ValidationError(
                    _("Multilateral clearing is intentionally disabled until group clearing architecture is added to this repository.")
                )
            if rule.m_create_payments and rule.m_settlement_strategy != "create_internal_payments":
                raise ValidationError(
                    _("Enable payment creation only when the settlement strategy is Create Internal Payments.")
                )
            if rule.m_settlement_strategy == "create_internal_payments" and not rule.m_create_payments:
                raise ValidationError(
                    _("Create Internal Payments requires payment creation to be enabled.")
                )
            if rule.m_auto_reconcile and not rule.m_auto_post_settlement:
                raise ValidationError(
                    _("Auto-reconcile requires Auto Post Settlement because draft proposals cannot be reconciled.")
                )

            rule.m_validate_journal_company(
                rule.m_source_clearing_journal_id,
                rule.m_source_company_id,
                _("source clearing journal"),
                {"general"},
            )
            rule.m_validate_journal_company(
                rule.m_destination_clearing_journal_id,
                rule.m_destination_company_id,
                _("destination clearing journal"),
                {"general"},
            )
            rule.m_validate_journal_company(
                rule.m_source_payment_journal_id,
                rule.m_source_company_id,
                _("source payment journal"),
                {"bank", "cash"},
            )
            rule.m_validate_journal_company(
                rule.m_destination_payment_journal_id,
                rule.m_destination_company_id,
                _("destination payment journal"),
                {"bank", "cash"},
            )

            rule.m_validate_account_company(
                rule.m_source_clearing_account_id,
                rule.m_source_company_id,
                _("source clearing account"),
                require_reconcile=True,
            )
            rule.m_validate_account_company(
                rule.m_destination_clearing_account_id,
                rule.m_destination_company_id,
                _("destination clearing account"),
                require_reconcile=True,
            )
            rule.m_validate_account_company(
                rule.m_source_due_to_account_id,
                rule.m_source_company_id,
                _("source due to account"),
                require_reconcile=True,
                forbidden_types={"asset_receivable", "liability_payable"},
            )
            rule.m_validate_account_company(
                rule.m_source_due_from_account_id,
                rule.m_source_company_id,
                _("source due from account"),
                require_reconcile=True,
                forbidden_types={"asset_receivable", "liability_payable"},
            )
            rule.m_validate_account_company(
                rule.m_destination_due_to_account_id,
                rule.m_destination_company_id,
                _("destination due to account"),
                require_reconcile=True,
                forbidden_types={"asset_receivable", "liability_payable"},
            )
            rule.m_validate_account_company(
                rule.m_destination_due_from_account_id,
                rule.m_destination_company_id,
                _("destination due from account"),
                require_reconcile=True,
                forbidden_types={"asset_receivable", "liability_payable"},
            )
            rule.m_validate_account_company(
                rule.m_source_writeoff_account_id,
                rule.m_source_company_id,
                _("source write-off account"),
                forbidden_types={"asset_receivable", "liability_payable"},
            )
            rule.m_validate_account_company(
                rule.m_destination_writeoff_account_id,
                rule.m_destination_company_id,
                _("destination write-off account"),
                forbidden_types={"asset_receivable", "liability_payable"},
            )

            rule.m_validate_approver_set(rule.m_source_approver_ids, rule.m_source_company_id, _("source"))
            rule.m_validate_approver_set(
                rule.m_destination_approver_ids,
                rule.m_destination_company_id,
                _("destination"),
            )
            if (
                rule.m_responsible_treasury_user_id
                and (
                    rule.m_source_company_id not in rule.m_responsible_treasury_user_id.company_ids
                    or rule.m_destination_company_id not in rule.m_responsible_treasury_user_id.company_ids
                )
            ):
                raise ValidationError(
                    _("The treasury responsible user must have access to both companies in the rule.")
                )

    def m_validate_journal_company(self, journal, company, label, allowed_types):
        self.ensure_one()
        if not journal:
            return
        if journal.company_id != company:
            raise ValidationError(
                _("The %(label)s must belong to company %(company)s.", label=label, company=company.display_name)
            )
        if allowed_types and journal.type not in allowed_types:
            raise ValidationError(
                _("The %(label)s must be one of these journal types: %(types)s.", label=label, types=", ".join(sorted(allowed_types)))
            )

    def m_validate_account_company(
        self,
        account,
        company,
        label,
        require_reconcile=False,
        forbidden_types=False,
    ):
        self.ensure_one()
        if not account:
            return
        if company not in account.company_ids:
            raise ValidationError(
                _("The %(label)s must belong to company %(company)s.", label=label, company=company.display_name)
            )
        if require_reconcile and not account.reconcile:
            raise ValidationError(_("The %(label)s must be reconcilable.", label=label))
        if forbidden_types and account.account_type in forbidden_types:
            raise ValidationError(
                _("The %(label)s cannot use receivable or payable account types.", label=label)
            )

    def m_validate_approver_set(self, users, company, label):
        self.ensure_one()
        for user in users:
            if company not in user.company_ids:
                raise ValidationError(
                    _("Every %(label)s approver must have access to company %(company)s.", label=label, company=company.display_name)
                )
            if not (user.has_group("account.group_account_user") or user.has_group("account.group_account_manager")):
                raise ValidationError(
                    _("Every %(label)s approver must belong to an accounting access group.", label=label)
                )

    def m_get_reconcile_clearing_journal(self, m_side):
        self.ensure_one()
        company = self.m_source_company_id if m_side == "source" else self.m_destination_company_id
        journal = (
            self.m_source_clearing_journal_id
            if m_side == "source"
            else self.m_destination_clearing_journal_id
        )
        return journal or company.m_get_intercompany_general_journal()

    def m_get_reconcile_payment_journal(self, m_side):
        self.ensure_one()
        company = self.m_source_company_id if m_side == "source" else self.m_destination_company_id
        journal = (
            self.m_source_payment_journal_id
            if m_side == "source"
            else self.m_destination_payment_journal_id
        )
        return journal or company.m_get_intercompany_payment_journal()

    def m_get_reconcile_counterpart_account(self, m_side, m_account_type):
        self.ensure_one()
        if m_side == "source":
            clearing_account = self.m_source_clearing_account_id
            due_to_account = self.m_source_due_to_account_id
            due_from_account = self.m_source_due_from_account_id
        else:
            clearing_account = self.m_destination_clearing_account_id
            due_to_account = self.m_destination_due_to_account_id
            due_from_account = self.m_destination_due_from_account_id

        if m_account_type == "asset_receivable":
            return due_from_account or clearing_account
        if m_account_type == "liability_payable":
            return due_to_account or clearing_account
        return clearing_account

    def m_action_open_reconcile_matches(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "merucore_intercompany_reconcile.m_action_intercompany_matches"
        )
        action["domain"] = [("m_rule_id", "=", self.id)]
        action["context"] = {
            "default_m_rule_id": self.id,
            "allowed_company_ids": (self.m_source_company_id | self.m_destination_company_id).ids,
        }
        return action

    def m_action_open_reconcile_settlements(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "merucore_intercompany_reconcile.m_action_intercompany_settlements"
        )
        action["domain"] = [("m_rule_id", "=", self.id)]
        action["context"] = {
            "default_m_rule_id": self.id,
            "allowed_company_ids": (self.m_source_company_id | self.m_destination_company_id).ids,
        }
        return action
