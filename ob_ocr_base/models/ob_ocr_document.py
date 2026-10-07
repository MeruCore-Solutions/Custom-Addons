import json
import logging
import mimetypes

from odoo import _, api, fields, models, tools
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class OcrDocument(models.Model):
    _name = "ob.ocr.document"
    _description = "OCR Document"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "create_date desc, id desc"

    name = fields.Char(default=lambda self: _("New"), required=True, tracking=True)
    document_type_id = fields.Many2one("ob.ocr.document.type", required=True, tracking=True, ondelete="restrict")
    document_type = fields.Char(related="document_type_id.code", store=True, readonly=True)
    mapping_id = fields.Many2one("ob.ocr.mapping", string="Mapping", tracking=True, ondelete="set null")
    document_type_target_model = fields.Char(related="document_type_id.target_model", readonly=True)
    file = fields.Binary(required=True, attachment=True)
    filename = fields.Char(required=True)
    mimetype = fields.Char()
    source_type = fields.Selection(
        [
            ("upload", "Upload"),
            ("scanner", "Scanner"),
            ("email", "Email"),
            ("api", "API"),
        ],
        default="upload",
        required=True,
        tracking=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("queued", "Queued"),
            ("processing", "Processing"),
            ("done", "Done"),
            ("failed", "Failed"),
            ("cancelled", "Cancelled"),
        ],
        default="draft",
        required=True,
        tracking=True,
    )
    language = fields.Char(tracking=True)
    detected_language = fields.Char(readonly=True, tracking=True)
    ocr_provider_id = fields.Many2one("ob.ocr.provider", string="OCR Provider", tracking=True, ondelete="set null")
    raw_text = fields.Text()
    ocr_layout_json = fields.Json(copy=False)
    extracted_json = fields.Json(copy=False)
    extracted_json_text = fields.Text(
        string="Extracted JSON",
        compute="_compute_extracted_json_text",
        inverse="_inverse_extracted_json_text",
    )
    confidence_score = fields.Float(digits=(16, 2), tracking=True)
    page_count = fields.Integer(readonly=True)
    company_id = fields.Many2one("res.company", required=True, default=lambda self: self.env.company, index=True, tracking=True)
    user_id = fields.Many2one("res.users", default=lambda self: self.env.user, required=True, index=True)
    active = fields.Boolean(default=True)
    error_message = fields.Text()
    partner_override_id = fields.Many2one(
        "res.partner",
        string="Selected Partner",
        tracking=True,
        help="Optional manual override. If set, target record creation uses this partner instead of automatic OCR partner matching.",
    )
    related_model = fields.Char(tracking=True, readonly=True)
    related_res_id = fields.Integer(tracking=True, readonly=True)
    related_record_name = fields.Char(compute="_compute_related_record_name", string="Related Record")
    related_record_count = fields.Integer(compute="_compute_related_record_name")
    reviewed = fields.Boolean(default=False, tracking=True)
    reviewed_by = fields.Many2one("res.users", readonly=True)
    reviewed_date = fields.Datetime(readonly=True)
    review_note = fields.Text()
    line_ids = fields.One2many("ob.ocr.document.line", "document_id", string="Extracted Lines")
    log_ids = fields.One2many("ob.ocr.log", "document_id", string="OCR Logs")
    processed_attachment_ids = fields.One2many("ir.attachment", "ocr_document_id", string="Processed Files")

    @api.depends("extracted_json")
    def _compute_extracted_json_text(self):
        for record in self:
            record.extracted_json_text = json.dumps(record.extracted_json or {}, indent=2, sort_keys=True)

    def _inverse_extracted_json_text(self):
        for record in self:
            try:
                record.extracted_json = json.loads(record.extracted_json_text or "{}")
            except json.JSONDecodeError as exc:
                raise ValidationError(_("Invalid JSON value: %s") % exc) from exc

    @api.depends("related_model", "related_res_id")
    def _compute_related_record_name(self):
        for record in self:
            related_name = False
            related_count = 0
            if record.related_model and record.related_res_id and record.env.registry.get(record.related_model):
                target = record.env[record.related_model].browse(record.related_res_id).exists()
                if target:
                    related_name = target.display_name
                    related_count = 1
            record.related_record_name = related_name
            record.related_record_count = related_count

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("name", _("New")) == _("New"):
                vals["name"] = self.env["ir.sequence"].next_by_code("ob.ocr.document") or _("New")
            vals.setdefault("mimetype", self._guess_mimetype(vals.get("filename")))
            vals.setdefault("ocr_provider_id", self._get_default_provider_id())
        records = super().create(vals_list)
        for record in records:
            if not record.mapping_id:
                record.mapping_id = record._get_effective_mapping()
        return records

    def write(self, vals):
        if vals.get("filename") and not vals.get("mimetype"):
            vals["mimetype"] = self._guess_mimetype(vals["filename"])
        result = super().write(vals)
        if "document_type_id" in vals and "mapping_id" not in vals:
            for record in self:
                record.mapping_id = record._get_effective_mapping()
        return result

    @api.onchange("document_type_id", "ocr_provider_id", "company_id")
    def _onchange_defaults(self):
        for record in self:
            if not record.mapping_id:
                record.mapping_id = record._get_effective_mapping()
            if not record.ocr_provider_id:
                provider_id = record._get_default_provider_id()
                if provider_id:
                    record.ocr_provider_id = provider_id

    def action_process_ocr(self):
        for record in self:
            record.write({
                "state": "queued",
                "error_message": False,
                "reviewed": False,
                "reviewed_by": False,
                "reviewed_date": False,
            })
            record._log_event("info", "OCR document queued for background processing.")
        return True

    def action_retry_ocr(self):
        for record in self:
            record.processed_attachment_ids.unlink()
            record.line_ids.unlink()
            record.write({
                "state": "queued",
                "raw_text": False,
                "ocr_layout_json": False,
                "extracted_json": False,
                "confidence_score": 0.0,
                "error_message": False,
                "page_count": 0,
            })
            record._log_event("info", "OCR document re-queued for processing.")
        return True

    def action_cancel(self):
        for record in self:
            if record.state == "processing":
                record._log_event("warning", "Cancellation requested while OCR was already processing.")
            record.write({"state": "cancelled"})
        return True

    def action_mark_reviewed(self):
        for record in self:
            if record.extracted_json_text:
                record._inverse_extracted_json_text()
            record.write({
                "reviewed": True,
                "reviewed_by": self.env.user.id,
                "reviewed_date": fields.Datetime.now(),
            })
            record._log_event("info", "OCR data reviewed and approved.")
        return True

    def action_create_target_record(self):
        self.ensure_one()
        if not self.document_type_id.target_model:
            raise UserError(_("This document type is not configured to create an Odoo record."))
        if self.related_model and self.related_res_id:
            raise UserError(_("This OCR document is already linked to an Odoo record."))
        if self._requires_manual_review() and not self.reviewed:
            raise UserError(_("This OCR document must be reviewed before a target record can be created."))
        record = self.env["ob.ocr.record.creation.service"].create_target_record(self)
        self._log_event("info", "Target record created.", {"model": record._name, "res_id": record.id})
        return self.action_open_related_record()

    def action_update_target_record(self):
        self.ensure_one()
        if not (self.related_model and self.related_res_id):
            raise UserError(_("There is no linked record to update from this OCR document."))
        if self._requires_manual_review() and not self.reviewed:
            raise UserError(_("This OCR document must be reviewed before the linked record can be updated."))
        record = self.env["ob.ocr.record.creation.service"].update_target_record(self)
        self._log_event("info", "Target record updated.", {"model": record._name, "res_id": record.id})
        return self.action_open_related_record()

    def action_open_related_record(self):
        self.ensure_one()
        if not (self.related_model and self.related_res_id):
            raise UserError(_("No linked record is available yet."))
        return {
            "type": "ir.actions.act_window",
            "name": _("Linked Record"),
            "res_model": self.related_model,
            "res_id": self.related_res_id,
            "view_mode": "form",
            "target": "current",
        }

    @api.model
    def _cron_process_queue(self, limit=10):
        documents = self.search([("state", "=", "queued")], limit=limit, order="create_date asc, id asc")
        for document in documents:
            document._process_ocr()
        return True

    def process_ocr(self):
        if self.env.context.get("ocr_run_now"):
            for document in self:
                document._process_ocr()
            return True
        return self.action_process_ocr()

    def _process_ocr(self):
        self.ensure_one()
        provider = self._get_effective_provider()
        if not provider:
            self._mark_failed(_("No OCR provider is configured for this document."))
            return False
        if not provider.supports_file_type(self.mimetype):
            self._mark_failed(_("The selected OCR provider does not support %s.") % self.mimetype)
            return False
        try:
            self.write({
                "state": "processing",
                "ocr_provider_id": provider.id,
                "error_message": False,
            })
            self._log_event("info", "OCR processing started.", {"provider": provider.display_name})
            if self._should_auto_detect_language() and not self.language:
                detected = provider.detect_language(self)
                if detected:
                    self.detected_language = detected
            text_result = self._extract_text()
            raw_text = text_result["text"] if isinstance(text_result, dict) else text_result
            layout_json = (text_result or {}).get("layout_json") if isinstance(text_result, dict) else False
            self.write({
                "raw_text": raw_text or False,
                "confidence_score": (text_result or {}).get("confidence", 0.0) if isinstance(text_result, dict) else 0.0,
                "page_count": (text_result or {}).get("page_count", 0) if isinstance(text_result, dict) else 0,
                "detected_language": (text_result or {}).get("detected_language") if isinstance(text_result, dict) else self.detected_language,
            })
            if layout_json:
                self.write({"ocr_layout_json": layout_json})
            extracted_json = self._extract_structured_data()
            self.write({
                "extracted_json": extracted_json,
                "state": "done",
            })
            self._sync_line_items_from_json()
            if self._is_below_confidence_threshold():
                self._log_event(
                    "warning",
                    "OCR completed below the configured confidence threshold.",
                    {"confidence": self.confidence_score},
                )
            self._log_event("info", "OCR processing completed.", {"confidence": self.confidence_score})
            if self._should_auto_create_target():
                try:
                    self.action_create_target_record()
                except Exception as exc:  # pragma: no cover - optional follow-up automation
                    self._log_event("warning", "Automatic target record creation failed.", {"error": tools.ustr(exc)})
            return True
        except Exception as exc:
            _logger.exception("OCR processing failed for %s", self.display_name)
            self._mark_failed(tools.ustr(exc))
            return False

    def _extract_text(self):
        self.ensure_one()
        return self.env["ob.ocr.text.service"].extract_document_text(self)

    def _extract_structured_data(self):
        self.ensure_one()
        return self.env["ob.ocr.extraction.service"].extract_document_data(self)

    def _prepare_target_values(self):
        self.ensure_one()
        return self.env["ob.ocr.mapping.service"].prepare_target_payload(self)

    def _create_target_record(self, values=None):
        self.ensure_one()
        target_model = self.document_type_id.target_model
        if not target_model:
            raise UserError(_("No target model is configured for this document type."))
        values = values or self._prepare_target_values()
        record = self.env[target_model].create(values)
        self._set_related_record(record)
        self._attach_original_file(record)
        return record

    def _update_target_record(self, values=None):
        self.ensure_one()
        if not (self.related_model and self.related_res_id):
            raise UserError(_("There is no related record to update."))
        record = self.env[self.related_model].browse(self.related_res_id).exists()
        if not record:
            raise UserError(_("The related record no longer exists."))
        values = values or self._prepare_target_values()
        record.write(values)
        self._attach_original_file(record)
        return record

    def _dispatch_document_type_method(self, field_name, default_method_name, *args):
        self.ensure_one()
        method_name = getattr(self.document_type_id, field_name, False) or default_method_name
        method = getattr(self, method_name, None)
        if not method:
            raise UserError(_("Method %s is not available on OCR documents.") % method_name)
        return method(*args)

    def _set_related_record(self, record):
        self.ensure_one()
        self.write({
            "related_model": record._name,
            "related_res_id": record.id,
        })
        if hasattr(record, "message_post"):
            record.message_post(body=_("Created from OCR document %s.") % self.display_name)

    def _attach_original_file(self, record):
        self.ensure_one()
        if not self.file:
            return False
        self.env["ir.attachment"].sudo().create({
            "name": self.filename or self.name,
            "datas": self.file,
            "mimetype": self.mimetype,
            "res_model": record._name,
            "res_id": record.id,
        })
        return True

    def _sync_line_items_from_json(self):
        for record in self:
            line_commands = [(5, 0, 0)]
            for sequence, payload in enumerate(record._get_line_payloads(), start=1):
                line_commands.append((0, 0, {
                    "sequence": sequence * 10,
                    "source_key": payload.get("source_key"),
                    "name": payload.get("description") or payload.get("name"),
                    "product_code": payload.get("product_code"),
                    "barcode": payload.get("barcode"),
                    "product_name": payload.get("product_name") or payload.get("name"),
                    "quantity": payload.get("quantity") or 0.0,
                    "uom_name": payload.get("uom") or payload.get("uom_name"),
                    "unit_price": payload.get("unit_price") or 0.0,
                    "discount": payload.get("discount") or 0.0,
                    "tax_names": ", ".join(payload.get("taxes", [])) if isinstance(payload.get("taxes"), list) else payload.get("taxes"),
                    "confidence_score": payload.get("confidence_score") or record.confidence_score,
                    "raw_payload": payload,
                    "note": payload.get("notes") or payload.get("note"),
                }))
            record.write({"line_ids": line_commands})

    def _get_line_payloads(self):
        self.ensure_one()
        data = self.extracted_json or {}
        for key in ("line_items", "invoice_lines", "order_lines", "product_lines", "lines"):
            value = data.get(key)
            if isinstance(value, list):
                return value
        return []

    def _mark_failed(self, message):
        self.write({
            "state": "failed",
            "error_message": message,
        })
        self._log_event("error", "OCR processing failed.", {"error": message})

    def _log_event(self, level, message, details=None):
        for record in self:
            self.env["ob.ocr.log"].create({
                "document_id": record.id,
                "provider_id": record.ocr_provider_id.id,
                "level": level,
                "message": message,
                "details_json": details or {},
            })

    def _get_effective_provider(self):
        self.ensure_one()
        if self.ocr_provider_id:
            return self.ocr_provider_id
        provider_id = self._get_default_provider_id()
        return self.env["ob.ocr.provider"].browse(provider_id).exists() if provider_id else self.env["ob.ocr.provider"].browse()

    def _get_effective_mapping(self):
        self.ensure_one()
        if self.mapping_id:
            return self.mapping_id
        domain = [
            ("active", "=", True),
            ("document_type_id", "=", self.document_type_id.id),
            "|",
            ("company_id", "=", False),
            ("company_id", "=", self.company_id.id),
        ]
        mappings = self.env["ob.ocr.mapping"].search(domain, order="sequence, id")
        if self.ocr_provider_id:
            provider_specific = mappings.filtered(lambda mapping: not mapping.provider_id or mapping.provider_id == self.ocr_provider_id)
            if provider_specific:
                return provider_specific[0]
        return mappings[:1]

    @api.model
    def _get_default_provider_id(self):
        provider_id = self.env["ir.config_parameter"].sudo().get_param("ob_ocr_base.default_provider_id", default=False)
        if provider_id:
            return int(provider_id)
        provider = self.env["ob.ocr.provider"].search([("is_default", "=", True)], limit=1)
        return provider.id

    @api.model
    def _guess_mimetype(self, filename):
        return mimetypes.guess_type(filename or "")[0] or "application/octet-stream"

    def _is_below_confidence_threshold(self):
        self.ensure_one()
        threshold = float(self.env["ir.config_parameter"].sudo().get_param("ob_ocr_base.confidence_threshold", default="70.0"))
        return bool(threshold and self.confidence_score and self.confidence_score < threshold)

    def _should_auto_detect_language(self):
        return self.env["ir.config_parameter"].sudo().get_param("ob_ocr_base.auto_detect_language", default="True") == "True"

    def _requires_manual_review(self):
        return self.env["ir.config_parameter"].sudo().get_param("ob_ocr_base.require_manual_review", default="True") == "True"

    def _should_auto_create_target(self):
        self.ensure_one()
        if self.related_res_id or not self.document_type_id.target_model:
            return False
        auto_create = self.env["ir.config_parameter"].sudo().get_param(
            "ob_ocr_base.auto_create_target_records",
            default="False",
        ) == "True"
        return auto_create and not self._requires_manual_review()

    def _parse_date_value(self, value):
        if not value:
            return False
        try:
            from dateutil import parser as date_parser

            return date_parser.parse(str(value), dayfirst=True).date()
        except Exception:
            return False

    def _parse_float_value(self, value):
        if value in (False, None, ""):
            return 0.0
        cleaned = str(value).strip().replace(" ", "")
        if cleaned.count(",") == 1 and cleaned.count(".") == 0:
            cleaned = cleaned.replace(",", ".")
        elif cleaned.count(",") > 0 and cleaned.count(".") > 0:
            cleaned = cleaned.replace(".", "").replace(",", ".")
        return float(cleaned)

    def _match_currency(self, currency_value):
        if not currency_value:
            return self.env.company.currency_id
        currency = self.env["res.currency"].search([
            "|",
            ("name", "=", str(currency_value).upper()),
            ("symbol", "=", currency_value),
        ], limit=1)
        return currency or self.env.company.currency_id

    def _match_payment_term(self, payment_term_value):
        if not payment_term_value or not self.env.registry.get("account.payment.term"):
            return False
        payment_term_model = self.env["account.payment.term"]
        return payment_term_model.search([
            "|",
            ("name", "=", payment_term_value),
            ("name", "ilike", payment_term_value),
        ], limit=1)

    def _match_incoterm(self, incoterm_value):
        if not incoterm_value or not self.env.registry.get("account.incoterms"):
            return False
        incoterm_model = self.env["account.incoterms"]
        return incoterm_model.search([
            "|",
            ("code", "=", str(incoterm_value).upper()),
            ("name", "ilike", incoterm_value),
        ], limit=1)

    def _match_taxes(self, tax_values, usage):
        if not tax_values or not self.env.registry.get("account.tax"):
            return False
        if isinstance(tax_values, str):
            tax_values = [item.strip() for item in tax_values.split(",") if item.strip()]
        tax_model = self.env["account.tax"]
        matched_taxes = tax_model.browse()
        for tax_value in tax_values:
            tax = tax_model.search([
                ("type_tax_use", "in", [usage, "none"]),
                "|",
                ("name", "=", tax_value),
                ("name", "ilike", tax_value),
            ], limit=1)
            if not tax:
                try:
                    amount = self._parse_float_value(tax_value)
                    tax = tax_model.search([
                        ("type_tax_use", "in", [usage, "none"]),
                        ("amount", "=", amount),
                    ], limit=1)
                except Exception:
                    tax = tax_model.browse()
            matched_taxes |= tax
        return matched_taxes

    def _resolve_partner_match(self, payload, role="partner", allow_create=None):
        self.ensure_one()
        if self.partner_override_id:
            return self.partner_override_id
        return self.env["ob.ocr.partner.matcher"].match_partner(
            payload,
            role=role,
            allow_create=allow_create,
        )
