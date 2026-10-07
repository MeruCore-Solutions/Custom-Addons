import base64
from xmlrpc.client import Binary
from ast import literal_eval
from datetime import timedelta, datetime, date, time
import time as pytime
import logging

from dateutil.relativedelta import relativedelta

from odoo import _, api, Command, fields, models, SUPERUSER_ID
from odoo.exceptions import MissingError, UserError
from odoo.tools import float_compare
from odoo.tools.safe_eval import safe_eval, wrap_module, pytz

_logger = logging.getLogger(__name__)

FIELD_TYPE_COMPATIBILITY = {
    "char": ["char", "text"],
    "text": ["char", "text"],
    "monetary": ["monetary"],
    "integer": ["integer"],
    "float": ["float", "monetary"],
    "boolean": ["boolean"],
    "date": ["date"],
    "datetime": ["datetime"],
    "selection": ["selection"],
    "binary": ["binary"]
}


class GenericSyncJob(models.Model):
    _name = "generic.sync.job"
    _description = "Generic Sync Job"
    _order = "sequence, id"

    # -------------------------------------------------------------------------
    # Fields
    # -------------------------------------------------------------------------
    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)

    backend_id = fields.Many2one(
        "generic.sync.backend",
        required=True,
    )

    model_id = fields.Many2one(
        "ir.model",
        string="Target Model",
        required=True,
        ondelete="cascade",
    )

    target_model = fields.Char(
        related="model_id.model",
        store=True,
        readonly=True,
    )

    source_model = fields.Char(
        help="Remote model name. If empty, target model is used.",
    )

    domain = fields.Char(
        help="Optional domain in python syntax, e.g. [('active','=',True)]",
    )

    batch_size = fields.Integer(
        default=500,
        help="Number of records processed per batch. "
             "Set to 0 or negative to disable batching.",
    )
    last_source_id = fields.Integer(
        default=0,
        help="Start from Source Id. ",
    )
    import_translation = fields.Boolean(default=True)
    translation_post_process = fields.Boolean(
        string="Post-Process Translations",
        default=False,
        help=(
            "Queue translation import after the main sync. This keeps the main "
            "record import faster and applies translations in batches later."
        ),
    )
    import_chatter = fields.Boolean(default=True)

    field_ids = fields.One2many(
        comodel_name="generic.sync.field",
        inverse_name="job_id",
        string="Field Mappings",
        copy=True,
    )

    auto_sync = fields.Boolean(default=False)

    sync_interval_unit = fields.Selection(
        [
            ("minute", "Minute"),
            ("hour", "Hour"),
            ("day", "Day"),
            ("week", "Week"),
            ("month", "Month"),
            ("year", "Year"),
        ],
        default="month",
        required=True,
    )

    sync_interval_number = fields.Integer(default=1, required=True)

    next_execution_datetime = fields.Datetime()
    last_run_datetime = fields.Datetime(readonly=True)
    last_message = fields.Text(readonly=True)

    post_process_python = fields.Text(
        string="Before Write Python Hook",
        default=(
            "# Executed after field mappings and before record write.\n"
            "#\n"
            "# Available variables:\n"
            "# - source_vals: raw source record (dict)\n"
            "# - result_vals: mapped values (dict, mutable)\n"
            "# - env: Odoo env\n"
            "# - job: current Generic Sync Job\n"
            "# - datetime, date, time, timezone, relativedelta\n"
            "# - float_compare, UserError, Command\n"
            "# - log(message, level='info'), _logger\n"
            "#\n"
            "# The expression MUST update result_vals in-place.\n"
        )
    )

    record_mapping_ids = fields.One2many(
        comodel_name="generic.sync.record.map",
        inverse_name="job_id",
        string="Record Mappings",
    )
    post_process_ids = fields.One2many(
        comodel_name="generic.sync.post.process",
        inverse_name="job_id",
        string="Post Processes",
        copy=False,
    )

    record_mapping_count = fields.Integer(
        compute="_compute_record_mapping_count",
        string="Record Mappings",
    )
    post_process_count = fields.Integer(
        compute="_compute_post_process_count",
        string="Post Processes",
    )
    pending_post_process_count = fields.Integer(
        compute="_compute_post_process_count",
        string="Pending Post Processes",
    )
    temp_last_batch = fields.Integer()

    @api.depends('record_mapping_ids')
    def _compute_record_mapping_count(self):
        for job in self:
            job.record_mapping_count = len(job.record_mapping_ids)

    @api.depends("post_process_ids", "post_process_ids.state")
    def _compute_post_process_count(self):
        for job in self:
            job.post_process_count = len(job.post_process_ids)
            job.pending_post_process_count = len(
                job.post_process_ids.filtered(lambda p: p.state == "pending")
            )

    def _get_sync_context(self):
        return {
            "tracking_disable": True,
            "mail_create_nolog": True,
            "mail_create_nosubscribe": True,
            "mail_notrack": True,
            "mail_notify_force_send": False,
            "skip_compute_price_unit": True,
            "skip_procurement": True,
        }

    def safe_create(self, model, vals, delay=0.5):
        try:
            return model.create(vals)
        except:
            pytime.sleep(delay)
            return self.safe_create(model, vals)

    def safe_update(self, model, vals, delay=0.5):
        try:
            return model.update(vals)
        except:
            pytime.sleep(delay)
            return self.safe_update(model, vals)

    def _with_sync_context(self, recordset):
        return recordset.with_context(**self._get_sync_context())

    def _get_table_columns(self, table_name):
        self.env.cr.execute(
            """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = %s
            """,
            [table_name],
        )
        return {row[0] for row in self.env.cr.fetchall()}

    def _get_field_mapping_read_fields(self):
        FieldMapping = self.env["generic.sync.field"]
        db_columns = self._get_table_columns(FieldMapping._table)
        requested_fields = [
            "sequence",
            "source_field",
            "target_field",
            "transform",
            "python_expr",
            "required",
            "missing_m2o_policy",
            "create_job_id",
            "post_process",
            "post_process_priority",
        ]
        read_fields = []
        skipped_fields = []

        for field_name in requested_fields:
            field = FieldMapping._fields.get(field_name)
            if field and field.column_type and field_name not in db_columns:
                skipped_fields.append(field_name)
                continue
            read_fields.append(field_name)

        if skipped_fields:
            _logger.warning(
                "Sync job field mapping preload skipped missing DB columns: %s",
                ", ".join(skipped_fields),
            )

        return read_fields

    def _get_field_mapping_post_process_priority(self, field_mapping):
        if not field_mapping:
            return False
        if "post_process_priority" not in self._get_table_columns("generic_sync_field"):
            return False
        return field_mapping.post_process_priority

    def _get_live_field_mappings(self):
        """
        Return a cached snapshot of current field mappings for this job.

        Sync jobs may overlap with admin edits to generic.sync.field. Reading
        self.field_ids lazily can then crash with MissingError if a mapping row
        disappears between browse and fetch. This helper reloads the current
        rows from the database and primes the cache once for the whole run.
        """
        self.ensure_one()
        FieldMapping = self.env["generic.sync.field"]
        domain = [("job_id", "=", self.id)]
        fields_to_read = self._get_field_mapping_read_fields()
        last_error = None

        for attempt in range(2):
            mappings = FieldMapping.search(
                domain,
                order="sequence, id",
            ).exists()
            if not mappings:
                return mappings
            try:
                with self.env.cr.savepoint():
                    mappings.read(fields_to_read)
                return mappings
            except MissingError:
                if attempt:
                    raise
                _logger.warning(
                    "Sync job '%s': field mappings changed during execution; "
                    "reloading live mappings",
                    self.name,
                )
            except Exception as exc:
                last_error = exc
                _logger.warning(
                    "Sync job '%s': bulk field mapping preload failed; "
                    "falling back to per-record reload. Error: %s",
                    self.name,
                    exc,
                )
                break

        valid_ids = []
        for mapping_id in FieldMapping.search(domain, order="sequence, id").ids:
            mapping = FieldMapping.browse(mapping_id).exists()
            if not mapping:
                continue
            try:
                with self.env.cr.savepoint():
                    mapping.read(fields_to_read)
                valid_ids.append(mapping.id)
            except Exception as exc:
                _logger.warning(
                    "Sync job '%s': skipping unreadable field mapping ID %s. "
                    "Error: %s",
                    self.name,
                    mapping_id,
                    exc,
                )

        if valid_ids:
            return FieldMapping.browse(valid_ids)
        if last_error:
            raise last_error
        return FieldMapping.browse()

    # -------------------------------------------------------------------------
    # Scheduling helpers
    # -------------------------------------------------------------------------
    def _get_interval_delta(self):
        """Return a timedelta/relativedelta based on the job's sync configuration."""
        self.ensure_one()
        n = self.sync_interval_number or 1
        unit = self.sync_interval_unit

        if unit == "minute":
            return timedelta(minutes=n)
        if unit == "hour":
            return timedelta(hours=n)
        if unit == "day":
            return timedelta(days=n)
        if unit == "week":
            return timedelta(weeks=n)
        if unit == "month":
            return relativedelta(months=n)
        if unit == "year":
            return relativedelta(years=n)
        # Fallback
        return timedelta(hours=1)

    def _update_next_execution(self, from_dt=None):
        """Compute and store next_execution_datetime for each job."""
        for job in self:
            base = from_dt or fields.Datetime.now()
            job.next_execution_datetime = base + job._get_interval_delta()

    @api.model
    def create(self, vals):
        job = super().create(vals)
        if not job.next_execution_datetime:
            job._update_next_execution()
        return job

    def write(self, vals):
        res = super().write(vals)
        if {"sync_interval_unit", "sync_interval_number", "auto_sync"} & set(vals):
            for job in self:
                job._update_next_execution()
        return res

    # -------------------------------------------------------------------------
    # Entry points
    # -------------------------------------------------------------------------
    @api.model
    def _cron_run_due_jobs(self):
        """Cron entry point: run all due jobs."""
        now = fields.Datetime.now()
        jobs = self.search([
            ("active", "=", True),
            ("auto_sync", "=", True),
            ("next_execution_datetime", "<=", now),
        ])
        for job in jobs:
            job._run_sync_job()

    def action_run_manual_sync(self):
        """Manual button to run sync immediately."""
        self.with_context(raise_on_error=True)._run_sync_job()

    def _run_sync_job(self):
        """Run the sync for each job in the recordset."""
        for job in self:
            if not job.backend_id:
                raise UserError(_("Backend required for job %s") % job.name)
            job._do_sync()
            job.last_run_datetime = fields.Datetime.now()
            job._update_next_execution(from_dt=job.last_run_datetime)
            job.last_message = _("Sync completed successfully.")

    def _get_source_language_codes(self, proxy=None, uid=None):
        self.ensure_one()
        cached_lang_codes = self.env.context.get("source_lang_codes")
        if cached_lang_codes is not None:
            return cached_lang_codes

        if uid is None or proxy is None:
            uid, proxy = self.backend_id.get_connection()

        languages = proxy.execute_kw(
            self.backend_id.db_name,
            uid,
            self.backend_id.password,
            "res.lang",
            "search_read",
            [[("active", "=", True)]],
            {"fields": ["code"]},
        )
        return [lang["code"] for lang in languages if lang["code"] != "en_US"]

    def _queue_post_process(
        self,
        process_type,
        res_ids=None,
        process_job=None,
        field=None,
        source_model=None,
        source_record_id=None,
    ):
        self.ensure_one()
        PostProcess = self.env["generic.sync.post.process"]

        clean_ids = []
        seen = set()
        for value in res_ids or []:
            if value in (False, None, ""):
                continue
            try:
                normalized = int(value)
            except (TypeError, ValueError):
                normalized = value
            if normalized in seen:
                continue
            seen.add(normalized)
            clean_ids.append(normalized)

        source_record_value = False
        if source_record_id not in (False, None, ""):
            source_record_value = str(source_record_id)

        domain = [
            ("job_id", "=", self.id),
            ("type", "=", process_type),
            ("state", "=", "pending"),
            ("source_model", "=", source_model or False),
            ("source_record_id", "=", source_record_value or False),
            ("process_job_id", "=", process_job.id if process_job else False),
            ("field_id", "=", field.id if field else False),
        ]
        queue_item = PostProcess.search(domain, limit=1)

        if queue_item:
            existing_ids = queue_item.res_ids or []
            merged_ids = []
            merged_seen = set()
            for value in existing_ids + clean_ids:
                key = str(value)
                if key in merged_seen:
                    continue
                merged_seen.add(key)
                merged_ids.append(value)
            queue_item.write({"res_ids": merged_ids})
            return queue_item

        return PostProcess.create({
            "job_id": self.id,
            "type": process_type,
            "process_job_id": process_job.id if process_job else False,
            "field_id": field.id if field else False,
            "priority": self._get_field_mapping_post_process_priority(field),
            "source_model": source_model,
            "source_record_id": source_record_value,
            "res_ids": clean_ids,
        })

    # -------------------------------------------------------------------------
    # Core sync logic
    # -------------------------------------------------------------------------
    def _do_sync(self):
        self.ensure_one()

        uid, proxy = self.backend_id.get_connection()
        source_model = self.source_model or self.target_model
        field_mappings = self._get_live_field_mappings()

        domain = literal_eval(self.domain) if self.domain else []

        # -------------------------------------------------
        # source Languages fetch
        # -------------------------------------------------
        lang_codes = self._get_source_language_codes(proxy=proxy, uid=uid)
        self = self.with_context(source_lang_codes=lang_codes)

        # -------------------------------------------------
        # Build source fields safely
        # -------------------------------------------------
        source_fields = {"id"}
        for mapping in field_mappings:
            field_name = self._get_effective_image_source_field(
                self.source_model or self.target_model,
                mapping.source_field,
            )
            source_fields.add(field_name)

        target_model = self.env[self.target_model]
        if target_model._name == "ir.attachment":
            source_fields.add("res_id")
            source_fields.add("res_model")

        # 🔧 REQUIRED: always read variant attributes
        if target_model._name == "product.product":
            source_fields.add("product_template_attribute_value_ids")
            source_fields.add("product_tmpl_id")

        source_fields = list(source_fields)

        batch_size = self.batch_size if self.batch_size and self.batch_size > 0 else 500

        parent_fields = self._get_self_parent_fields()
        base_mappings = field_mappings.filtered(
            lambda m: m.target_field not in parent_fields
        )
        parent_mappings = field_mappings.filtered(
            lambda m: m.target_field in parent_fields
        )

        # -------------------------------------------------
        # Resume-safe cursor (pure ID-based)
        # -------------------------------------------------
        last_source_id = self.last_source_id
        batch_no = 1

        # -------------------------------------------------
        # MAIN LOOP — ID-based batching
        # -------------------------------------------------
        while True:
            batch_domain = list(domain) + [("id", ">", last_source_id)]

            batch_ids = proxy.execute_kw(
                self.backend_id.db_name,
                uid,
                self.backend_id.password,
                source_model,
                "search",
                [batch_domain],
                {
                    "order": "id ASC",
                    "limit": batch_size,
                },
            )

            if not batch_ids:
                _logger.info(
                    "Sync job '%s': no more records after ID %s",
                    self.name,
                    last_source_id,
                )
                break
            else:
                _logger.info(
                    "Sync job '%s': Redord Being  ID %s",
                    self.name,
                    last_source_id,
                )

            batch_start = pytime.time()

            records = proxy.execute_kw(
                self.backend_id.db_name,
                uid,
                self.backend_id.password,
                source_model,
                "read",
                [batch_ids],
                {"fields": source_fields},
            )
            _logger.info(
                "Sync job '%s': Redord Being Processed ID %s",
                self.name,
                (str([len(records), batch_ids])),
            )

            # Prefetch variant attributes ONCE per batch
            if target_model._name == "product.product":
                self = self._prefetch_variant_attributes(records, proxy)

            # -------------------------
            # PASS 1 — base fields
            # -------------------------
            for rec in records:
                self.last_source_id = last_source_id = rec["id"]

                vals = self._map_record_values(rec, base_mappings)
                vals = self._post_process_values(rec, vals)

                if self._has_missing_required_fields(rec, base_mappings, vals):
                    _logger.info(
                        "Skipping record %s %s due to missing required fields",
                        (self.target_model, rec.get("id")),
                    )
                    continue

                if vals and not vals.get("skip_sync"):
                    if target_model._name == "product.product":
                        self._upsert_product_variant(vals, rec, proxy)
                    else:
                        self._upsert_record(target_model, vals, rec)

            # -------------------------
            # PASS 2..N — hierarchy
            # -------------------------
            if parent_mappings:
                max_passes = 10
                for _ in range(max_passes):
                    unresolved = 0

                    for rec in records:
                        record = self._find_existing_record(rec)
                        if not record:
                            continue

                        vals = self._map_record_values(rec, parent_mappings)
                        if not vals:
                            continue

                        write_vals = {}
                        for field_name, val in vals.items():
                            if not val:
                                unresolved += 1
                                continue
                            if record[field_name].id != val:
                                write_vals[field_name] = val

                        if write_vals:
                            self._with_sync_context(record).write(write_vals)

                    if unresolved == 0:
                        break

            # -------------------------------------------------
            # Commit batch
            # -------------------------------------------------
            if not self.env.context.get('skip_auto_commit'):
                self.env.cr.commit()

            _logger.info(
                "Sync job '%s': batch %s done (up to source ID %s) in %.2fs",
                self.name,
                batch_no,
                last_source_id,
                pytime.time() - batch_start,
            )

            batch_no += 1

    # -------------------------------------------------------------------------
    # Auto field mapping helpers
    # -------------------------------------------------------------------------
    def _has_missing_required_fields(self, rec, mappings, vals):
        """
        Return True if any required mapping has no usable value.
        """
        model = self.env[self.target_model]

        for mapping in mappings:
            field = model._fields.get(mapping.target_field)
            if not field:
                continue

            required_mapping = mapping.required
            required_target_m2o = field.required and field.type == "many2one"
            if not required_mapping and not required_target_m2o:
                continue

            source_field = self._get_effective_image_source_field(
                self.source_model or self.target_model,
                mapping.source_field,
            )

            source_val = rec.get(source_field)

            # 1️⃣ Missing in source
            if not source_val:
                return True

            # 2️⃣ Mapping result missing
            if mapping.target_field not in vals:
                return True

            # 3️⃣ Explicit False from mapping (e.g. missing required M2O)
            if vals.get(mapping.target_field) is False:
                return True

        return False

    def _process_binary_and_attachment_values(self, source_vals, result_vals):
        """
        Normalize binary values and handle attachment binaries.

        - Converts XML-RPC Binary / bytes → base64 string
        - Downloads attachment binary via HTTP when target model = ir.attachment
        - Mutates result_vals in-place

        This function is SAFE to call multiple times.
        """
        self.ensure_one()

        # ------------------------------------------------------------
        # 1) Normalize binary fields for ALL models
        # ------------------------------------------------------------
        for field_name, value in list(result_vals.items()):
            # XML-RPC Binary
            if isinstance(value, Binary):
                result_vals[field_name] = base64.b64encode(
                    value.data
                ).decode("ascii")

            # Raw bytes
            elif isinstance(value, (bytes, bytearray)):
                result_vals[field_name] = base64.b64encode(
                    value
                ).decode("ascii")

        # ------------------------------------------------------------
        # 2) Handle ir.attachment binary content (SPECIAL CASE)
        # ------------------------------------------------------------
        if self.target_model == "ir.attachment" and not result_vals.get('res_id') and \
                result_vals.get('res_model') and source_vals.get('res_id'):
            map_res_id = self.env['generic.sync.record.map'].search([
                ('source_model', '=', source_vals.get('res_model')),
                ('source_record_id', '=', source_vals.get('res_id')),
            ], limit=1)
            if map_res_id and map_res_id.target_record_id:
                result_vals['res_id'] = map_res_id.target_record_id
            else:
                result_vals['skip_sync'] = True

        return result_vals

    def _get_remote_stored_fields(self, proxy, uid, source_model):
        """Fetch stored fields from remote model via XML-RPC."""
        fields_info = proxy.execute_kw(
            self.backend_id.db_name,
            uid,
            self.backend_id.password,
            source_model,
            "fields_get",
            [],
            {"attributes": ["type", "store", "relation", "selection"]},
        )

        return {
            name: info
            for name, info in fields_info.items()
            if info.get("store", False)
               and name not in ("id", "__last_update")
        }

    def _get_local_stored_fields(self):
        """Fetch stored, non-computed fields from local target model."""
        model = self.env[self.target_model]
        return {
            name: field
            for name, field in model._fields.items()
            if field.store
               and name not in ("id", "__last_update")
        }

    def _detect_transform(self, source_field, source, target):
        """Decide which transform to use for a given source/target field pair."""
        _ = source_field  # unused but kept for API clarity
        src_type = source.get("type")
        tgt_type = target.type

        # X2Many via mapping table
        if src_type in ("one2many", "many2many") and tgt_type == src_type:
            return "x2many_map"

        # Self-referencing hierarchy (many2one to same model)
        if (
                src_type == "many2one"
                and tgt_type == "many2one"
                and source.get("relation") == self.target_model
                and target.comodel_name == self.target_model
        ):
            return "m2o_self_hierarchy"

        # Simple copy-compatible types
        if src_type in FIELD_TYPE_COMPATIBILITY:
            if tgt_type in FIELD_TYPE_COMPATIBILITY[src_type]:
                return "copy"

        # Generic many2one -> many2one name-based mapping
        if src_type == "many2one" and tgt_type == "many2one":
            return "m2o_name"

        return False

    def action_generate_field_mappings(self):
        """Auto-generate generic.sync.field records based on schema matching."""
        self.ensure_one()

        if not self.target_model:
            raise UserError(_("Please select a target model first."))

        if not self.backend_id:
            raise UserError(_("Please configure a backend on the job first."))

        uid, proxy = self.backend_id.get_connection()
        source_model = self.source_model or self.target_model

        remote_fields = self._get_remote_stored_fields(proxy, uid, source_model)
        local_fields = self._get_local_stored_fields()
        field_mappings = self._get_live_field_mappings()

        existing_pairs = set(
            (f.source_field, f.target_field) for f in field_mappings
        )

        FieldMapping = self.env["generic.sync.field"]
        created = 0
        for name, src in remote_fields.items():
            if name not in local_fields:
                continue

            target_field = local_fields[name]
            pair = (name, name)
            if pair in existing_pairs:
                continue

            transform = self._detect_transform(
                source_field=name,
                source=src,
                target=target_field,
            )
            if not transform:
                continue

            FieldMapping.sudo().create({
                "job_id": self.id,
                "source_field": name,
                "target_field": name,
                "transform": transform,
            })
            created += 1

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "message": _("%s field mappings generated.") % created,
                "type": "success" if created else "warning",
                "sticky": False,
                "next": {
                    "type": "ir.actions.client",
                    "tag": "soft_reload",
                },
            },
        }

    # -------------------------------------------------------------------------
    # Mapping helpers
    # -------------------------------------------------------------------------
    def _get_self_parent_fields(self):
        """Return many2one fields that point to the same model (self hierarchy)."""
        self.ensure_one()
        model = self.env[self.target_model]
        return [
            name
            for name, field in model._fields.items()
            if field.type == "many2one" and field.comodel_name == self.target_model
        ]

    def _map_record_values(self, src, mappings):
        """Apply field mappings to a single source record."""
        vals = {}
        model = self.env[self.target_model]

        for mapping in mappings:
            source_field = self._get_effective_image_source_field(
                self.source_model or self.target_model,
                mapping.source_field,
            )

            value = src.get(source_field)
            field = model._fields.get(mapping.target_field)

            if not field:
                continue

            if mapping.transform in ["copy", "binary"]:
                if self._is_image_field(model._name, mapping.target_field):
                    if value:
                        vals[mapping.target_field] = value
                else:
                    vals[mapping.target_field] = value

            elif mapping.transform == "m2o_self_hierarchy":
                vals[mapping.target_field] = self._map_self_parent(mapping, value, src=src)

            elif mapping.transform == "m2o_name":
                vals[mapping.target_field] = self._map_m2o(model, mapping, value, src=src)

            elif (
                    mapping.transform == "x2many_map"
                    and field.type in ("one2many", "many2many")
            ):
                mapped_value = self._map_x2many_by_mapping(mapping, field, value, src=src)
                if mapped_value is not False:
                    vals[mapping.target_field] = mapped_value

        vals = self._process_binary_and_attachment_values(src, vals)
        return vals

    def _map_m2o(self, model, mapping, value, src=None):
        """
        Resolve many2one in this order:
        1) mapping table (by remote ID)
        2) name-based lookup
        3) missing_m2o_policy
        """
        if not value or not isinstance(value, (list, tuple)):
            return False

        remote_id = str(value[0])
        name = value[1]

        comodel_name = model._fields[mapping.target_field].comodel_name
        comodel = self.env[comodel_name]

        # 1) mapping table
        rec_map = self.env["generic.sync.record.map"].search([
            ("source_model", "=", comodel_name),
            ("source_record_id", "=", remote_id),
            ("active", "=", True),
        ], limit=1)

        if rec_map and rec_map.target_record_id:
            rec = self.env[rec_map.target_model].browse(rec_map.target_record_id)
            if rec.exists():
                return rec.id

        # 2) fallback to name-based lookup
        if name and "name" in comodel._fields:
            rec = comodel.search([("name", "=", name)], limit=1)
            if rec:
                return rec.id
            else:
                rec = comodel.with_context(active_test=False).search([("name", "=", name)], limit=1)
                if rec:
                    return rec.id

        # 3) apply policy
        return self._handle_missing_m2o(
            mapping=mapping,
            model=model,
            value=value,
            src=src,
        )

    def _map_x2many_by_mapping(self, mapping, field, value, src=None):
        """
        Resolve one2many / many2many using generic.sync.record.map
        and apply per-field missing_m2o_policy.
        """
        if not value:
            return False

        if not isinstance(value, (list, tuple)):
            return False

        remote_ids = [v for v in value if v]
        if not remote_ids:
            return False

        Mapping = self.env["generic.sync.record.map"]
        local_ids = []
        missing = []

        for remote_id in remote_ids:
            rec_map = Mapping.search([
                ("source_model", "=", field.comodel_name),
                ("source_record_id", "=", str(remote_id)),
                ("active", "=", True),
            ], limit=1)

            if rec_map and rec_map.target_record_id:
                local_rec = self.env[rec_map.target_model].browse(
                    rec_map.target_record_id
                )
                if local_rec.exists():
                    local_ids.append(local_rec.id)
                else:
                    missing.append(remote_id)
            else:
                missing.append(remote_id)

        if missing:
            policy = mapping.missing_m2o_policy

            if policy == "stop":
                raise UserError(_(
                    "Missing related records for x2many field '%s'. "
                    "Remote IDs: %s"
                ) % (mapping.target_field, missing))
            # policy == 'skip' → ignore missing
            if policy == "create" and mapping.create_job_id:
                if mapping.post_process:
                    self._queue_post_process(
                        process_type="create_record",
                        res_ids=missing,
                        process_job=mapping.create_job_id,
                        field=mapping,
                        source_model=self.source_model or self.target_model,
                        source_record_id=src.get("id") if src else False,
                    )
                    if local_ids:
                        return [(5, 0, 0), (6, 0, local_ids)]
                    else:
                        return [(5, 0, 0)]
                sync_job = mapping.create_job_id
                if sync_job.target_model == 'mail.message' and self.import_chatter:
                    sync_job.write({'domain': ['|', ('id', 'in', missing), '&', ('id', 'in', missing), ('tracking_value_ids', '!=', False)], 'last_source_id': 0})
                else:
                    sync_job.write({'domain': [('id', 'in', missing)], 'last_source_id': 0})
                sync_job.action_run_manual_sync()
                mappings = self.env["generic.sync.record.map"]
                for missing_id in missing:
                    mappings |= sync_job._find_existing_mapping({'id': missing_id})
                for mapping in mappings:
                    local_rec = self.env[mapping.target_model].browse(mapping.target_record_id)
                    if local_rec.exists():
                        local_ids.append(local_rec.id)

            # policy == 'create' → intentionally blocked (no automatic create)
        if local_ids:
            return [(5,0,0), (6, 0, local_ids)]
        else:
            return [(5, 0, 0)]

    # -------------------------------------------------------------------------
    # Mapping-table based resolution (self hierarchy)
    # -------------------------------------------------------------------------
    def _map_self_parent(self, mapping, value, src=None):
        """Resolve self-referential many2one using mapping table."""
        if not value or not isinstance(value, (list, tuple)):
            return False

        source_parent_id = str(value[0])
        source_model = self.source_model or self.target_model

        rec_map = self.env["generic.sync.record.map"].search([
            ("source_model", "=", source_model),
            ("source_record_id", "=", source_parent_id),
            ("active", "=", True),
        ], limit=1)

        if rec_map and rec_map.target_record_id:
            parent_rec = self.env[rec_map.target_model].browse(
                rec_map.target_record_id
            )
            if parent_rec.exists():
                return parent_rec.id

        return self._handle_missing_m2o(
            mapping=mapping,
            model=self.env[self.target_model],
            value=value,
            src=src,
        )

    def _find_existing_mapping(self, src):
        """Find existing mapping row for a given source record (global, not per job)."""
        source_model = self.source_model or self.target_model
        source_record_id = str(src["id"])
        return self.env["generic.sync.record.map"].search([
            ("source_model", "=", source_model),
            ("source_record_id", "=", source_record_id),
            ("active", "=", True),
        ], limit=1)

    def _is_image_field(self, model_name, field_name):
        """
        Return True if the field is an Odoo image field (image_1920, image_1024, etc.).
        """
        field = self.env[model_name]._fields.get(field_name)
        return bool(
            field
            and field.type == "binary"
            and field_name.startswith("image_")
        )

    def _force_image_update(self, record, field_name, value):
        """
        Force update of Odoo image fields by fully invalidating cache
        and regenerating attachments.
        """
        if not record or not value:
            return

        # 1️⃣ Clear image with context
        self._with_sync_context(
            record.with_context(bin_size=False)
        ).write({field_name: False})

        # 2️⃣ Invalidate cache
        record.invalidate_recordset()

        # 3️⃣ Commit to force attachment cleanup
        self.env.cr.commit()

        # 4️⃣ Write image again
        self._with_sync_context(
            record.with_context(bin_size=False)
        ).write({field_name: value})

        # 5️⃣ Invalidate again to regenerate image sizes
        record.invalidate_recordset()

    def _get_effective_image_source_field(self, model_name, field_name):
        if field_name == "image_1920":
            return "image_1024"
        return field_name

    def _get_translatable_fields(self):
        model = self.env[self.target_model]
        if not self.import_translation:
            return []
        return [
            name
            for name, field in model._fields.items()
            if getattr(field, "translate", False)
               and field.store
               and field.type in ("char", "text")
        ]

    def _get_cached_source_languages(self):
        return self._get_source_language_codes()

    def _fetch_source_translations(self, proxy, uid, source_model, source_id, fields):
        translations = []
        languages = self._get_source_language_codes(proxy=proxy, uid=uid)

        for code in languages:

            records = proxy.execute_kw(
                self.backend_id.db_name,
                uid,
                self.backend_id.password,
                source_model,
                "read",
                [[source_id]],
                {
                    "fields": fields,
                    "context": {"lang": code},
                },
            )

            if not records:
                continue

            rec = records[0]
            for field in fields:
                value = rec.get(field)
                if value:
                    translations.append({
                        "name": f"{source_model},{field}",
                        "lang": code,
                        "value": value,
                    })

        return translations

    def _apply_translations(self, record, translations):
        if not translations:
            return

        per_lang_vals = {}

        for tr in translations:
            lang = tr["lang"]

            # extract field name from "model,field"
            field_name = tr["name"].split(",")[1]

            per_lang_vals.setdefault(lang, {})
            per_lang_vals[lang][field_name] = tr["value"]

        for lang, vals in per_lang_vals.items():
            self._with_sync_context(
                record.with_context(lang=lang)
            ).update(vals)

    def _upsert_record(self, model, vals, src):
        """
        Upsert target record based on mapping table:
        - If mapping + target exist → update
        - If mapping exists but target deleted → recreate and reuse mapping
        - If no mapping → create target + mapping
        + Sync translated fields (translate=True) from source v16
        """
        source_model = self.source_model or self.target_model
        source_record_id = str(src["id"])

        # ---------------------------------
        # Detect translated fields once
        # ---------------------------------
        translated_fields = self._get_translatable_fields()

        uid = proxy = None
        if translated_fields and not self.translation_post_process:
            uid, proxy = self.backend_id.get_connection()

        # ---------------------------------
        # 1️⃣ Existing record → UPDATE
        # ---------------------------------
        record = self._find_existing_record(src)

        if record:
            if vals:
                image_vals = {}
                normal_vals = {}

                for field_name, value in vals.items():
                    if self._is_image_field(model._name, field_name):
                        image_vals[field_name] = value
                    else:
                        normal_vals[field_name] = value

                if normal_vals:
                    self._with_sync_context(record).update(normal_vals)

                for field_name, value in image_vals.items():
                    if value:
                        self._force_image_update(record, field_name, value)

            # 🔥 Apply translations after update
            if translated_fields:
                if self.translation_post_process:
                    self._queue_post_process(
                        process_type="update_translations",
                        res_ids=[src["id"]],
                        source_model=source_model,
                    )
                else:
                    translations = self._fetch_source_translations(
                        proxy,
                        uid,
                        source_model,
                        src["id"],
                        translated_fields,
                    )
                    self._apply_translations(record, translations)

            return record

        # ---------------------------------
        # 2️⃣ Create record
        # ---------------------------------
        if model._name == "mail.message":
            record = self._create_mail_message(model, vals, src)
        else:
            record = self._with_sync_context(model.sudo()).create(vals or {})

        if not record:
            return False

        # ---------------------------------
        # 3️⃣ Create / reuse mapping
        # ---------------------------------
        self.env["generic.sync.record.map"].create({
            "job_id": self.id,
            "source_model": source_model,
            "source_record_id": source_record_id,
            "target_model": model._name,
            "target_record_id": record.id,
            "vals": vals
        })

        # ---------------------------------
        # 4️⃣ Apply translations after create
        # ---------------------------------
        if translated_fields:
            if self.translation_post_process:
                self._queue_post_process(
                    process_type="update_translations",
                    res_ids=[src["id"]],
                    source_model=source_model,
                )
            else:
                translations = self._fetch_source_translations(
                    proxy,
                    uid,
                    source_model,
                    src["id"],
                    translated_fields,
                )
                self._apply_translations(record, translations)

        return record

    def _create_mail_message(self, model, vals, src):
        """
        Create mail.message and map it using (model, res_id).
        """
        # 1️⃣ Resolve mapped target record
        target_model, target_res_id = self._resolve_mail_message_target(src)
        if not target_model or not target_res_id:
            _logger.info(
                "Skipping mail.message %s: target record not mapped yet",
                src.get("id"),
            )
            return False

        # 2️⃣ Force correct linkage
        vals.update({
            "model": target_model,
            "res_id": target_res_id,
        })

        # 3️⃣ Create message as SUPERUSER (mail.message ACL-safe)
        message = self._with_sync_context(
            model.sudo()
        ).create(vals)

        # 4️⃣ Create mapping using COMPOSITE identity
        self.env["generic.sync.record.map"].create({
            "job_id": self.id,
            "source_model": "mail.message",
            "source_record_id": f"{src.get('model')}:{src.get('res_id')}:{src.get('id')}",
            "target_model": "mail.message",
            "target_record_id": message.id,
        })

        return message

    def _resolve_mail_message_target(self, src):
        source_model_name = src.get("model")
        source_res_id = src.get("res_id")

        if not source_model_name or not source_res_id:
            return False, False

        rec_map = self.env["generic.sync.record.map"].search([
            ("source_model", "=", source_model_name),
            ("source_record_id", "=", str(source_res_id)),
            ("target_model", "=", source_model_name),
            ("active", "=", True),
        ], limit=1)

        if not rec_map:
            return False, False

        return rec_map.target_model, rec_map.target_record_id

    def _upsert_product_variant(self, vals, src, proxy):
        """
        Map product.product without creating variants.
        - Single-variant template → direct mapping
        - Multi-variant template → match by attribute values
        """

        # -------------------------------------------------
        # Guard: missing template
        # -------------------------------------------------
        tmpl = src.get("product_tmpl_id")
        if not tmpl:
            _logger.warning(
                "Source product %s has no product_tmpl_id, skipped",
                src.get("id"),
            )
            return False

        # -------------------------------------------------
        # 1️⃣ Mapping already exists → update only
        # -------------------------------------------------
        existing_map = self._find_existing_mapping(src)
        if existing_map:
            variant = self.env[existing_map.target_model].browse(
                existing_map.target_record_id
            ).exists()
            if variant and vals:
                safe_vals = self._filter_variant_write_vals(vals)
                self._update_variant_fields(variant, safe_vals)
            return variant

        # -------------------------------------------------
        # 2️⃣ Resolve target template via mapping
        # -------------------------------------------------
        tmpl_map = self.env["generic.sync.record.map"].search(
            [
                ("source_model", "=", "product.template"),
                ("source_record_id", "=", str(tmpl[0])),
                ("active", "=", True),
            ],
            limit=1,
        )

        if not tmpl_map:
            raise UserError(
                _("Product template not mapped for source product %s") % src["id"]
            )

        template = self.env["product.template"].browse(
            tmpl_map.target_record_id
        ).exists()

        if not template:
            return False

        variants = template.product_variant_ids

        # -------------------------------------------------
        # 3️⃣ Single variant shortcut
        # -------------------------------------------------
        if len(variants) == 1:
            variant = variants[0]

            if not self._find_existing_mapping(src):
                self._create_variant_mapping(src, variant)

            self._update_variant_fields(variant, vals)
            return variant

        # -------------------------------------------------
        # 4️⃣ Multi-variant → attribute matching
        # -------------------------------------------------
        source_attrs = self._get_source_variant_attributes(src)

        for variant in variants:
            target_attrs = {
                (ptav.attribute_id.name, ptav.product_attribute_value_id.name)
                for ptav in variant.product_template_attribute_value_ids
            }
            if target_attrs == source_attrs:
                if not self._find_existing_mapping(src):
                    self._create_variant_mapping(src, variant)

                self._update_variant_fields(variant, vals)
                return variant

        # -------------------------------------------------
        # 5️⃣ No match found → DO NOT CREATE
        # -------------------------------------------------
        _logger.warning(
            "No matching variant found for source product %s (template %s)",
            src["id"],
            template.display_name,
        )
        return False

    def _update_variant_fields(self, variant, vals):
        """
        Update variant fields using mapped values.
        Image fields handled safely.
        """
        vals = self._filter_variant_write_vals(vals)
        image_vals = {}
        normal_vals = {}

        for field_name, value in vals.items():
            if self._is_image_field(variant._name, field_name):
                image_vals[field_name] = value
            else:
                normal_vals[field_name] = value

        if normal_vals:
            self._with_sync_context(variant).update(normal_vals)

        for field_name, value in image_vals.items():
            if value:
                self._force_image_update(variant, field_name, value)

    def _get_source_variant_attributes(self, src):
        """
        Returns a comparable set of (attribute_name, value_name)
        Uses prefetched cache — NO XML-RPC here.
        """
        ptav_ids = src.get("product_template_attribute_value_ids") or []
        if not ptav_ids:
            return set()

        cache = self.env.context.get("ptav_cache", {})
        result = set()

        for ptav_id in ptav_ids:
            pair = cache.get(ptav_id)
            if pair:
                result.add(pair)

        return result

    def _prefetch_variant_attributes(self, records, proxy):
        ptav_ids = set()

        for rec in records:
            ptav_ids.update(rec.get("product_template_attribute_value_ids") or [])

        if not ptav_ids:
            return self

        uid, _ = self.backend_id.get_connection()

        ptav_records = proxy.execute_kw(
            self.backend_id.db_name,
            uid,
            self.backend_id.password,
            "product.template.attribute.value",
            "read",
            [list(ptav_ids)],
            {"fields": ["attribute_id", "name"]},
        )

        cache = {
            rec["id"]: (rec["attribute_id"][1], rec["name"])
            for rec in ptav_records
        }

        return self.with_context(ptav_cache=cache)

    def _create_variant_mapping(self, src, variant):
        self.env['generic.sync.record.map'].create({
            'job_id': self.id,
            'source_model': 'product.product',
            'source_record_id': str(src['id']),
            'target_model': 'product.product',
            'target_record_id': variant.id,
        })

    def _filter_variant_write_vals(self, vals):
        """
        Remove fields that would trigger variant recomputation.
        """
        forbidden = {
            "product_template_attribute_value_ids",
            "product_template_variant_value_ids",
            "combination_indices",
            "product_tmpl_id",
            "attribute_line_ids",
        }
        return {
            k: v for k, v in vals.items()
            if k not in forbidden
        }

    def _handle_missing_m2o(self, mapping, model, value, src=None):
        """
        Apply per-field missing M2O policy.
        """
        policy = mapping.missing_m2o_policy

        if policy == "skip":
            return False

        if policy == "stop":
            raise UserError(_(
                "Missing related record for field '%s' (source: %s). "
                "Execution stopped due to field policy."
            ) % (mapping.target_field, value))

        if policy == "create" and not mapping.create_job_id:
            comodel = self.env[model._fields[mapping.target_field].comodel_name]

            name = value[1] if isinstance(value, (list, tuple)) else value
            if not name:
                return False

            rec = self._with_sync_context(comodel.sudo()).create({"name": name})
            return rec.id
        elif policy == "create" and mapping.create_job_id:
            if mapping.post_process:
                remote_id = value[0] if isinstance(value, (list, tuple)) else value
                self._queue_post_process(
                    process_type="create_record",
                    res_ids=[remote_id],
                    process_job=mapping.create_job_id,
                    field=mapping,
                    source_model=self.source_model or self.target_model,
                    source_record_id=src.get("id") if src else False,
                )
                return False

            sync_job = mapping.create_job_id
            id = value[0] if isinstance(value, (list, tuple)) else value
            if sync_job.target_model == 'mail.message' and self.import_chatter:
                sync_job.write({'domain': ['|', ('id', 'in', [id]), '&', ('id', 'in', [id]),
                                           ('tracking_value_ids', '!=', False)], 'last_source_id': 0})
            else:
                sync_job.write({'domain': [('id', 'in', [id])], 'last_source_id': 0})
            sync_job.action_run_manual_sync()
            mappings = self.env["generic.sync.record.map"]
            for missing_id in [id]:
                mappings |= sync_job._find_existing_mapping({'id': missing_id})
            for mapping in mappings:
                local_rec = self.env[mapping.target_model].browse(mapping.target_record_id)
                if local_rec.exists():
                    return local_rec.id

        return False

    def _find_existing_record(self, src):
        """
        Wrapper used by _do_sync().
        Returns the existing target record if mapping + record exist,
        otherwise False.
        """
        mapping = self._find_existing_mapping(src)
        if not mapping:
            return False
        record = self.env[mapping.target_model].browse(mapping.target_record_id)
        return record if record.exists() else False

    # -------------------------------------------------------------------------
    # Post-processing hook
    # -------------------------------------------------------------------------
    def _post_process_values(self, source_vals, result_vals):
        """
        Execute job-level post-processing Python code.

        The code can mutate result_vals in-place.
        Available variables:
            - source_vals
            - result_vals
            - env
            - job
            - datetime, date, time, timezone, relativedelta
            - float_compare, UserError, Command
            - log(message, level='info'), _logger
        """
        self.ensure_one()

        if not self.post_process_python:
            return result_vals

        def log(message, level="info"):
            """Helper to log from within post_process_python."""
            fn = getattr(_logger, level, _logger.info)
            fn(message)

        localdict = {
            "source_vals": source_vals,
            "result_vals": result_vals,
            "env": self.env,
            "job": self,
            "datetime": datetime,
            "date": date,
            "time": time,
            "timezone": pytz,
            "relativedelta": relativedelta,
            "float_compare": float_compare,
            "UserError": UserError,
            "Command": Command,
            "log": log,
            "_logger": _logger,
        }

        try:
            safe_eval(
                self.post_process_python,
                localdict,
                mode="exec",
            )
        except Exception as exc:
            raise UserError(_(
                "Post-process Python error in job '%s'\n\n%s"
            ) % (self.name, str(exc)))
        return result_vals

    def action_view_record_mappings(self):
        """Open a tree view of all record mappings for this job."""
        self.ensure_one()
        return {
            "name": _("Record Mappings"),
            "type": "ir.actions.act_window",
            "res_model": "generic.sync.record.map",
            "view_mode": "list,form",
            "domain": [("job_id", "=", self.id)],
            "context": {"default_job_id": self.id},
        }

    def action_view_post_processes(self):
        self.ensure_one()
        return {
            "name": _("Post Processes"),
            "type": "ir.actions.act_window",
            "res_model": "generic.sync.post.process",
            "view_mode": "list,form",
            "domain": [("job_id", "=", self.id)],
            "context": {"default_job_id": self.id},
        }

    def action_run_post_processes(self):
        for job in self:
            job.post_process_ids.filtered(
                lambda p: p.state == "pending"
            ).with_context(raise_on_error=True).execute()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "message": _("Pending post-process items executed."),
                "type": "success",
                "sticky": False,
                "next": {
                    "type": "ir.actions.client",
                    "tag": "soft_reload",
                },
            },
        }
