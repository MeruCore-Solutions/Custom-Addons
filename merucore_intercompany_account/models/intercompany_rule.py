from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class MeruCoreIntercompanyRule(models.Model):
    _inherit = "merucore.intercompany.rule"

    m_account_sync_enabled = fields.Boolean(
        string="Invoice & Bill Synchronization",
        default=False,
        tracking=True,
    )
    m_account_workflow = fields.Selection(
        selection=[
            ("linked_sale_purchase", "Linked Sales / Purchase"),
            ("manual_documents", "Manual Documents"),
            ("both", "Both"),
        ],
        string="Accounting Workflow",
        default="manual_documents",
        tracking=True,
    )
    m_trigger_document = fields.Selection(
        selection=[
            ("customer_invoice", "Customer Invoice / Credit Note"),
            ("vendor_bill", "Vendor Bill / Refund"),
            ("both", "Both"),
        ],
        string="Trigger Document",
        default="both",
        tracking=True,
    )
    m_counterpart_creation_timing = fields.Selection(
        selection=[
            ("manual", "Manual"),
            ("on_draft_creation", "On Draft Creation"),
            ("on_source_post", "On Source Post"),
        ],
        string="Counterpart Creation Timing",
        default="manual",
        tracking=True,
    )
    m_counterpart_document_state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("posted", "Posted"),
        ],
        string="Counterpart Document State",
        default="draft",
        tracking=True,
    )
    m_sync_direction = fields.Selection(
        selection=[
            ("source_to_destination", "Source to Destination"),
            ("destination_to_source", "Destination to Source"),
            ("bidirectional", "Bidirectional"),
        ],
        string="Synchronization Direction",
        default="source_to_destination",
        tracking=True,
    )
    m_sync_draft_headers = fields.Boolean(default=True)
    m_sync_draft_lines = fields.Boolean(default=True)
    m_sync_quantities = fields.Boolean(default=True)
    m_sync_unit_prices = fields.Boolean(default=True)
    m_sync_discounts = fields.Boolean(default=False)
    m_sync_dates = fields.Boolean(default=True)
    m_sync_payment_terms = fields.Boolean(default=True)
    m_sync_analytic_distribution = fields.Boolean(default=False)
    m_sync_line_labels = fields.Boolean(default=True)
    m_allow_line_creation = fields.Boolean(default=True)
    m_allow_line_deletion = fields.Boolean(default=False)
    m_allow_posted_counterpart_changes = fields.Boolean(default=False)
    m_auto_post_counterpart = fields.Boolean(default=False)
    m_posting_failure_policy = fields.Selection(
        selection=[
            ("block_source_post", "Block Source Posting"),
            ("post_source_and_flag_counterpart", "Post Source and Flag Counterpart"),
        ],
        string="Posting Failure Policy",
        default="block_source_post",
        tracking=True,
    )
    m_refund_strategy = fields.Selection(
        selection=[
            ("create_draft_counterpart_refund", "Create Draft Counterpart Refund"),
            ("auto_post_counterpart_refund", "Auto-Post Counterpart Refund"),
            ("manual_review", "Manual Review"),
        ],
        string="Refund Strategy",
        default="create_draft_counterpart_refund",
        tracking=True,
    )
    m_reversal_date_strategy = fields.Selection(
        selection=[
            ("source_date", "Source Date"),
            ("current_date", "Current Date"),
            ("destination_accounting_date", "Destination Accounting Date"),
        ],
        string="Reversal Date Strategy",
        default="source_date",
        tracking=True,
    )
    m_cancel_counterpart_draft = fields.Boolean(default=False)
    m_currency_strategy = fields.Selection(
        selection=[
            ("destination_company_currency", "Destination Company Currency"),
            ("source_document_currency", "Source Document Currency"),
            ("destination_journal_currency", "Destination Journal Currency"),
        ],
        string="Currency Strategy",
        default="destination_company_currency",
        tracking=True,
    )
    m_exchange_rate_date_strategy = fields.Selection(
        selection=[
            ("source_invoice_date", "Source Invoice Date"),
            ("source_accounting_date", "Source Accounting Date"),
            ("destination_invoice_date", "Destination Invoice Date"),
            ("current_date", "Current Date"),
        ],
        string="Exchange Rate Date Strategy",
        default="source_invoice_date",
        tracking=True,
    )
    m_price_strategy = fields.Selection(
        selection=[
            ("source_document", "Source Document"),
            ("linked_order", "Linked Order"),
            ("destination_product_price", "Destination Product Price"),
        ],
        string="Price Strategy",
        default="source_document",
        tracking=True,
    )
    m_tax_strategy = fields.Selection(
        selection=[
            ("explicit_mapping", "Explicit Mapping"),
            ("destination_fiscal_position", "Destination Fiscal Position"),
            ("destination_product_taxes", "Destination Product Taxes"),
            ("no_taxes", "No Taxes"),
        ],
        string="Tax Strategy",
        default="destination_fiscal_position",
        tracking=True,
    )
    m_account_strategy = fields.Selection(
        selection=[
            ("explicit_mapping", "Explicit Mapping"),
            ("destination_product_accounts", "Destination Product Accounts"),
            ("destination_fiscal_position", "Destination Fiscal Position"),
        ],
        string="Account Strategy",
        default="destination_product_accounts",
        tracking=True,
    )
    m_journal_strategy = fields.Selection(
        selection=[
            ("configured_journal", "Configured Journal"),
            ("destination_default", "Destination Default"),
        ],
        string="Journal Strategy",
        default="destination_default",
        tracking=True,
    )
    m_source_sale_journal_id = fields.Many2one(
        "account.journal",
        string="Source Sale Journal",
        tracking=True,
        check_company=False,
    )
    m_source_purchase_journal_id = fields.Many2one(
        "account.journal",
        string="Source Purchase Journal",
        tracking=True,
        check_company=False,
    )
    m_destination_sale_journal_id = fields.Many2one(
        "account.journal",
        string="Destination Sale Journal",
        tracking=True,
        check_company=False,
    )
    m_destination_purchase_journal_id = fields.Many2one(
        "account.journal",
        string="Destination Purchase Journal",
        tracking=True,
        check_company=False,
    )
    m_partner_validation = fields.Boolean(default=True)
    m_three_way_matching_enabled = fields.Boolean(default=False)
    m_quantity_tolerance = fields.Float(default=0.0)
    m_amount_tolerance = fields.Float(default=0.0)
    m_tax_tolerance = fields.Float(default=0.0)
    m_conflict_policy = fields.Selection(
        selection=[
            ("block_and_review", "Block and Review"),
            ("source_wins_for_draft", "Source Wins For Draft"),
            ("destination_wins_for_draft", "Destination Wins For Draft"),
        ],
        string="Conflict Policy",
        default="block_and_review",
        tracking=True,
    )
    m_responsible_account_user_id = fields.Many2one(
        "res.users",
        string="Accounting Responsible",
        ondelete="set null",
        tracking=True,
    )
    m_account_mapping_ids = fields.One2many(
        "merucore.intercompany.account.mapping",
        "m_rule_id",
        string="Account Mappings",
    )
    m_tax_mapping_ids = fields.One2many(
        "merucore.intercompany.tax.mapping",
        "m_rule_id",
        string="Tax Mappings",
    )
    m_analytic_mapping_ids = fields.One2many(
        "merucore.intercompany.analytic.mapping",
        "m_rule_id",
        string="Analytic Mappings",
    )

    @api.constrains(
        "m_account_sync_enabled",
        "m_source_sale_journal_id",
        "m_source_purchase_journal_id",
        "m_destination_sale_journal_id",
        "m_destination_purchase_journal_id",
        "m_quantity_tolerance",
        "m_amount_tolerance",
        "m_tax_tolerance",
        "m_auto_post_counterpart",
        "m_counterpart_document_state",
        "m_allow_posted_counterpart_changes",
        "m_responsible_account_user_id",
        "m_source_company_id",
        "m_destination_company_id",
    )
    def m_check_account_configuration(self):
        journal_specs = (
            ("m_source_sale_journal_id", "sale", "m_source_company_id"),
            ("m_source_purchase_journal_id", "purchase", "m_source_company_id"),
            ("m_destination_sale_journal_id", "sale", "m_destination_company_id"),
            ("m_destination_purchase_journal_id", "purchase", "m_destination_company_id"),
        )
        for rule in self.filtered("m_account_sync_enabled"):
            for tolerance in (rule.m_quantity_tolerance, rule.m_amount_tolerance, rule.m_tax_tolerance):
                if tolerance < 0.0:
                    raise ValidationError(_("Invoice and bill tolerances cannot be negative."))
            if rule.m_allow_posted_counterpart_changes:
                raise ValidationError(
                    _("Posted counterpart changes cannot be enabled as unrestricted direct writes.")
                )
            if (
                rule.m_counterpart_document_state == "posted"
                or rule.m_auto_post_counterpart
                or rule.m_refund_strategy == "auto_post_counterpart_refund"
            ):
                responsible_user = rule.m_get_account_responsible_user()
                if not responsible_user:
                    raise ValidationError(
                        _("An accounting responsible user is required when counterpart posting automation is enabled.")
                    )
            for field_name, expected_type, company_field_name in journal_specs:
                journal = rule[field_name]
                company = rule[company_field_name]
                if not journal:
                    continue
                if journal.company_id and company and journal.company_id != company:
                    raise ValidationError(
                        _("The selected journal %(journal)s does not belong to %(company)s.",
                          journal=journal.display_name,
                          company=company.display_name)
                    )
                if journal.type != expected_type:
                    raise ValidationError(
                        _("The journal %(journal)s must be of type %(journal_type)s.",
                          journal=journal.display_name,
                          journal_type=expected_type)
                    )
            responsible_user = rule.m_responsible_account_user_id
            if responsible_user:
                allowed_companies = responsible_user.company_ids
                if (
                    rule.m_source_company_id not in allowed_companies
                    or rule.m_destination_company_id not in allowed_companies
                ):
                    raise ValidationError(
                        _("The accounting responsible user must have access to both companies in the company pair.")
                    )

    def m_get_account_responsible_user(self):
        self.ensure_one()
        return self.m_responsible_account_user_id or self.m_responsible_user_id

    def m_allows_account_trigger(self, m_move):
        self.ensure_one()
        if not self.m_account_sync_enabled:
            return False
        if not m_move.is_invoice(include_receipts=False):
            return False
        if m_move.move_type not in {"out_invoice", "in_invoice", "out_refund", "in_refund"}:
            return False
        if m_move.company_id == self.m_source_company_id:
            if self.m_sync_direction not in {"source_to_destination", "bidirectional"}:
                return False
        elif m_move.company_id == self.m_destination_company_id:
            if self.m_sync_direction not in {"destination_to_source", "bidirectional"}:
                return False
        else:
            return False
        trigger_type = "customer_invoice" if m_move.move_type.startswith("out_") else "vendor_bill"
        return self.m_trigger_document in {trigger_type, "both"}

    def m_get_account_journal_for_company(self, m_company, m_move_type):
        self.ensure_one()
        if self.m_journal_strategy == "configured_journal":
            if m_company == self.m_source_company_id:
                return (
                    self.m_source_sale_journal_id
                    if m_move_type in {"out_invoice", "out_refund"}
                    else self.m_source_purchase_journal_id
                )
            return (
                self.m_destination_sale_journal_id
                if m_move_type in {"out_invoice", "out_refund"}
                else self.m_destination_purchase_journal_id
            )
        journal_type = "sale" if m_move_type in {"out_invoice", "out_refund"} else "purchase"
        return self.env["account.journal"].search(
            [
                ("company_id", "=", m_company.id),
                ("type", "=", journal_type),
            ],
            order="sequence, id",
            limit=1,
        )
