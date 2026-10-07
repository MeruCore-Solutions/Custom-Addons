from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class MeruCoreIntercompanyTransaction(models.Model):
    _inherit = "merucore.intercompany.transaction"

    m_account_document_mapping_ids = fields.One2many(
        "merucore.intercompany.document.mapping",
        "m_transaction_id",
        string="Accounting Documents",
    )
    m_source_account_move_ids = fields.Many2many(
        "account.move",
        compute="m_compute_account_document_sets",
        string="Source Accounting Documents",
    )
    m_destination_account_move_ids = fields.Many2many(
        "account.move",
        compute="m_compute_account_document_sets",
        string="Destination Accounting Documents",
    )
    m_customer_invoice_ids = fields.Many2many(
        "account.move",
        compute="m_compute_account_document_sets",
        string="Customer Invoices",
    )
    m_vendor_bill_ids = fields.Many2many(
        "account.move",
        compute="m_compute_account_document_sets",
        string="Vendor Bills",
    )
    m_customer_refund_ids = fields.Many2many(
        "account.move",
        compute="m_compute_account_document_sets",
        string="Customer Credit Notes",
    )
    m_vendor_refund_ids = fields.Many2many(
        "account.move",
        compute="m_compute_account_document_sets",
        string="Vendor Refunds",
    )
    m_invoice_count = fields.Integer(compute="m_compute_account_document_counts")
    m_bill_count = fields.Integer(compute="m_compute_account_document_counts")
    m_customer_refund_count = fields.Integer(compute="m_compute_account_document_counts")
    m_vendor_refund_count = fields.Integer(compute="m_compute_account_document_counts")
    m_account_document_count = fields.Integer(compute="m_compute_account_document_counts")
    m_account_sync_state = fields.Selection(
        selection=[
            ("not_started", "Not Started"),
            ("draft_pair", "Draft Pair"),
            ("waiting_counterpart", "Waiting Counterpart"),
            ("partially_matched", "Partially Matched"),
            ("matched", "Matched"),
            ("posted", "Posted"),
            ("conflict", "Conflict"),
            ("failed", "Failed"),
            ("reversed", "Reversed"),
        ],
        default="not_started",
        copy=False,
        readonly=True,
    )
    m_comparison_currency_id = fields.Many2one(
        "res.currency",
        compute="m_compute_comparison_currency_id",
    )
    m_source_untaxed_total = fields.Monetary(
        compute="m_compute_account_totals",
        currency_field="m_comparison_currency_id",
    )
    m_destination_untaxed_total = fields.Monetary(
        compute="m_compute_account_totals",
        currency_field="m_comparison_currency_id",
    )
    m_source_tax_total = fields.Monetary(
        compute="m_compute_account_totals",
        currency_field="m_comparison_currency_id",
    )
    m_destination_tax_total = fields.Monetary(
        compute="m_compute_account_totals",
        currency_field="m_comparison_currency_id",
    )
    m_source_total = fields.Monetary(
        compute="m_compute_account_totals",
        currency_field="m_comparison_currency_id",
    )
    m_destination_total = fields.Monetary(
        compute="m_compute_account_totals",
        currency_field="m_comparison_currency_id",
    )
    m_amount_difference = fields.Monetary(
        compute="m_compute_account_totals",
        currency_field="m_comparison_currency_id",
    )
    m_tax_difference = fields.Monetary(
        compute="m_compute_account_totals",
        currency_field="m_comparison_currency_id",
    )
    m_currency_mismatch = fields.Boolean(compute="m_compute_account_totals")
    m_account_mismatch_count = fields.Integer(compute="m_compute_account_differences")
    m_tax_mismatch_count = fields.Integer(compute="m_compute_account_differences")
    m_line_mismatch_count = fields.Integer(compute="m_compute_account_differences")
    m_three_way_mismatch_count = fields.Integer(compute="m_compute_account_differences")
    m_pending_account_conflict = fields.Boolean(copy=False, readonly=True)
    m_last_account_sync_at = fields.Datetime(copy=False, readonly=True)
    m_account_sync_version = fields.Integer(default=0, copy=False, readonly=True)

    @api.depends("m_source_company_id")
    def m_compute_comparison_currency_id(self):
        for transaction in self:
            transaction.m_comparison_currency_id = transaction.m_source_company_id.currency_id

    @api.depends("m_account_document_mapping_ids", "m_account_document_mapping_ids.m_role", "m_account_document_mapping_ids.m_move_id")
    def m_compute_account_document_sets(self):
        for transaction in self:
            mappings = transaction.m_account_document_mapping_ids
            source_moves = mappings.filtered(lambda mapping: mapping.m_move_id.company_id == transaction.m_source_company_id).mapped("m_move_id")
            destination_moves = mappings.filtered(lambda mapping: mapping.m_move_id.company_id == transaction.m_destination_company_id).mapped("m_move_id")
            transaction.m_source_account_move_ids = [fields.Command.set(source_moves.ids)]
            transaction.m_destination_account_move_ids = [fields.Command.set(destination_moves.ids)]
            transaction.m_customer_invoice_ids = [fields.Command.set(mappings.filtered(lambda mapping: mapping.m_move_id.move_type == "out_invoice").mapped("m_move_id").ids)]
            transaction.m_vendor_bill_ids = [fields.Command.set(mappings.filtered(lambda mapping: mapping.m_move_id.move_type == "in_invoice").mapped("m_move_id").ids)]
            transaction.m_customer_refund_ids = [fields.Command.set(mappings.filtered(lambda mapping: mapping.m_move_id.move_type == "out_refund").mapped("m_move_id").ids)]
            transaction.m_vendor_refund_ids = [fields.Command.set(mappings.filtered(lambda mapping: mapping.m_move_id.move_type == "in_refund").mapped("m_move_id").ids)]

    @api.depends(
        "m_customer_invoice_ids",
        "m_vendor_bill_ids",
        "m_customer_refund_ids",
        "m_vendor_refund_ids",
    )
    def m_compute_account_document_counts(self):
        for transaction in self:
            transaction.m_invoice_count = len(transaction.m_customer_invoice_ids)
            transaction.m_bill_count = len(transaction.m_vendor_bill_ids)
            transaction.m_customer_refund_count = len(transaction.m_customer_refund_ids)
            transaction.m_vendor_refund_count = len(transaction.m_vendor_refund_ids)
            transaction.m_account_document_count = len(transaction.m_account_document_mapping_ids)

    @api.depends(
        "m_account_document_mapping_ids.m_move_id.amount_total",
        "m_account_document_mapping_ids.m_move_id.amount_untaxed",
        "m_account_document_mapping_ids.m_move_id.amount_tax",
        "m_account_document_mapping_ids.m_move_id.currency_id",
        "m_account_document_mapping_ids.m_move_id.invoice_date",
        "m_account_document_mapping_ids.m_move_id.date",
    )
    def m_compute_account_totals(self):
        for transaction in self:
            currency = transaction.m_comparison_currency_id
            transaction.m_source_untaxed_total = 0.0
            transaction.m_destination_untaxed_total = 0.0
            transaction.m_source_tax_total = 0.0
            transaction.m_destination_tax_total = 0.0
            transaction.m_source_total = 0.0
            transaction.m_destination_total = 0.0
            transaction.m_amount_difference = 0.0
            transaction.m_tax_difference = 0.0
            transaction.m_currency_mismatch = False
            if not currency:
                continue
            all_currencies = set()
            for move in transaction.m_source_account_move_ids:
                all_currencies.add(move.currency_id.id)
                conversion_date = move.invoice_date or move.date or fields.Date.context_today(move)
                transaction.m_source_untaxed_total += move.currency_id._convert(
                    move.amount_untaxed, currency, move.company_id, conversion_date
                )
                transaction.m_source_tax_total += move.currency_id._convert(
                    move.amount_tax, currency, move.company_id, conversion_date
                )
                transaction.m_source_total += move.currency_id._convert(
                    move.amount_total, currency, move.company_id, conversion_date
                )
            for move in transaction.m_destination_account_move_ids:
                all_currencies.add(move.currency_id.id)
                conversion_date = move.invoice_date or move.date or fields.Date.context_today(move)
                transaction.m_destination_untaxed_total += move.currency_id._convert(
                    move.amount_untaxed, currency, move.company_id, conversion_date
                )
                transaction.m_destination_tax_total += move.currency_id._convert(
                    move.amount_tax, currency, move.company_id, conversion_date
                )
                transaction.m_destination_total += move.currency_id._convert(
                    move.amount_total, currency, move.company_id, conversion_date
                )
            transaction.m_amount_difference = transaction.m_source_total - transaction.m_destination_total
            transaction.m_tax_difference = transaction.m_source_tax_total - transaction.m_destination_tax_total
            transaction.m_currency_mismatch = len(all_currencies) > 1

    @api.depends(
        "m_account_document_mapping_ids.m_move_id.invoice_line_ids.m_intercompany_line_key",
        "m_account_document_mapping_ids.m_move_id.invoice_line_ids.quantity",
        "m_account_document_mapping_ids.m_move_id.invoice_line_ids.tax_ids",
        "m_account_document_mapping_ids.m_move_id.invoice_line_ids.account_id",
    )
    def m_compute_account_differences(self):
        for transaction in self:
            differences = transaction.m_collect_account_differences()
            transaction.m_line_mismatch_count = differences["line"]
            transaction.m_account_mismatch_count = differences["account"]
            transaction.m_tax_mismatch_count = differences["tax"]
            transaction.m_three_way_mismatch_count = 0

    @api.model
    def m_build_account_idempotency_key(self, m_rule, m_account_move):
        return f"invoice_bill:rule:{m_rule.id}:move:{m_account_move.id}"

    def m_collect_account_differences(self):
        self.ensure_one()
        source_lines = {
            line.m_intercompany_line_key: line
            for line in self.m_source_account_move_ids.mapped("invoice_line_ids").filtered(
                lambda current: current.display_type in {"product", "line_section", "line_subsection", "line_note"}
                and current.m_intercompany_line_key
            )
        }
        destination_lines = {
            line.m_intercompany_line_key: line
            for line in self.m_destination_account_move_ids.mapped("invoice_line_ids").filtered(
                lambda current: current.display_type in {"product", "line_section", "line_subsection", "line_note"}
                and current.m_intercompany_line_key
            )
        }
        differences = {"line": 0, "account": 0, "tax": 0}
        all_keys = set(source_lines) | set(destination_lines)
        rule = self.m_rule_id
        for line_key in all_keys:
            source_line = source_lines.get(line_key)
            destination_line = destination_lines.get(line_key)
            if not source_line or not destination_line:
                differences["line"] += 1
                continue
            if source_line.display_type != destination_line.display_type:
                differences["line"] += 1
                continue
            if source_line.display_type == "product":
                if abs(source_line.quantity - destination_line.quantity) > rule.m_quantity_tolerance:
                    differences["line"] += 1
                if not destination_line.account_id:
                    differences["account"] += 1
                source_tax_count = len(source_line.tax_ids)
                destination_tax_count = len(destination_line.tax_ids)
                if source_tax_count != destination_tax_count and rule.m_tax_strategy != "no_taxes":
                    differences["tax"] += 1
        return differences

    def m_get_account_actor_environment(self, m_user, m_model_name, m_company, m_allowed_company_ids):
        return (
            self.env[m_model_name]
            .with_user(m_user)
            .with_company(m_company)
            .with_context(
                allowed_company_ids=m_allowed_company_ids,
                m_skip_intercompany_account_sync=True,
                m_skip_intercompany_sync=True,
            )
        )

    def m_get_account_actor(self, m_rule, m_model_name, m_company, m_operation, m_automatic=False):
        allowed_company_ids = [m_rule.m_source_company_id.id, m_rule.m_destination_company_id.id]
        actor = self.env.user
        if m_automatic:
            actor = m_rule.m_get_account_responsible_user() or self.env.user
        if m_company not in actor.company_ids:
            raise AccessError(_("The selected user does not have access to the target company."))
        if (
            m_rule.m_source_company_id not in actor.company_ids
            or m_rule.m_destination_company_id not in actor.company_ids
        ):
            raise AccessError(_("The selected user must have access to both companies in the company pair."))
        actor_env = self.m_get_account_actor_environment(
            actor,
            m_model_name,
            m_company,
            m_allowed_company_ids=allowed_company_ids,
        )
        actor_env.check_access_rights(m_operation)
        return actor, actor_env

    @api.model
    def m_get_account_transaction(self, m_rule, m_account_move):
        if m_account_move.m_intercompany_transaction_id:
            return m_account_move.m_intercompany_transaction_id
        idempotency_key = self.m_build_account_idempotency_key(m_rule, m_account_move)
        transaction = self.search([("m_idempotency_key", "=", idempotency_key)], limit=1)
        if transaction:
            return transaction
        transaction_vals = m_account_move.m_prepare_intercompany_transaction_values(m_rule)
        transaction_vals.update(
            {
                "m_idempotency_key": idempotency_key,
                "m_state": "draft",
            }
        )
        try:
            return self.with_context(m_intercompany_internal_write=True).create(transaction_vals)
        except ValidationError:
            transaction = self.search([("m_idempotency_key", "=", idempotency_key)], limit=1)
            if transaction:
                return transaction
            raise

    @api.model
    def m_sync_from_account_move(
        self,
        m_account_move,
        m_rule=False,
        m_automatic=False,
        m_raise_on_error=True,
        m_from_retry=False,
    ):
        move = m_account_move
        rule = move.m_validate_intercompany_account_eligibility(
            m_rule=m_rule,
            m_purpose="retry" if m_from_retry else "sync",
            m_automatic=m_automatic,
        )
        transaction = self.m_get_account_transaction(rule, move)
        try:
            counterpart_move = transaction.m_create_or_link_counterpart_move(
                m_source_move=move,
                m_rule=rule,
                m_automatic=m_automatic,
            )
        except Exception as error:  # pylint: disable=broad-except
            transaction.m_mark_account_sync_failed(
                m_source_move=move,
                m_summary=_("Intercompany accounting synchronization failed"),
                m_message=_("The counterpart invoice or bill could not be created or updated."),
                m_error=error,
            )
            if m_raise_on_error:
                raise
            return transaction
        transaction.m_mark_account_sync_success(move, counterpart_move)
        return transaction

    def m_mark_account_sync_failed(self, m_source_move, m_summary, m_message, m_error):
        self.ensure_one()
        error_message = self.m_sanitize_exception_message(m_error)
        self.with_context(m_intercompany_internal_write=True).write(
            {
                "m_account_sync_state": "failed",
                "m_pending_account_conflict": True,
                "m_last_account_sync_at": fields.Datetime.now(),
                "m_account_sync_version": self.m_account_sync_version + 1,
            }
        )
        m_source_move.with_context(m_skip_intercompany_account_sync=True).write(
            {
                "m_intercompany_transaction_id": self.id,
                "m_intercompany_sync_state": "failed",
                "m_intercompany_last_error": m_message,
                "m_intercompany_last_sync_at": fields.Datetime.now(),
                "m_intercompany_posting_pending": m_source_move.state == "posted",
                "m_intercompany_matching_state": "waiting_counterpart",
                "m_intercompany_sync_version": m_source_move.m_intercompany_sync_version + 1,
            }
        )
        self.m_mark_failed(
            m_summary=m_summary,
            m_message=m_message,
            m_technical_details=error_message,
        )

    def m_mark_account_sync_success(self, m_source_move, m_counterpart_move):
        self.ensure_one()
        self.m_upsert_document_mapping(m_source_move)
        self.m_upsert_document_mapping(m_counterpart_move, m_origin_move=m_source_move)
        sync_state = "posted" if all(move.state == "posted" for move in self.m_account_document_mapping_ids.mapped("m_move_id")) else "draft_pair"
        self.with_context(m_intercompany_internal_write=True).write(
            {
                "m_account_sync_state": sync_state,
                "m_pending_account_conflict": False,
                "m_last_account_sync_at": fields.Datetime.now(),
                "m_last_sync_at": fields.Datetime.now(),
                "m_account_sync_version": self.m_account_sync_version + 1,
            }
        )
        for move in (m_source_move | m_counterpart_move):
            matching_state = "matched" if not self.m_collect_account_differences()["line"] else "mismatch"
            move.with_context(m_skip_intercompany_account_sync=True).write(
                {
                    "m_intercompany_transaction_id": self.id,
                    "m_intercompany_document_key": move.m_intercompany_document_key or self.m_build_account_document_key(m_source_move),
                    "m_intercompany_sync_state": sync_state,
                    "m_intercompany_last_error": False,
                    "m_intercompany_last_sync_at": fields.Datetime.now(),
                    "m_intercompany_posting_pending": False,
                    "m_intercompany_matching_state": matching_state,
                    "m_intercompany_sync_version": move.m_intercompany_sync_version + 1,
                }
            )
            move.invoice_line_ids.with_context(m_skip_intercompany_account_sync=True).write(
                {
                    "m_intercompany_sync_state": "synced",
                    "m_intercompany_last_error": False,
                    "m_intercompany_last_sync_at": fields.Datetime.now(),
                    "m_intercompany_sync_version": 1,
                }
            )
        self.m_mark_healthy(
            m_summary=_("Intercompany accounting documents synchronized"),
            m_message=_("The linked counterpart invoice or bill is now synchronized."),
        )

    def m_build_account_document_key(self, m_source_move):
        self.ensure_one()
        return f"{self.m_idempotency_key or 'invoice_bill'}:move:{m_source_move.id}"

    def m_retry_handler_invoice_bill(self):
        self.ensure_one()
        source_move = self.m_get_source_record() or self.m_get_destination_record()
        if not source_move or source_move._name != "account.move":
            return {
                "success": False,
                "summary": _("Retry source move missing"),
                "message": _("The source accounting document is no longer available."),
                "health_state": "failed",
            }
        source_move.m_create_or_update_intercompany_counterpart(
            m_rule=self.m_rule_id,
            m_automatic=True,
            m_raise_on_error=True,
            m_from_retry=True,
        )
        return True

    def m_collect_extension_health_issues(self):
        issues = super().m_collect_extension_health_issues()
        for transaction in self.filtered(lambda current: current.m_transaction_type == "invoice_bill"):
            if transaction.m_account_sync_state == "failed":
                issues.append(_("Accounting document synchronization is marked as failed."))
            if transaction.m_account_sync_state in {"draft_pair", "posted"} and not transaction.m_account_document_mapping_ids:
                issues.append(_("No accounting document mappings are linked to the transaction."))
            if transaction.m_line_mismatch_count:
                issues.append(_("Linked accounting documents contain line mismatches."))
        return issues

    def m_resolve_counterpart_move_type(self, m_source_move):
        self.ensure_one()
        mapping = {
            "out_invoice": "in_invoice",
            "in_invoice": "out_invoice",
            "out_refund": "in_refund",
            "in_refund": "out_refund",
        }
        counterpart_move_type = mapping.get(m_source_move.move_type)
        if not counterpart_move_type:
            raise ValidationError(_("Unsupported intercompany move type %(move_type)s.", move_type=m_source_move.move_type))
        return counterpart_move_type

    def m_resolve_counterpart_company(self, m_source_move, m_rule):
        self.ensure_one()
        if m_source_move.company_id == m_rule.m_source_company_id:
            return m_rule.m_destination_company_id
        if m_source_move.company_id == m_rule.m_destination_company_id:
            return m_rule.m_source_company_id
        raise ValidationError(_("The source accounting document does not belong to the selected company pair."))

    def m_resolve_counterpart_partner(self, m_source_move, m_counterpart_company, m_counterpart_move_type):
        self.ensure_one()
        partner = m_source_move.company_id.partner_id.commercial_partner_id
        partner = partner.with_company(m_counterpart_company)
        account_field = (
            "property_account_receivable_id"
            if m_counterpart_move_type in {"out_invoice", "out_refund"}
            else "property_account_payable_id"
        )
        if not partner[account_field]:
            raise ValidationError(
                _("The partner %(partner)s is missing the required %(field)s in %(company)s.",
                  partner=partner.display_name,
                  field=account_field,
                  company=m_counterpart_company.display_name)
            )
        return partner

    def m_resolve_counterpart_currency(self, m_source_move, m_counterpart_company, m_counterpart_journal, m_rule):
        self.ensure_one()
        if m_rule.m_currency_strategy == "source_document_currency":
            return m_source_move.currency_id
        if m_rule.m_currency_strategy == "destination_journal_currency" and m_counterpart_journal.currency_id:
            return m_counterpart_journal.currency_id
        return m_counterpart_company.currency_id

    def m_resolve_counterpart_payment_term(self, m_counterpart_partner, m_counterpart_company, m_counterpart_move_type, m_rule):
        self.ensure_one()
        if not m_rule.m_sync_payment_terms:
            return False
        partner = m_counterpart_partner.with_company(m_counterpart_company)
        if m_counterpart_move_type in {"out_invoice", "out_refund"}:
            return partner.property_payment_term_id
        return partner.property_supplier_payment_term_id

    def m_resolve_counterpart_product(self, m_source_line, m_counterpart_company):
        self.ensure_one()
        product = m_source_line.product_id
        if not product:
            return self.env["product.product"]
        if product.company_id and product.company_id != m_counterpart_company:
            return self.env["product.product"]
        return product

    def m_resolve_counterpart_account(self, m_source_line, m_counterpart_move, m_counterpart_product, m_rule):
        self.ensure_one()
        mapping_scope = "refund" if m_counterpart_move.move_type in {"out_refund", "in_refund"} else (
            "sale" if m_counterpart_move.move_type == "out_invoice" else "purchase"
        )
        account_mapping = self.env["merucore.intercompany.account.mapping"].search(
            [
                ("m_rule_id", "=", m_rule.id),
                ("m_active", "=", True),
                ("m_source_account_id", "=", m_source_line.account_id.id),
                ("m_move_scope", "in", [mapping_scope, "all"]),
            ],
            order="m_sequence, id",
            limit=1,
        )
        if m_rule.m_account_strategy == "explicit_mapping":
            if not account_mapping:
                raise ValidationError(
                    _("No active intercompany account mapping was found for account %(account)s.",
                      account=m_source_line.account_id.display_name)
                )
            return account_mapping, account_mapping.m_destination_account_id
        if m_counterpart_product:
            product_accounts = m_counterpart_product.with_company(m_counterpart_move.company_id).product_tmpl_id.get_product_accounts(
                fiscal_pos=m_counterpart_move.fiscal_position_id
            )
            account_field = "income" if m_counterpart_move.move_type in {"out_invoice", "out_refund"} else "expense"
            account = product_accounts.get(account_field)
            if account:
                return account_mapping, account
        if m_rule.m_account_strategy == "destination_fiscal_position" and m_counterpart_move.fiscal_position_id:
            mapped_account = m_counterpart_move.fiscal_position_id.map_account(m_source_line.account_id)
            if mapped_account:
                return account_mapping, mapped_account
        raise ValidationError(_("No valid destination commercial account could be resolved for line %(line)s.", line=m_source_line.name))

    def m_resolve_counterpart_taxes(self, m_source_line, m_counterpart_move, m_counterpart_product, m_rule):
        self.ensure_one()
        mapping_scope = "refund" if m_counterpart_move.move_type in {"out_refund", "in_refund"} else (
            "sale" if m_counterpart_move.move_type == "out_invoice" else "purchase"
        )
        tax_mappings = self.env["merucore.intercompany.tax.mapping"]
        taxes = self.env["account.tax"]
        if m_rule.m_tax_strategy == "no_taxes":
            return tax_mappings, taxes
        if m_rule.m_tax_strategy == "explicit_mapping":
            for source_tax in m_source_line.tax_ids:
                mapping = self.env["merucore.intercompany.tax.mapping"].search(
                    [
                        ("m_rule_id", "=", m_rule.id),
                        ("m_active", "=", True),
                        ("m_source_tax_id", "=", source_tax.id),
                        ("m_move_scope", "in", [mapping_scope, "all"]),
                    ],
                    order="m_sequence, id",
                    limit=1,
                )
                if not mapping:
                    raise ValidationError(
                        _("No active intercompany tax mapping was found for tax %(tax)s.",
                          tax=source_tax.display_name)
                    )
                tax_mappings |= mapping
                taxes |= mapping.m_destination_tax_id
            return tax_mappings, taxes
        if m_counterpart_product:
            taxes = (
                m_counterpart_product.taxes_id
                if m_counterpart_move.move_type in {"out_invoice", "out_refund"}
                else m_counterpart_product.supplier_taxes_id
            ).filtered(lambda tax: not tax.company_id or tax.company_id == m_counterpart_move.company_id)
        if m_rule.m_tax_strategy == "destination_fiscal_position" and m_counterpart_move.fiscal_position_id:
            taxes = m_counterpart_move.fiscal_position_id.map_tax(taxes)
        return tax_mappings, taxes

    def m_resolve_counterpart_analytic_distribution(self, m_source_line, m_rule):
        self.ensure_one()
        if not m_rule.m_sync_analytic_distribution or not m_source_line.analytic_distribution:
            return False
        distribution = {}
        for source_analytic_id, percentage in m_source_line.analytic_distribution.items():
            mapping = self.env["merucore.intercompany.analytic.mapping"].search(
                [
                    ("m_rule_id", "=", m_rule.id),
                    ("m_active", "=", True),
                    ("m_source_analytic_account_id", "=", int(source_analytic_id)),
                ],
                order="m_sequence, id",
                limit=1,
            )
            if not mapping:
                raise ValidationError(_("Missing analytic mapping for source analytic account ID %(analytic_id)s.", analytic_id=source_analytic_id))
            distribution[str(mapping.m_destination_analytic_account_id.id)] = percentage
        return distribution

    def m_get_conversion_date(self, m_source_move, m_counterpart_move, m_rule):
        self.ensure_one()
        strategy = m_rule.m_exchange_rate_date_strategy
        if strategy == "source_accounting_date":
            return m_source_move.date
        if strategy == "destination_invoice_date":
            return m_counterpart_move.invoice_date or m_counterpart_move.date or fields.Date.context_today(m_counterpart_move)
        if strategy == "current_date":
            return fields.Date.context_today(m_counterpart_move)
        return m_source_move.invoice_date or m_source_move.date or fields.Date.context_today(m_source_move)

    def m_compute_counterpart_unit_price(self, m_source_line, m_source_move, m_counterpart_move, m_rule, m_counterpart_product):
        self.ensure_one()
        if m_rule.m_price_strategy == "destination_product_price" and m_counterpart_product:
            return (
                m_counterpart_product.lst_price
                if m_counterpart_move.move_type in {"out_invoice", "out_refund"}
                else m_counterpart_product.standard_price
            )
        conversion_date = self.m_get_conversion_date(m_source_move, m_counterpart_move, m_rule)
        return m_source_move.currency_id._convert(
            m_source_line.price_unit,
            m_counterpart_move.currency_id,
            m_source_move.company_id,
            conversion_date,
        )

    def m_prepare_counterpart_invoice_line_values(self, m_source_line, m_source_move, m_counterpart_move, m_rule):
        self.ensure_one()
        line_vals = {
            "name": m_source_line.name,
            "sequence": m_source_line.sequence,
            "m_intercompany_transaction_id": self.id,
            "m_intercompany_origin_line_id": m_source_line.id,
            "m_intercompany_line_key": m_source_line.m_intercompany_line_key,
            "m_intercompany_sync_state": "synced",
            "m_intercompany_sync_version": m_source_line.m_intercompany_sync_version + 1,
            "m_intercompany_last_sync_at": fields.Datetime.now(),
        }
        if m_source_line.display_type in {"line_section", "line_subsection", "line_note"}:
            line_vals["display_type"] = m_source_line.display_type
            return line_vals
        counterpart_product = self.m_resolve_counterpart_product(m_source_line, m_counterpart_move.company_id)
        account_mapping, counterpart_account = self.m_resolve_counterpart_account(
            m_source_line,
            m_counterpart_move,
            counterpart_product,
            m_rule,
        )
        tax_mappings, counterpart_taxes = self.m_resolve_counterpart_taxes(
            m_source_line,
            m_counterpart_move,
            counterpart_product,
            m_rule,
        )
        analytic_distribution = self.m_resolve_counterpart_analytic_distribution(m_source_line, m_rule)
        line_vals.update(
            {
                "display_type": "product",
                "product_id": counterpart_product.id,
                "product_uom_id": m_source_line.product_uom_id.id,
                "quantity": m_source_line.quantity if m_rule.m_sync_quantities else 1.0,
                "price_unit": self.m_compute_counterpart_unit_price(
                    m_source_line,
                    m_source_move,
                    m_counterpart_move,
                    m_rule,
                    counterpart_product,
                ),
                "discount": m_source_line.discount if m_rule.m_sync_discounts else 0.0,
                "account_id": counterpart_account.id,
                "tax_ids": [fields.Command.set(counterpart_taxes.ids)],
                "analytic_distribution": analytic_distribution,
                "m_intercompany_account_mapping_id": account_mapping.id if account_mapping else False,
                "m_intercompany_tax_mapping_ids": [fields.Command.set(tax_mappings.ids)],
            }
        )
        return line_vals

    def m_prepare_counterpart_move_values(self, m_source_move, m_rule, m_counterpart_move=False):
        self.ensure_one()
        counterpart_company = self.m_resolve_counterpart_company(m_source_move, m_rule)
        counterpart_move_type = self.m_resolve_counterpart_move_type(m_source_move)
        counterpart_journal = m_rule.m_get_account_journal_for_company(counterpart_company, counterpart_move_type)
        if not counterpart_journal:
            raise ValidationError(
                _("No destination %(journal_type)s journal could be resolved for %(company)s.",
                  journal_type="sale" if counterpart_move_type in {"out_invoice", "out_refund"} else "purchase",
                  company=counterpart_company.display_name)
            )
        counterpart_currency = self.m_resolve_counterpart_currency(
            m_source_move,
            counterpart_company,
            counterpart_journal,
            m_rule,
        )
        counterpart_partner = self.m_resolve_counterpart_partner(
            m_source_move,
            counterpart_company,
            counterpart_move_type,
        )
        move_stub = self.env["account.move"].with_company(counterpart_company).new(
            {
                "company_id": counterpart_company.id,
                "move_type": counterpart_move_type,
                "partner_id": counterpart_partner.id,
                "journal_id": counterpart_journal.id,
                "currency_id": counterpart_currency.id,
            }
        )
        payment_term = self.m_resolve_counterpart_payment_term(
            counterpart_partner,
            counterpart_company,
            counterpart_move_type,
            m_rule,
        )
        document_key = m_source_move.m_intercompany_document_key or self.m_build_account_document_key(m_source_move)
        invoice_date = m_source_move.invoice_date if m_rule.m_sync_dates else fields.Date.context_today(self)
        accounting_date = m_source_move.date if m_rule.m_sync_dates else invoice_date
        move_vals = {
            "move_type": counterpart_move_type,
            "company_id": counterpart_company.id,
            "partner_id": counterpart_partner.id,
            "journal_id": counterpart_journal.id,
            "currency_id": counterpart_currency.id,
            "invoice_date": invoice_date,
            "date": accounting_date,
            "invoice_origin": m_source_move.name or m_source_move.ref,
            "ref": m_source_move.ref or m_source_move.name,
            "payment_reference": m_source_move.payment_reference or m_source_move.name,
            "invoice_payment_term_id": payment_term.id if payment_term else False,
            "narration": m_source_move.narration if m_rule.m_sync_draft_headers else False,
            "m_intercompany_transaction_id": self.id,
            "m_intercompany_origin_move_id": m_source_move.id,
            "m_intercompany_document_key": document_key,
            "m_intercompany_sync_state": "draft_pair",
            "m_intercompany_last_sync_at": fields.Datetime.now(),
            "m_intercompany_matching_state": "matched",
            "m_intercompany_sync_version": (m_counterpart_move.m_intercompany_sync_version + 1) if m_counterpart_move else 1,
        }
        if not m_rule.m_sync_payment_terms:
            move_vals.pop("invoice_payment_term_id")
        line_commands = [fields.Command.create(
            self.m_prepare_counterpart_invoice_line_values(line, m_source_move, move_stub, m_rule)
        ) for line in m_source_move.m_get_commercial_lines()]
        move_vals["invoice_line_ids"] = line_commands
        return move_vals

    def m_upsert_document_mapping(self, m_move, m_origin_move=False):
        self.ensure_one()
        mapping_model = self.env["merucore.intercompany.document.mapping"]
        role = m_move.m_get_intercompany_role()
        document_key = m_move.m_intercompany_document_key or self.m_build_account_document_key(m_origin_move or m_move)
        mapping = mapping_model.search(
            [
                ("m_transaction_id", "=", self.id),
                ("m_move_id", "=", m_move.id),
            ],
            limit=1,
        )
        vals = {
            "m_transaction_id": self.id,
            "m_move_id": m_move.id,
            "m_role": role,
            "m_document_key": document_key,
            "m_origin_move_id": (m_origin_move or m_move.m_intercompany_origin_move_id).id or False,
        }
        if mapping:
            mapping.write(vals)
            return mapping
        return mapping_model.create(vals)

    def m_create_or_link_counterpart_move(self, m_source_move, m_rule, m_automatic=False):
        self.ensure_one()
        counterpart_company = self.m_resolve_counterpart_company(m_source_move, m_rule)
        counterpart_move_type = self.m_resolve_counterpart_move_type(m_source_move)
        counterpart_move = self.m_account_document_mapping_ids.mapped("m_move_id").filtered(
            lambda move: move.company_id == counterpart_company and move.move_type == counterpart_move_type and move.state != "cancel"
        )[:1]
        if counterpart_move and counterpart_move.state != "draft" and not m_rule.m_allow_posted_counterpart_changes:
            return counterpart_move
        _, counterpart_env = self.m_get_account_actor(
            m_rule,
            "account.move",
            counterpart_company,
            "create" if not counterpart_move else "write",
            m_automatic=m_automatic,
        )
        move_vals = self.m_prepare_counterpart_move_values(
            m_source_move,
            m_rule,
            m_counterpart_move=counterpart_move,
        )
        if counterpart_move:
            if counterpart_move.state != "draft":
                raise ValidationError(_("Only draft counterpart invoices and bills can be refreshed."))
            if not m_rule.m_sync_draft_lines:
                move_vals.pop("invoice_line_ids", None)
            counterpart_move.with_context(
                m_skip_intercompany_account_sync=True,
                m_skip_intercompany_sync=True,
            ).write(move_vals)
        else:
            counterpart_move = counterpart_env.create(move_vals)
        counterpart_move.with_context(m_skip_intercompany_account_sync=True).write(
            {
                "m_intercompany_transaction_id": self.id,
                "m_intercompany_origin_move_id": m_source_move.id,
                "m_intercompany_document_key": move_vals["m_intercompany_document_key"],
            }
        )
        if (
            m_rule.m_auto_post_counterpart
            or m_rule.m_counterpart_document_state == "posted"
            or (m_source_move.move_type in {"out_refund", "in_refund"} and m_rule.m_refund_strategy == "auto_post_counterpart_refund")
        ) and counterpart_move.state == "draft":
            counterpart_move.with_context(
                m_skip_intercompany_account_sync=True,
                m_skip_intercompany_sync=True,
            ).action_post()
        return counterpart_move

    def m_action_open_account_documents(self):
        self.ensure_one()
        moves = self.m_account_document_mapping_ids.mapped("m_move_id")
        if not moves:
            raise UserError(_("No accounting documents are linked to this transaction."))
        action = {
            "type": "ir.actions.act_window",
            "res_model": "account.move",
            "view_mode": "list,form",
            "domain": [("id", "in", moves.ids)],
            "context": {"create": False, "allowed_company_ids": self.m_company_ids.ids},
        }
        if len(moves) == 1:
            action.update({"view_mode": "form", "res_id": moves.id, "domain": False})
        return action
