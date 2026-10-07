from psycopg2 import IntegrityError

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError


class MeruCoreIntercompanyTransaction(models.Model):
    _name = "merucore.intercompany.transaction"
    _description = "MeruCore Intercompany Transaction"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    m_name = fields.Char(
        required=True,
        copy=False,
        readonly=True,
        index=True,
        default="/",
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
    m_transaction_type = fields.Selection(
        selection=[
            ("manual", "Manual"),
            ("sale_purchase", "Sale / Purchase"),
            ("stock", "Stock"),
            ("invoice_bill", "Invoice / Bill"),
            ("payment", "Payment"),
            ("cost_allocation", "Cost Allocation"),
            ("elimination", "Elimination"),
        ],
        default="manual",
        required=True,
        index=True,
        tracking=True,
    )
    m_state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("in_progress", "In Progress"),
            ("done", "Done"),
            ("cancelled", "Cancelled"),
        ],
        default="draft",
        required=True,
        index=True,
        tracking=True,
        readonly=True,
    )
    m_health_state = fields.Selection(
        selection=[
            ("healthy", "Healthy"),
            ("warning", "Warning"),
            ("failed", "Failed"),
            ("retrying", "Retrying"),
        ],
        default="healthy",
        required=True,
        index=True,
        tracking=True,
        readonly=True,
    )
    m_direction = fields.Char(
        compute="m_compute_direction",
        store=True,
    )
    m_reference = fields.Char(index=True, tracking=True)
    m_idempotency_key = fields.Char(index=True, copy=False)
    m_source_model = fields.Char(index=True, copy=False)
    m_source_res_id = fields.Integer(index=True, copy=False)
    m_destination_model = fields.Char(index=True, copy=False)
    m_destination_res_id = fields.Integer(index=True, copy=False)
    m_source_document_name = fields.Char(
        compute="m_compute_document_labels",
    )
    m_destination_document_name = fields.Char(
        compute="m_compute_document_labels",
    )
    m_source_document_accessible = fields.Boolean(
        compute="m_compute_document_labels",
    )
    m_destination_document_accessible = fields.Boolean(
        compute="m_compute_document_labels",
    )
    m_last_sync_at = fields.Datetime(readonly=True, copy=False)
    m_last_health_check_at = fields.Datetime(readonly=True, copy=False)
    m_last_error_message = fields.Text(readonly=True, copy=False)
    m_retry_count = fields.Integer(default=0, readonly=True, copy=False)
    m_next_retry_at = fields.Datetime(readonly=True, copy=False)
    m_responsible_user_id = fields.Many2one(
        "res.users",
        string="Responsible",
        tracking=True,
        ondelete="set null",
    )
    m_event_ids = fields.One2many(
        "merucore.intercompany.event",
        "m_transaction_id",
        string="Events",
    )
    m_event_count = fields.Integer(
        compute="m_compute_event_counts",
    )
    m_error_event_count = fields.Integer(
        compute="m_compute_event_counts",
    )
    m_warning_event_count = fields.Integer(
        compute="m_compute_event_counts",
    )
    m_has_open_issue = fields.Boolean(
        compute="m_compute_has_open_issue",
        store=True,
        index=True,
    )
    m_company_ids = fields.Many2many(
        "res.company",
        compute="m_compute_company_ids",
        store=True,
    )
    m_note = fields.Html()

    def init(self):
        self.env.cr.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
                merucore_intercompany_transaction_idempotency_uniq
            ON merucore_intercompany_transaction (m_idempotency_key)
            WHERE COALESCE(m_idempotency_key, '') <> ''
            """
        )

    @api.depends("m_source_company_id", "m_destination_company_id")
    def m_compute_direction(self):
        for transaction in self:
            if transaction.m_source_company_id and transaction.m_destination_company_id:
                transaction.m_direction = _(
                    "%(source)s -> %(destination)s",
                    source=transaction.m_source_company_id.display_name,
                    destination=transaction.m_destination_company_id.display_name,
                )
            else:
                transaction.m_direction = False

    @api.depends("m_source_company_id", "m_destination_company_id")
    def m_compute_company_ids(self):
        for transaction in self:
            transaction.m_company_ids = [
                fields.Command.set(
                    (transaction.m_source_company_id | transaction.m_destination_company_id).ids
                )
            ]

    @api.depends("m_event_ids", "m_event_ids.m_event_type")
    def m_compute_event_counts(self):
        counts = {transaction.id: {"all": 0, "error": 0, "warning": 0} for transaction in self}
        all_grouped = self.env["merucore.intercompany.event"]._read_group(
            [("m_transaction_id", "in", self.ids)],
            ["m_transaction_id"],
            ["__count"],
        )
        error_grouped = self.env["merucore.intercompany.event"]._read_group(
            [("m_transaction_id", "in", self.ids), ("m_event_type", "=", "error")],
            ["m_transaction_id"],
            ["__count"],
        )
        warning_grouped = self.env["merucore.intercompany.event"]._read_group(
            [("m_transaction_id", "in", self.ids), ("m_event_type", "=", "warning")],
            ["m_transaction_id"],
            ["__count"],
        )
        for transaction, count in all_grouped:
            counts[transaction.id]["all"] = count
        for transaction, count in error_grouped:
            counts[transaction.id]["error"] = count
        for transaction, count in warning_grouped:
            counts[transaction.id]["warning"] = count
        for transaction in self:
            transaction.m_event_count = counts[transaction.id]["all"]
            transaction.m_error_event_count = counts[transaction.id]["error"]
            transaction.m_warning_event_count = counts[transaction.id]["warning"]

    @api.depends("m_health_state", "m_event_ids.m_event_type", "m_event_ids.m_resolved")
    def m_compute_has_open_issue(self):
        for transaction in self:
            unresolved_events = transaction.m_event_ids.filtered(
                lambda event: event.m_event_type in {"warning", "error"} and not event.m_resolved
            )
            transaction.m_has_open_issue = bool(
                unresolved_events or transaction.m_health_state in {"warning", "failed", "retrying"}
            )

    @api.depends(
        "m_source_model",
        "m_source_res_id",
        "m_destination_model",
        "m_destination_res_id",
        "m_company_ids",
    )
    def m_compute_document_labels(self):
        for transaction in self:
            source_record = transaction.m_get_source_record()
            destination_record = transaction.m_get_destination_record()
            transaction.m_source_document_accessible = bool(source_record)
            transaction.m_destination_document_accessible = bool(destination_record)
            transaction.m_source_document_name = (
                source_record.display_name
                if source_record
                else transaction.m_get_document_fallback_label(
                    transaction.m_source_model, transaction.m_source_res_id
                )
            )
            transaction.m_destination_document_name = (
                destination_record.display_name
                if destination_record
                else transaction.m_get_document_fallback_label(
                    transaction.m_destination_model, transaction.m_destination_res_id
                )
            )

    @api.depends("m_name")
    def _compute_display_name(self):
        for transaction in self:
            transaction.display_name = transaction.m_name

    @api.constrains("m_source_company_id", "m_destination_company_id")
    def m_check_company_pair(self):
        for transaction in self:
            if (
                transaction.m_source_company_id
                and transaction.m_destination_company_id
                and transaction.m_source_company_id == transaction.m_destination_company_id
            ):
                raise ValidationError(_("Source and destination companies must be different."))

    @api.constrains("m_rule_id", "m_source_company_id", "m_destination_company_id")
    def m_check_rule_matches_companies(self):
        for transaction in self:
            if not transaction.m_rule_id:
                continue
            if (
                transaction.m_source_company_id != transaction.m_rule_id.m_source_company_id
                or transaction.m_destination_company_id != transaction.m_rule_id.m_destination_company_id
            ):
                raise ValidationError(
                    _("Transaction companies must match the selected company-pair rule.")
                )

    @api.constrains("m_idempotency_key")
    def m_check_idempotency_key_unique(self):
        for transaction in self.filtered("m_idempotency_key"):
            duplicate = self.search(
                [
                    ("id", "!=", transaction.id),
                    ("m_idempotency_key", "=", transaction.m_idempotency_key),
                ],
                limit=1,
            )
            if duplicate:
                raise ValidationError(_("The idempotency key must be unique when it is set."))

    @api.constrains(
        "m_source_model",
        "m_source_res_id",
        "m_destination_model",
        "m_destination_res_id",
        "m_source_company_id",
        "m_destination_company_id",
    )
    def m_check_document_links(self):
        for transaction in self:
            transaction.m_validate_document_link(
                transaction.m_source_model,
                transaction.m_source_res_id,
                transaction.m_source_company_id,
                _("source"),
            )
            transaction.m_validate_document_link(
                transaction.m_destination_model,
                transaction.m_destination_res_id,
                transaction.m_destination_company_id,
                _("destination"),
            )

    @api.constrains("m_responsible_user_id", "m_source_company_id", "m_destination_company_id")
    def m_check_responsible_user_companies(self):
        for transaction in self.filtered("m_responsible_user_id"):
            allowed_companies = transaction.m_responsible_user_id.company_ids
            if (
                transaction.m_source_company_id not in allowed_companies
                or transaction.m_destination_company_id not in allowed_companies
            ):
                raise ValidationError(
                    _("The responsible user must have access to both the source and destination companies.")
                )

    @api.model_create_multi
    def create(self, vals_list):
        self.m_validate_manual_vals(vals_list, create_mode=True)
        for vals in vals_list:
            vals.setdefault("m_name", self.env["ir.sequence"].next_by_code("merucore.intercompany.transaction") or "/")
            rule = self.env["merucore.intercompany.rule"].browse(vals.get("m_rule_id"))
            if rule:
                vals.setdefault("m_source_company_id", rule.m_source_company_id.id)
                vals.setdefault("m_destination_company_id", rule.m_destination_company_id.id)
                vals.setdefault("m_responsible_user_id", rule.m_responsible_user_id.id)
            if not vals.get("m_responsible_user_id") and vals.get("m_source_company_id"):
                company = self.env["res.company"].browse(vals["m_source_company_id"])
                vals["m_responsible_user_id"] = company.m_intercompany_default_responsible_user_id.id or False
        try:
            records = super().create(vals_list)
        except IntegrityError as error:
            raise ValidationError(_("Unable to create the transaction because one of the unique constraints was violated.")) from error
        for record in records:
            record.m_log_event(
                m_event_type="info",
                m_summary=_("Transaction created"),
                m_message=_("The intercompany transaction has been created."),
            )
        return records

    def write(self, vals):
        self.m_validate_manual_vals([vals], create_mode=False)
        if "m_name" in vals:
            raise AccessError(_("The transaction sequence cannot be edited manually."))
        return super().write(vals)

    def unlink(self):
        if self.env.context.get("module_uninstall"):
            return super().unlink()
        self.check_access("unlink")
        if self.filtered("m_event_ids"):
            raise ValidationError(_("Transactions with audit events cannot be deleted."))
        return super().unlink()

    def m_action_open_transaction_form(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "current",
            "context": {"allowed_company_ids": self.m_company_ids.ids},
        }

    def m_action_start(self):
        for transaction in self:
            previous_state = transaction.m_state
            transaction.m_transition_state("in_progress")
            transaction.with_context(m_intercompany_internal_write=True).write(
                {"m_health_state": "healthy"}
            )
            transaction.m_log_event(
                m_event_type="state_change",
                m_summary=_("Transaction started"),
                m_old_value=previous_state,
                m_new_value="in_progress",
            )

    def m_action_mark_done(self):
        for transaction in self:
            if transaction.m_state == "cancelled":
                raise UserError(_("Cancelled transactions cannot be marked as done."))
            previous_state = transaction.m_state
            transaction.with_context(m_intercompany_internal_write=True).write(
                {
                    "m_state": "done",
                    "m_last_sync_at": fields.Datetime.now(),
                }
            )
            transaction.m_mark_healthy(
                m_summary=_("Transaction completed"),
                m_message=_("The intercompany transaction finished successfully."),
            )
            transaction.m_log_event(
                m_event_type="state_change",
                m_summary=_("Transaction state updated"),
                m_old_value=previous_state,
                m_new_value="done",
            )

    def m_action_cancel(self):
        for transaction in self:
            if transaction.m_state == "done":
                raise UserError(_("Completed transactions cannot be cancelled."))
            previous_state = transaction.m_state
            transaction.with_context(m_intercompany_internal_write=True).write(
                {
                    "m_state": "cancelled",
                    "m_next_retry_at": False,
                }
            )
            transaction.m_log_event(
                m_event_type="state_change",
                m_summary=_("Transaction cancelled"),
                m_old_value=previous_state,
                m_new_value="cancelled",
            )

    def m_action_open_retry_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Retry Intercompany Transaction"),
            "res_model": "merucore.intercompany.retry.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_m_transaction_id": self.id,
                "allowed_company_ids": self.m_company_ids.ids,
            },
        }

    def m_action_open_events(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "merucore_intercompany_base.m_action_intercompany_events"
        )
        action["domain"] = [("m_transaction_id", "=", self.id)]
        action["context"] = {"allowed_company_ids": self.m_company_ids.ids}
        return action

    def m_action_open_error_events(self):
        self.ensure_one()
        action = self.m_action_open_events()
        action["domain"] = [
            ("m_transaction_id", "=", self.id),
            ("m_event_type", "=", "error"),
        ]
        return action

    def m_action_open_warning_events(self):
        self.ensure_one()
        action = self.m_action_open_events()
        action["domain"] = [
            ("m_transaction_id", "=", self.id),
            ("m_event_type", "=", "warning"),
        ]
        return action

    def m_action_open_source_document(self):
        self.ensure_one()
        return self.m_action_open_document("source")

    def m_action_open_destination_document(self):
        self.ensure_one()
        return self.m_action_open_document("destination")

    def m_log_event(
        self,
        m_event_type,
        m_summary,
        m_message=False,
        m_company_id=False,
        m_model_name=False,
        m_res_id=False,
        m_old_value=False,
        m_new_value=False,
        m_technical_details=False,
        m_retry_number=False,
    ):
        self.ensure_one()
        event_vals = {
            "m_transaction_id": self.id,
            "m_company_id": m_company_id or self.m_source_company_id.id,
            "m_event_type": m_event_type,
            "m_summary": m_summary,
            "m_message": m_message,
            "m_model_name": m_model_name,
            "m_res_id": m_res_id or 0,
            "m_old_value": m_old_value,
            "m_new_value": m_new_value,
            "m_technical_details": m_technical_details,
            "m_retry_number": m_retry_number or 0,
        }
        # sudo is required because audit events are intentionally immutable and not
        # directly creatable through regular access rights.
        event = (
            self.env["merucore.intercompany.event"]
            .sudo()
            .with_context(m_intercompany_event_create=True)
            .create(event_vals)
        )
        if m_event_type in {"state_change", "warning", "error", "retry"}:
            body = m_message or m_summary
            self.message_post(body=body, message_type="comment", subtype_xmlid="mail.mt_note")
        return event

    def m_mark_warning(self, m_summary, m_message=False, m_technical_details=False):
        self.ensure_one()
        self.with_context(m_intercompany_internal_write=True).write(
            {
                "m_health_state": "warning",
                "m_last_error_message": m_message or m_summary,
            }
        )
        event = self.m_log_event(
            m_event_type="warning",
            m_summary=m_summary,
            m_message=m_message,
            m_company_id=self.m_destination_company_id.id or self.m_source_company_id.id,
            m_technical_details=m_technical_details,
        )
        if self.m_rule_id.m_notify_on_warning:
            self.m_schedule_issue_activity(event)
        return event

    def m_mark_failed(self, m_summary, m_message=False, m_technical_details=False):
        self.ensure_one()
        self.with_context(m_intercompany_internal_write=True).write(
            {
                "m_health_state": "failed",
                "m_last_error_message": m_message or m_summary,
            }
        )
        event = self.m_log_event(
            m_event_type="error",
            m_summary=m_summary,
            m_message=m_message,
            m_company_id=self.m_destination_company_id.id or self.m_source_company_id.id,
            m_technical_details=m_technical_details,
        )
        if self.m_rule_id.m_notify_on_failure:
            self.m_schedule_issue_activity(event)
        return event

    def m_mark_healthy(self, m_summary=False, m_message=False):
        self.ensure_one()
        open_issue_events = self.m_event_ids.filtered(
            lambda event: event.m_event_type in {"warning", "error"} and not event.m_resolved
        )
        if open_issue_events:
            open_issue_events.sudo().with_context(m_intercompany_event_resolve=True).write(
                {
                    "m_resolved": True,
                    "m_resolved_at": fields.Datetime.now(),
                    "m_resolved_by_id": self.env.user.id,
                }
            )
            for event in open_issue_events:
                self.m_close_issue_activities(event)
        values = {
            "m_health_state": "healthy",
            "m_last_error_message": False,
            "m_next_retry_at": False,
        }
        self.with_context(m_intercompany_internal_write=True).write(values)
        if m_summary or m_message:
            self.m_log_event(
                m_event_type="info",
                m_summary=m_summary or _("Transaction is healthy"),
                m_message=m_message,
            )

    def m_prepare_retry(self, m_force_retry=False, m_manager_note=False):
        self.ensure_one()
        if self.m_state in {"done", "cancelled"}:
            raise UserError(_("Done or cancelled transactions cannot be retried."))
        max_retry_count = self.m_rule_id.m_max_retry_count
        next_retry_count = self.m_retry_count + 1
        if not m_force_retry and next_retry_count > max_retry_count:
            raise UserError(_("The maximum retry count has already been reached for this transaction."))
        self.with_context(m_intercompany_internal_write=True).write(
            {
                "m_retry_count": next_retry_count,
                "m_health_state": "retrying",
                "m_state": "in_progress",
                "m_next_retry_at": False,
            }
        )
        return self.m_log_event(
            m_event_type="retry",
            m_summary=_("Retry attempt %(number)s", number=next_retry_count),
            m_message=m_manager_note or _("A retry attempt has been started."),
            m_company_id=self.m_source_company_id.id,
            m_retry_number=next_retry_count,
        )

    def m_get_retry_handler(self):
        self.ensure_one()
        method_name = f"m_retry_handler_{self.m_transaction_type}"
        handler = getattr(self, method_name, None)
        return handler if callable(handler) else None

    def m_execute_retry(self, m_force_retry=False, m_manager_note=False, m_from_cron=False):
        self.ensure_one()
        locked_transaction = self
        if not self.env.context.get("m_intercompany_retry_locked"):
            locked_transaction = self.try_lock_for_update()
            if locked_transaction != self:
                raise UserError(_("This transaction is already being retried by another worker."))
            locked_transaction = locked_transaction.with_context(m_intercompany_retry_locked=True)
        locked_transaction.m_prepare_retry(
            m_force_retry=m_force_retry,
            m_manager_note=m_manager_note,
        )
        handler = locked_transaction.m_get_retry_handler()
        if not handler:
            message = _(
                "No retry handler is registered for the '%(transaction_type)s' transaction type.",
                transaction_type=locked_transaction.m_transaction_type,
            )
            locked_transaction.m_prepare_next_retry_at()
            return locked_transaction.m_mark_warning(
                m_summary=_("Retry handler missing"),
                m_message=message,
            )
        try:
            result = handler()
        except Exception as error:  # pylint: disable=broad-except
            locked_transaction.m_prepare_next_retry_at()
            return locked_transaction.m_mark_failed(
                m_summary=_("Retry failed"),
                m_message=_("The retry attempt ended with an exception."),
                m_technical_details=locked_transaction.m_sanitize_exception_message(error),
            )
        if result is True:
            locked_transaction.m_action_mark_done()
            return True
        if isinstance(result, dict):
            if result.get("success"):
                locked_transaction.m_action_mark_done()
                return True
            if result.get("health_state") == "failed":
                locked_transaction.m_prepare_next_retry_at()
                return locked_transaction.m_mark_failed(
                    m_summary=result.get("summary") or _("Retry failed"),
                    m_message=result.get("message"),
                    m_technical_details=result.get("technical_details"),
                )
            locked_transaction.m_prepare_next_retry_at(
                m_next_retry_at=result.get("next_retry_at")
            )
            return locked_transaction.m_mark_warning(
                m_summary=result.get("summary") or _("Retry did not complete"),
                m_message=result.get("message"),
                m_technical_details=result.get("technical_details"),
            )
        locked_transaction.m_prepare_next_retry_at()
        return locked_transaction.m_mark_warning(
            m_summary=_("Retry finished without a success signal"),
            m_message=_("The retry handler returned without confirming a successful outcome."),
        )

    def m_collect_extension_health_issues(self):
        self.ensure_one()
        return []

    def m_run_health_check(self):
        for transaction in self:
            issues = transaction.m_collect_base_health_issues() + transaction.m_collect_extension_health_issues()
            issue_message = "\n".join(issues)
            transaction.with_context(m_intercompany_internal_write=True).write(
                {"m_last_health_check_at": fields.Datetime.now()}
            )
            if issues:
                if issue_message != (transaction.m_last_error_message or "") or transaction.m_health_state == "healthy":
                    transaction.m_mark_warning(
                        m_summary=_("Health check detected an issue"),
                        m_message=issue_message,
                    )
                continue
            if transaction.m_health_state != "healthy" or transaction.m_last_error_message:
                transaction.m_mark_healthy(
                    m_summary=_("Health check passed"),
                    m_message=_("The base health checks passed successfully."),
                )
        return True

    @api.model
    def m_cron_process_retry_batch(self, m_batch_size=50):
        domain = [
            ("m_state", "not in", ["done", "cancelled"]),
            ("m_next_retry_at", "<=", fields.Datetime.now()),
            ("m_rule_id.m_auto_retry", "=", True),
        ]
        transactions = self.search(domain, order="m_next_retry_at asc, id asc", limit=m_batch_size)
        locked_transactions = transactions.try_lock_for_update()
        processed = 0
        for transaction in locked_transactions:
            with self.env.cr.savepoint():
                try:
                    transaction.with_context(m_intercompany_retry_locked=True).m_execute_retry(
                        m_force_retry=False,
                        m_manager_note=_("Automatic retry"),
                        m_from_cron=True,
                    )
                except Exception as error:  # pylint: disable=broad-except
                    transaction.m_mark_failed(
                        m_summary=_("Automatic retry failed"),
                        m_message=_("The automatic retry worker hit an unexpected exception."),
                        m_technical_details=transaction.m_sanitize_exception_message(error),
                    )
                processed += 1
        return processed

    @api.model
    def m_cron_run_health_check_batch(self, m_batch_size=100):
        transactions = self.search(
            [("m_state", "not in", ["done", "cancelled"])],
            order="id asc",
            limit=m_batch_size,
        )
        locked_transactions = transactions.try_lock_for_update()
        processed = 0
        for transaction in locked_transactions:
            with self.env.cr.savepoint():
                transaction.m_run_health_check()
                processed += 1
        return processed

    def m_get_source_record(self):
        self.ensure_one()
        return self.m_get_document_record(
            self.m_source_model,
            self.m_source_res_id,
            self.m_source_company_id,
        )

    def m_get_destination_record(self):
        self.ensure_one()
        return self.m_get_document_record(
            self.m_destination_model,
            self.m_destination_res_id,
            self.m_destination_company_id,
        )

    def m_schedule_issue_activity(self, event):
        self.ensure_one()
        responsible_user = self.m_responsible_user_id or self.m_rule_id.m_responsible_user_id
        if not responsible_user:
            return False
        summary = self.m_get_issue_activity_summary(event)
        existing_activity = self.env["mail.activity"].search(
            [
                ("res_model", "=", self._name),
                ("res_id", "=", self.id),
                ("user_id", "=", responsible_user.id),
                ("summary", "=", summary),
                ("active", "=", True),
            ],
            limit=1,
        )
        if existing_activity:
            return existing_activity
        return self.activity_schedule(
            act_type_xmlid="mail.mail_activity_data_warning",
            user_id=responsible_user.id,
            summary=summary,
            note=event.m_message or event.m_summary,
            automated=True,
        )

    def m_close_issue_activities(self, event):
        self.ensure_one()
        summary = self.m_get_issue_activity_summary(event)
        activities = self.env["mail.activity"].search(
            [
                ("res_model", "=", self._name),
                ("res_id", "=", self.id),
                ("summary", "=", summary),
                ("active", "=", True),
            ]
        )
        if activities:
            activities.action_feedback(feedback=_("Intercompany issue resolved."))
        return activities

    def m_validate_manual_vals(self, vals_list, create_mode):
        if self.env.context.get("m_intercompany_internal_write") or self.env.su:
            return
        allowed_fields = {
            "m_rule_id",
            "m_source_company_id",
            "m_destination_company_id",
            "m_transaction_type",
            "m_reference",
            "m_source_model",
            "m_source_res_id",
            "m_destination_model",
            "m_destination_res_id",
            "m_responsible_user_id",
            "m_note",
            "m_idempotency_key",
        }
        if not create_mode:
            allowed_fields = {
                "m_reference",
                "m_source_model",
                "m_source_res_id",
                "m_destination_model",
                "m_destination_res_id",
                "m_responsible_user_id",
                "m_note",
            }
        for vals in vals_list:
            forbidden_fields = set(vals) - allowed_fields
            if forbidden_fields:
                raise AccessError(
                    _("Manual edits to technical synchronization fields are not allowed: %(fields)s",
                      fields=", ".join(sorted(forbidden_fields)))
                )

    def m_transition_state(self, target_state):
        for transaction in self:
            if transaction.m_state in {"done", "cancelled"} and target_state == "draft":
                raise UserError(_("Done or cancelled transactions cannot be reset to draft."))
            if transaction.m_state in {"done", "cancelled"} and target_state == "in_progress":
                raise UserError(_("Done or cancelled transactions cannot be restarted directly."))
            if transaction.m_state == target_state:
                continue
            if target_state == "in_progress" and transaction.m_state not in {"draft", "warning", "failed", "in_progress"}:
                raise UserError(_("This transaction cannot be moved to In Progress from its current state."))
            transaction.with_context(m_intercompany_internal_write=True).write({"m_state": target_state})

    def m_prepare_next_retry_at(self, m_next_retry_at=False):
        self.ensure_one()
        if self.m_rule_id.m_auto_retry and self.m_retry_count < self.m_rule_id.m_max_retry_count:
            next_retry_at = m_next_retry_at or fields.Datetime.add(
                fields.Datetime.now(),
                minutes=self.m_rule_id.m_retry_delay_minutes,
            )
            self.with_context(m_intercompany_internal_write=True).write({"m_next_retry_at": next_retry_at})
            return next_retry_at
        self.with_context(m_intercompany_internal_write=True).write({"m_next_retry_at": False})
        return False

    def m_get_document_record(self, model_name, res_id, company, m_bypass_access=False):
        self.ensure_one()
        if not model_name or not res_id:
            return False
        model = self.env.registry.get(model_name)
        if not model:
            return False
        recordset = self.env[model_name].with_context(allowed_company_ids=self.m_company_ids.ids)
        if company and "company_id" in recordset._fields:
            recordset = recordset.with_company(company)
        # sudo is limited here to existence/company validation, not user-facing data reads.
        record = (recordset.sudo() if m_bypass_access else recordset).browse(res_id).exists()
        if not record:
            return False
        if m_bypass_access:
            return record
        try:
            record.check_access("read")
        except AccessError:
            return False
        return record

    def m_get_document_fallback_label(self, model_name, res_id):
        if not model_name or not res_id:
            return False
        return _("%(model)s,%(res_id)s", model=model_name, res_id=res_id)

    def m_validate_document_link(self, model_name, res_id, expected_company, document_side_label):
        if bool(model_name) != bool(res_id):
            raise ValidationError(
                _("The %(document_side)s document link must define both a model and a record ID.", document_side=document_side_label)
            )
        if not model_name:
            return
        if not self.env.registry.get(model_name):
            raise ValidationError(
                _("The %(document_side)s model '%(model)s' does not exist.", document_side=document_side_label, model=model_name)
            )
        # sudo is used strictly to validate the linked record's existence and company
        # alignment without disclosing the record to unauthorized users.
        record = self.env[model_name].sudo().browse(res_id).exists()
        if not record:
            raise ValidationError(
                _("The %(document_side)s record %(model)s,%(res_id)s does not exist.", document_side=document_side_label, model=model_name, res_id=res_id)
            )
        if expected_company and "company_id" in record._fields and record.company_id and record.company_id != expected_company:
            raise ValidationError(
                _("The %(document_side)s record belongs to %(actual)s instead of %(expected)s.",
                  document_side=document_side_label,
                  actual=record.company_id.display_name,
                  expected=expected_company.display_name)
            )
        if expected_company and "company_ids" in record._fields and record.company_ids and expected_company not in record.company_ids:
            raise ValidationError(
                _("The %(document_side)s record is not shared with %(expected)s.",
                  document_side=document_side_label,
                  expected=expected_company.display_name)
            )

    def m_action_open_document(self, side):
        self.ensure_one()
        if side == "source":
            record = self.m_get_source_record()
            field_label = _("source")
        else:
            record = self.m_get_destination_record()
            field_label = _("destination")
        if not record:
            raise UserError(
                _("The %(side)s document is missing or you do not have access to it.", side=field_label)
            )
        return {
            "type": "ir.actions.act_window",
            "res_model": record._name,
            "res_id": record.id,
            "view_mode": "form",
            "target": "current",
            "context": {"allowed_company_ids": self.m_company_ids.ids},
        }

    def m_get_issue_activity_summary(self, event):
        self.ensure_one()
        return _(
            "Intercompany issue #%(event_id)s: %(summary)s",
            event_id=event.id,
            summary=event.m_summary,
        )

    def m_collect_base_health_issues(self):
        self.ensure_one()
        issues = []
        if self.m_rule_id and (
            self.m_source_company_id != self.m_rule_id.m_source_company_id
            or self.m_destination_company_id != self.m_rule_id.m_destination_company_id
        ):
            issues.append(_("Transaction companies no longer match the selected rule."))
        if self.m_source_company_id == self.m_destination_company_id:
            issues.append(_("Source and destination companies must remain distinct."))
        for model_name, res_id, company, label in [
            (self.m_source_model, self.m_source_res_id, self.m_source_company_id, _("source")),
            (self.m_destination_model, self.m_destination_res_id, self.m_destination_company_id, _("destination")),
        ]:
            if model_name and res_id and not self.m_get_document_record(
                model_name,
                res_id,
                company,
                m_bypass_access=True,
            ):
                issues.append(
                    _("The %(document_side)s linked record %(model)s,%(res_id)s is no longer available.",
                      document_side=label,
                      model=model_name,
                      res_id=res_id)
                )
        return issues

    def m_sanitize_exception_message(self, error):
        return _("%(error_type)s: %(message)s", error_type=type(error).__name__, message=str(error))
