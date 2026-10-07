import logging

from odoo import _, SUPERUSER_ID, api, fields, models
from odoo.exceptions import UserError
from odoo.modules.registry import Registry

_logger = logging.getLogger(__name__)


def _execute_post_process_item(db_name, post_process_id):
    with Registry(db_name).cursor() as cr:
        env = api.Environment(cr, SUPERUSER_ID, {})
        post_process = env["generic.sync.post.process"].browse(post_process_id)
        if not post_process.exists():
            return False
        try:
            post_process._execute_one()
        except Exception as exc:
            cr.commit()
            return str(exc)
        cr.commit()
        return False


class GenericSyncPostProcess(models.Model):
    _name = "generic.sync.post.process"
    _description = "Generic Sync Post Process"
    _order = "priority, id"
    _rec_name = "display_name"

    display_name = fields.Char(compute="_compute_display_name")
    priority = fields.Integer(default=10)
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("running", "Running"),
            ("done", "Done"),
            ("failed", "Failed"),
        ],
        default="pending",
        required=True,
        index=True,
    )
    type = fields.Selection(
        [
            ("create_record", "Create Missing Related Records"),
            ("update_translations", "Import Translations"),
        ],
        required=True,
    )
    job_id = fields.Many2one(
        "generic.sync.job",
        string="Owner Job",
        required=True,
        ondelete="cascade",
    )
    process_job_id = fields.Many2one(
        "generic.sync.job",
        string="Process Job",
        ondelete="set null",
        help="Optional helper job used to create missing related records.",
    )
    field_id = fields.Many2one(
        "generic.sync.field",
        string="Field Mapping",
        ondelete="set null",
    )
    res_ids = fields.Json(
        string="Process Record IDs",
        help="Source-side IDs handled by the process job or translation importer.",
        default=list,
    )
    source_model = fields.Char(
        string="Source Model",
        help="Source model of the owner record that triggered the queue item.",
    )
    source_record_id = fields.Char(
        string="Owner Source Record ID",
        help="Source ID of the main record that should be reprocessed after dependencies exist.",
    )
    error_message = fields.Text(readonly=True)
    attempt_count = fields.Integer(readonly=True)
    date_done = fields.Datetime(readonly=True)

    @api.depends("type", "job_id", "source_model", "source_record_id", "state")
    def _compute_display_name(self):
        labels = dict(self._fields["type"].selection)
        for rec in self:
            owner = rec.source_record_id or _("Batch")
            label = labels.get(rec.type, rec.type)
            rec.display_name = f"{label} - {rec.job_id.display_name} - {owner} [{rec.state}]"

    @api.model
    def _cron_run_pending_post_processes(self, limit=25):
        next_process = self.search([("state", "=", "pending")], order="priority, id", limit=1)
        while next_process:
            next_process.execute()
            self.env.cr.commit()
            next_process = self.search([("state", "=", "pending")], order="priority, id", limit=1)

    def action_run_now(self):
        self.with_context(raise_on_error=True).execute()

    def action_retry(self):
        self.write({
            "state": "pending",
            "error_message": False,
            "date_done": False,
        })

    def execute(self):
        pending_items = self.filtered(lambda rec: rec.state in ("pending", "failed"))
        if not pending_items:
            return

        errors = []
        db_name = self.env.cr.dbname

        for rec in pending_items:
            error_message = _execute_post_process_item(db_name, rec.id)
            if error_message:
                errors.append((rec.display_name, error_message))

        self.invalidate_recordset()

        if errors and self.env.context.get("raise_on_error"):
            raise UserError(_(
                "Some post-process items failed:\n%s"
            ) % "\n".join(
                f"{display_name}: {message}"
                for display_name, message in errors
            ))

    def _execute_one(self):
        self.ensure_one()
        self.write({
            "state": "running",
            "attempt_count": self.attempt_count + 1,
            "error_message": False,
        })
        try:
            if self.type == "create_record":
                self._execute_create_record()
            elif self.type == "update_translations":
                self._execute_update_translations()
        except Exception as exc:
            _logger.exception("Post-process %s failed", self.display_name)
            self.write({
                "state": "failed",
                "error_message": str(exc),
            })
            raise
        else:
            self.write({
                "state": "done",
                "date_done": fields.Datetime.now(),
            })

    def _normalize_ids(self, ids):
        unique_ids = []
        seen = set()
        for value in ids or []:
            if value in (False, None, ""):
                continue
            try:
                normalized = int(value)
            except (TypeError, ValueError):
                normalized = value
            if normalized in seen:
                continue
            seen.add(normalized)
            unique_ids.append(normalized)
        return unique_ids

    def _run_job_copy(self, job, domain):
        self.ensure_one()
        copied_job = job.copy({
            "active": False,
            "auto_sync": False,
        })
        try:
            copied_job.write({
                "domain": domain,
                "last_source_id": 0,
            })
            copied_job.with_context(skip_auto_commit=True, post_process_id=self).action_run_manual_sync()
        except Exception:
            copied_job.record_mapping_ids.update({"job_id": job.id})
            copied_job.post_process_ids.update({"job_id": job.id})
            raise
        else:
            copied_job.record_mapping_ids.update({"job_id": job.id})
            copied_job.post_process_ids.update({"job_id": job.id})
            copied_job.unlink()

    def _rerun_owner_record(self):
        self.ensure_one()
        if not self.source_record_id:
            return
        try:
            source_record_id = int(self.source_record_id)
        except (TypeError, ValueError):
            _logger.warning(
                "Skipping owner rerun for post-process %s: invalid source_record_id=%s",
                self.id,
                self.source_record_id,
            )
            return
        self._run_link_missing_records()

    def _get_owner_target_record(self):
        self.ensure_one()
        if not self.source_record_id:
            return self.env[self.job_id.target_model]

        owner_mapping = self.job_id._find_existing_mapping({
            "id": int(self.source_record_id),
        })
        if not owner_mapping or not owner_mapping.target_record_id:
            return self.env[self.job_id.target_model]

        return self.env[owner_mapping.target_model].browse(
            owner_mapping.target_record_id
        ).exists()

    def _run_link_missing_records(self):
        self.ensure_one()

        if not self.process_job_id or not self.source_record_id or not self.field_id:
            return

        res_ids = self._normalize_ids(self.res_ids)
        if not res_ids:
            return

        mappings = self.env["generic.sync.record.map"]
        for res_id in res_ids:
            mappings |= self.process_job_id._find_existing_mapping({'id': res_id})

        local_ids = []
        for mapping in mappings:
            local_rec = self.env[mapping.target_model].browse(mapping.target_record_id)
            if local_rec.exists():
                local_ids.append(local_rec.id)
        owner_record = self._get_owner_target_record()
        if not owner_record:
            return

        field = owner_record._fields.get(self.field_id.target_field)
        if not field:
            return

        if field.type in ("one2many", "many2many"):
            value = [(6, 0, local_ids)]
        elif field.type == "many2one":
            value = local_ids[0] if local_ids else False
        else:
            return

        self.job_id._with_sync_context(owner_record).write({
            self.field_id.target_field: value,
        })

    def _execute_create_record(self):
        self.ensure_one()
        if not self.process_job_id:
            return

        res_ids = self._normalize_ids(self.res_ids)
        if not res_ids:
            return

        if self.process_job_id.target_model == 'mail.message':
            domain = ['|', ('id', 'in', res_ids), '&', ('id', 'in', res_ids), ('tracking_value_ids', '!=', False)]
            self._run_job_copy(self.process_job_id, domain)
        else:
            self._run_job_copy(self.process_job_id, [("id", "in", res_ids)])
        self._rerun_owner_record()

    def _execute_update_translations(self):
        self.ensure_one()
        job = self.job_id
        translated_fields = job._get_translatable_fields()
        if not translated_fields:
            return

        source_ids = self._normalize_ids(self.res_ids)
        if not source_ids:
            return

        uid, proxy = job.backend_id.get_connection()
        source_model = self.source_model or job.source_model or job.target_model
        languages = job._get_source_language_codes(proxy=proxy, uid=uid)
        if not languages:
            return

        mappings = self.env["generic.sync.record.map"].search([
            ("source_model", "=", source_model),
            ("source_record_id", "in", [str(source_id) for source_id in source_ids]),
            ("active", "=", True),
        ])
        mapping_by_source = {
            str(mapping.source_record_id): mapping
            for mapping in mappings
            if mapping.target_record_id
        }

        for lang_code in languages:
            records = proxy.execute_kw(
                job.backend_id.db_name,
                uid,
                job.backend_id.password,
                source_model,
                "read",
                [source_ids],
                {
                    "fields": translated_fields,
                    "context": {"lang": lang_code},
                },
            )

            for source_record in records:
                mapping = mapping_by_source.get(str(source_record.get("id")))
                if not mapping:
                    continue
                target_record = self.env[mapping.target_model].browse(mapping.target_record_id)
                if not target_record.exists():
                    continue
                values = {
                    field_name: source_record.get(field_name)
                    for field_name in translated_fields
                    if source_record.get(field_name)
                }
                if values:
                    job._with_sync_context(
                        target_record.with_context(lang=lang_code)
                    ).write(values)
