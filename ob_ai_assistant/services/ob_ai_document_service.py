import base64
import csv
import io
import json
import logging
import os
import shutil
import subprocess
import tempfile
from datetime import date, datetime

from odoo import _, fields, models

_logger = logging.getLogger(__name__)

TEXT_EXTENSIONS = {"txt", "md", "json", "xml", "html", "htm", "log", "csv", "tsv"}
CSV_EXTENSIONS = {"csv", "tsv"}
EXCEL_EXTENSIONS = {"xlsx", "xlsm", "xltx", "xltm", "xls"}
PDF_EXTENSIONS = {"pdf"}
IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "bmp", "tif", "tiff", "webp", "gif"}

DEFAULT_MAX_CHARACTERS = 20_000
DEFAULT_MAX_ROWS = 500
DEFAULT_MAX_TABLES = 5


class OBAIDocumentService(models.AbstractModel):
    _name = "ob.ai.document.service"
    _description = "AI Document Service"

    def build_document_context(self, record, conversation=False):
        record = record.exists()
        if not record:
            return {
                "documents": [],
                "document_contexts": self.env["ob.ai.document.context"],
            }
        attachments = self.env["ir.attachment"].search(
            [
                ("res_model", "=", record._name),
                ("res_id", "=", record.id),
                ("type", "=", "binary"),
            ],
            order="create_date desc, id desc",
            limit=5,
        )
        return self.build_attachment_document_context(
            attachments,
            conversation=conversation,
            record=record,
        )

    def build_conversation_document_context(self, conversation):
        conversation = conversation.exists()
        if not conversation:
            return {
                "documents": [],
                "document_contexts": self.env["ob.ai.document.context"],
            }
        return self.build_attachment_document_context(
            conversation.chat_attachment_ids,
            conversation=conversation,
            record=conversation.related_record_ref or False,
        )

    def build_attachment_document_context(self, attachments, conversation=False, record=False):
        max_tables = self._get_int_param("ob_ai_assistant.document_extract_max_tables", DEFAULT_MAX_TABLES)
        attachments = attachments.exists().filtered(lambda attachment: attachment.type == "binary")[: max(max_tables, 1)]
        context_records = self.env["ob.ai.document.context"]
        documents = []
        for attachment in attachments:
            document_context = self._get_or_create_document_context(
                attachment,
                record=record,
                conversation=conversation,
            )
            context_records |= document_context
            documents.append({
                "attachment_id": attachment.id,
                "name": attachment.display_name,
                "mimetype": attachment.mimetype,
                "checksum": document_context.attachment_checksum,
                "context_type": document_context.context_type,
                "text_preview": document_context.text_preview,
                "character_count": document_context.character_count,
                "extraction_engine": document_context.extraction_engine,
                "structured_table_count": document_context.structured_table_count,
                "structured_row_count": document_context.structured_row_count,
            })
        return {
            "documents": documents,
            "document_contexts": context_records,
        }

    def build_attachment_context(self, attachment, conversation=False, record=False, force_refresh=False, max_rows=False):
        attachment = attachment.exists()
        if not attachment or attachment.type != "binary":
            return {}
        document_context = self._get_or_create_document_context(
            attachment,
            record=record,
            conversation=conversation,
            force_refresh=force_refresh,
        )
        return self._context_to_payload(document_context, max_rows=max_rows)

    def get_attachment_tabular_rows(self, attachment, sheet_name=False, max_rows=False, force_refresh=False):
        context = self.build_attachment_context(
            attachment,
            force_refresh=force_refresh,
            max_rows=max_rows or DEFAULT_MAX_ROWS,
        )
        tables = context.get("tables") or []
        if not tables:
            extracted_text = (context.get("extracted_text") or "").strip()
            if extracted_text:
                rows = [{"extracted_text": extracted_text}]
                return {
                    "ok": True,
                    "table_name": "Extracted Text",
                    "columns": ["extracted_text"],
                    "rows": rows,
                    "row_count": len(rows),
                    "available_tables": ["Extracted Text"],
                }
            return {"ok": False, "error": _("No structured tabular data was detected in this attachment.")}
        selected = False
        sheet_name = (sheet_name or "").strip()
        if sheet_name:
            for table in tables:
                if (table.get("name") or "").strip().lower() == sheet_name.lower():
                    selected = table
                    break
        if not selected:
            selected = tables[0]
        rows = list(selected.get("rows") or [])
        if max_rows:
            rows = rows[: max(int(max_rows), 1)]
        return {
            "ok": True,
            "table_name": selected.get("name"),
            "columns": selected.get("columns") or [],
            "rows": rows,
            "row_count": len(rows),
            "available_tables": [table.get("name") for table in tables],
        }

    def _get_or_create_document_context(self, attachment, record=False, conversation=False, force_refresh=False):
        checksum = attachment.checksum or attachment.store_fname or str(attachment.id)
        existing = self.env["ob.ai.document.context"].search(
            [
                ("attachment_id", "=", attachment.id),
                ("attachment_checksum", "=", checksum),
            ],
            limit=1,
        )
        if existing and not force_refresh:
            return existing
        if existing and force_refresh:
            existing.unlink()

        payload = self._extract_attachment_payload(attachment)
        return self.env["ob.ai.document.context"].create({
            "attachment_id": attachment.id,
            "attachment_checksum": checksum,
            "related_record_ref": "%s,%s" % (record._name, record.id) if record else False,
            "source_conversation_id": conversation.id if conversation else False,
            "state": payload["state"],
            "context_type": self._guess_context_type(attachment),
            "extracted_text": payload["extracted_text"],
            "character_count": len(payload["extracted_text"] or ""),
            "error_message": payload["error_message"],
            "structured_payload": payload["structured_payload"],
            "structured_row_count": payload["structured_row_count"],
            "structured_table_count": payload["structured_table_count"],
            "extraction_engine": payload["extraction_engine"],
            "parse_metadata": payload["parse_metadata"],
        })

    def _extract_attachment_payload(self, attachment):
        extension = self._extension_from_attachment(attachment)
        max_rows = self._get_int_param("ob_ai_assistant.document_extract_max_rows", DEFAULT_MAX_ROWS)
        max_chars = self._get_int_param("ob_ai_assistant.document_extract_max_chars", DEFAULT_MAX_CHARACTERS)
        extracted_text = self._truncate(attachment.index_content or "", max_chars=max_chars)
        extraction_engine = "odoo_index" if extracted_text else "binary_metadata"
        structured_payload = {}
        parse_metadata = {"extension": extension, "mimetype": attachment.mimetype or ""}
        error_messages = []
        state = "ready"

        raw_bytes = self._decode_attachment_bytes(attachment)
        if raw_bytes is None:
            state = "error"
            error_messages.append(_("Could not decode attachment %s.", attachment.display_name))
        else:
            try:
                if extension in CSV_EXTENSIONS:
                    table_payload = self._extract_csv_payload(
                        raw_bytes,
                        delimiter="\t" if extension == "tsv" else ",",
                        sheet_name="Table",
                        max_rows=max_rows,
                    )
                    extracted_text = extracted_text or table_payload["text"]
                    structured_payload = table_payload["structured_payload"]
                    extraction_engine = table_payload["engine"]
                elif extension in EXCEL_EXTENSIONS:
                    excel_payload = self._extract_excel_payload(raw_bytes, max_rows=max_rows)
                    extracted_text = extracted_text or excel_payload["text"]
                    structured_payload = excel_payload["structured_payload"]
                    extraction_engine = excel_payload["engine"]
                    parse_metadata.update(excel_payload.get("metadata") or {})
                elif extension in PDF_EXTENSIONS:
                    pdf_payload = self._extract_pdf_payload(raw_bytes)
                    extracted_text = extracted_text or pdf_payload.get("text", "")
                    extraction_engine = pdf_payload.get("engine") or extraction_engine
                    if pdf_payload.get("error"):
                        error_messages.append(pdf_payload["error"])
                elif extension in IMAGE_EXTENSIONS or (attachment.mimetype or "").startswith("image/"):
                    image_payload = self._extract_image_payload(raw_bytes, extension=extension)
                    extracted_text = extracted_text or image_payload.get("text", "")
                    extraction_engine = image_payload.get("engine") or extraction_engine
                    if image_payload.get("error"):
                        error_messages.append(image_payload["error"])
                elif extension in TEXT_EXTENSIONS or (attachment.mimetype or "").startswith("text/"):
                    text_payload = self._extract_text_payload(raw_bytes, extension=extension, max_rows=max_rows)
                    extracted_text = extracted_text or text_payload.get("text", "")
                    structured_payload = text_payload.get("structured_payload") or {}
                    extraction_engine = text_payload.get("engine") or "text_decode"
                elif extracted_text:
                    extraction_engine = "odoo_index"
            except Exception as exc:  # noqa: BLE001
                _logger.exception("Attachment extraction failed for %s", attachment.display_name)
                state = "error"
                error_messages.append(str(exc))

        if not extracted_text:
            extracted_text = _(
                "Binary attachment: %(name)s (%(mimetype)s). No extractable plain text was available.",
                name=attachment.display_name,
                mimetype=attachment.mimetype or "application/octet-stream",
            )
            extraction_engine = "metadata_only"
        extracted_text = self._truncate(extracted_text, max_chars=max_chars)
        structured_payload = self._normalize_structured_payload(structured_payload, max_rows=max_rows)
        if error_messages and state != "error":
            # Keep extraction usable but visible in audit/form.
            state = "ready"

        table_count, row_count = self._structured_counts(structured_payload)
        return {
            "state": state,
            "extracted_text": extracted_text,
            "error_message": "\n".join(message for message in error_messages if message) or False,
            "structured_payload": structured_payload,
            "structured_table_count": table_count,
            "structured_row_count": row_count,
            "extraction_engine": extraction_engine,
            "parse_metadata": parse_metadata,
        }

    def _extract_text_payload(self, raw_bytes, extension=False, max_rows=DEFAULT_MAX_ROWS):
        text = self._decode_text(raw_bytes)
        structured_payload = {}
        if extension in CSV_EXTENSIONS:
            structured_payload = self._extract_csv_payload(
                raw_bytes,
                delimiter="\t" if extension == "tsv" else ",",
                sheet_name="Table",
                max_rows=max_rows,
            ).get("structured_payload") or {}
        elif extension == "json":
            structured_payload = self._extract_json_payload(text, max_rows=max_rows)
        return {
            "engine": "text_decode",
            "text": text,
            "structured_payload": structured_payload,
        }

    def _extract_csv_payload(self, raw_bytes, delimiter=",", sheet_name="Table", max_rows=DEFAULT_MAX_ROWS):
        text = self._decode_text(raw_bytes)
        reader = csv.reader(io.StringIO(text), delimiter=delimiter)
        rows_raw = []
        for row in reader:
            if row and any(str(cell or "").strip() for cell in row):
                rows_raw.append(row)
            if len(rows_raw) >= max(max_rows, 1) + 1:
                break
        if not rows_raw:
            return {"engine": "csv", "text": text, "structured_payload": {}}
        header, data_rows = self._split_header_and_rows(rows_raw)
        rows = [self._row_to_dict(header, row) for row in data_rows[: max(max_rows, 1)]]
        return {
            "engine": "csv",
            "text": text,
            "structured_payload": {
                "format": "tabular",
                "tables": [{
                    "name": sheet_name,
                    "columns": header,
                    "rows": rows,
                    "row_count": len(rows),
                }],
            },
        }

    def _extract_excel_payload(self, raw_bytes, max_rows=DEFAULT_MAX_ROWS):
        workbook = False
        import_error = False
        for module_name in ("openpyxl",):
            try:
                module = __import__(module_name, fromlist=["load_workbook"])
                workbook = module.load_workbook(io.BytesIO(raw_bytes), read_only=True, data_only=True)
                break
            except Exception as exc:  # noqa: BLE001
                import_error = str(exc)
        if not workbook:
            raise ValueError(_("Excel parsing is unavailable in this environment: %s", import_error or "missing openpyxl"))

        tables = []
        text_chunks = []
        for sheet in workbook.worksheets:
            rows_raw = []
            for row in sheet.iter_rows(values_only=True):
                normalized = [self._json_safe(cell) for cell in row]
                if normalized and any(str(cell or "").strip() for cell in normalized):
                    rows_raw.append(normalized)
                if len(rows_raw) >= max(max_rows, 1) + 1:
                    break
            if not rows_raw:
                continue
            header, data_rows = self._split_header_and_rows(rows_raw)
            row_dicts = [self._row_to_dict(header, row) for row in data_rows[: max(max_rows, 1)]]
            tables.append({
                "name": sheet.title,
                "columns": header,
                "rows": row_dicts,
                "row_count": len(row_dicts),
            })
            text_chunks.append(
                _(
                    "Sheet %(sheet)s: %(count)s rows, columns: %(columns)s",
                    sheet=sheet.title,
                    count=len(row_dicts),
                    columns=", ".join(header[:20]),
                )
            )
            if len(tables) >= max(self._get_int_param("ob_ai_assistant.document_extract_max_tables", DEFAULT_MAX_TABLES), 1):
                break
        workbook.close()
        return {
            "engine": "excel_openpyxl",
            "text": "\n".join(text_chunks),
            "structured_payload": {
                "format": "tabular",
                "tables": tables,
            },
            "metadata": {"sheet_count": len(tables)},
        }

    def _extract_json_payload(self, text, max_rows=DEFAULT_MAX_ROWS):
        try:
            parsed = json.loads(text or "")
        except Exception:  # noqa: BLE001
            return {}
        if isinstance(parsed, list) and parsed and isinstance(parsed[0], dict):
            columns = []
            for row in parsed[: max(max_rows, 1)]:
                for key in row.keys():
                    if key not in columns:
                        columns.append(str(key))
            rows = []
            for row in parsed[: max(max_rows, 1)]:
                rows.append({column: self._json_safe(row.get(column)) for column in columns})
            return {
                "format": "tabular",
                "tables": [{
                    "name": "JSON",
                    "columns": columns,
                    "rows": rows,
                    "row_count": len(rows),
                }],
            }
        return {}

    def _extract_pdf_payload(self, raw_bytes):
        errors = []
        for module_name in ("pypdf", "PyPDF2"):
            try:
                module = __import__(module_name, fromlist=["PdfReader"])
                reader = module.PdfReader(io.BytesIO(raw_bytes))
                text_chunks = []
                for page in reader.pages:
                    page_text = page.extract_text() or ""
                    if page_text.strip():
                        text_chunks.append(page_text.strip())
                if text_chunks:
                    return {"text": "\n\n".join(text_chunks), "engine": module_name}
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))
        pdftotext_bin = shutil.which("pdftotext")
        if pdftotext_bin:
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                    tmp_file.write(raw_bytes)
                    tmp_path = tmp_file.name
                cmd = [pdftotext_bin, "-layout", tmp_path, "-"]
                result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=30)
                os.unlink(tmp_path)
                if result.returncode == 0 and result.stdout.strip():
                    return {"text": result.stdout, "engine": "pdftotext"}
                errors.append(result.stderr.strip() or _("pdftotext returned no text"))
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))
        return {"text": "", "engine": False, "error": "; ".join(message for message in errors if message)}

    def _extract_image_payload(self, raw_bytes, extension=False):
        errors = []
        try:
            image_module = __import__("PIL.Image", fromlist=["Image"])
            pytesseract = __import__("pytesseract")
            image = image_module.open(io.BytesIO(raw_bytes))
            text = pytesseract.image_to_string(image) or ""
            if text.strip():
                return {"text": text, "engine": "pytesseract"}
            errors.append(_("OCR returned no text."))
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))

        tesseract_bin = shutil.which("tesseract")
        if tesseract_bin:
            suffix = ".%s" % (extension or "png")
            temp_path = False
            try:
                with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
                    tmp_file.write(raw_bytes)
                    temp_path = tmp_file.name
                cmd = [tesseract_bin, temp_path, "stdout"]
                result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=30)
                if result.returncode == 0 and (result.stdout or "").strip():
                    return {"text": result.stdout, "engine": "tesseract_cli"}
                errors.append(result.stderr.strip() or _("tesseract returned no text"))
            except Exception as exc:  # noqa: BLE001
                errors.append(str(exc))
            finally:
                if temp_path and os.path.exists(temp_path):
                    os.unlink(temp_path)
        return {"text": "", "engine": False, "error": "; ".join(message for message in errors if message)}

    def _context_to_payload(self, document_context, max_rows=False):
        document_context.ensure_one()
        payload = document_context.structured_payload or {}
        tables = []
        for table in payload.get("tables") or []:
            rows = table.get("rows") or []
            if max_rows:
                rows = rows[: max(int(max_rows), 1)]
            tables.append({
                "name": table.get("name"),
                "columns": table.get("columns") or [],
                "rows": rows,
                "row_count": table.get("row_count") or len(rows),
            })
        return {
            "document_context_id": document_context.id,
            "attachment_id": document_context.attachment_id.id,
            "name": document_context.attachment_id.display_name,
            "mimetype": document_context.attachment_id.mimetype,
            "state": document_context.state,
            "context_type": document_context.context_type,
            "extracted_text": document_context.extracted_text or "",
            "text_preview": document_context.text_preview or "",
            "character_count": document_context.character_count or 0,
            "structured_table_count": document_context.structured_table_count or 0,
            "structured_row_count": document_context.structured_row_count or 0,
            "extraction_engine": document_context.extraction_engine,
            "tables": tables,
            "parse_metadata": document_context.parse_metadata or {},
            "error_message": document_context.error_message or "",
        }

    def _decode_attachment_bytes(self, attachment):
        if not attachment.datas:
            return b""
        try:
            return base64.b64decode(attachment.datas)
        except Exception:  # noqa: BLE001
            return None

    def _decode_text(self, raw_bytes):
        if raw_bytes is None:
            return ""
        for encoding in ("utf-8", "utf-16", "latin-1"):
            try:
                return raw_bytes.decode(encoding, errors="ignore")
            except Exception:  # noqa: BLE001
                continue
        return ""

    def _split_header_and_rows(self, rows):
        first = list(rows[0] or [])
        second = list(rows[1] or []) if len(rows) > 1 else []
        use_first_as_header = bool(first) and any(str(cell or "").strip() for cell in first)
        if use_first_as_header:
            header = [self._normalize_header(cell, index + 1) for index, cell in enumerate(first)]
            data_rows = rows[1:]
            # If the first row looks numeric and the second row is empty-ish, treat as data instead.
            if second and all(self._looks_like_number(cell) for cell in first if str(cell or "").strip()):
                header = [self._normalize_header(False, index + 1) for index, _cell in enumerate(first)]
                data_rows = rows
        else:
            col_count = max(len(row or []) for row in rows)
            header = [self._normalize_header(False, index + 1) for index in range(col_count)]
            data_rows = rows
        return header, data_rows

    def _row_to_dict(self, columns, row):
        values = list(row or [])
        row_dict = {}
        for index, column in enumerate(columns):
            row_dict[column] = self._json_safe(values[index] if index < len(values) else False)
        return row_dict

    def _normalize_header(self, raw, index):
        label = str(raw or "").strip()
        if not label:
            return "column_%s" % index
        normalized = "".join(char if char.isalnum() or char == "_" else "_" for char in label.lower())
        normalized = normalized.strip("_")
        return normalized or "column_%s" % index

    def _looks_like_number(self, value):
        text = str(value or "").strip()
        if not text:
            return False
        try:
            float(text.replace(",", ""))
            return True
        except Exception:  # noqa: BLE001
            return False

    def _normalize_structured_payload(self, structured_payload, max_rows=DEFAULT_MAX_ROWS):
        payload = structured_payload or {}
        tables = []
        for table in payload.get("tables") or []:
            columns = [str(column) for column in (table.get("columns") or [])]
            rows = []
            for row in table.get("rows") or []:
                if isinstance(row, dict):
                    rows.append({str(key): self._json_safe(value) for key, value in row.items()})
                else:
                    rows.append(self._json_safe(row))
                if len(rows) >= max(max_rows, 1):
                    break
            tables.append({
                "name": table.get("name") or "Table",
                "columns": columns,
                "rows": rows,
                "row_count": table.get("row_count") or len(rows),
            })
            if len(tables) >= max(self._get_int_param("ob_ai_assistant.document_extract_max_tables", DEFAULT_MAX_TABLES), 1):
                break
        if not tables:
            return {}
        return {"format": "tabular", "tables": tables}

    def _structured_counts(self, structured_payload):
        tables = (structured_payload or {}).get("tables") or []
        row_count = 0
        for table in tables:
            row_count += len(table.get("rows") or [])
        return len(tables), row_count

    def _extension_from_attachment(self, attachment):
        filename = (attachment.display_name or attachment.name or "").strip().lower()
        if "." in filename:
            return filename.rsplit(".", 1)[-1]
        return ""

    def _json_safe(self, value):
        if value is None or isinstance(value, (bool, int, float, str)):
            return value
        if isinstance(value, datetime):
            return fields.Datetime.to_string(value)
        if isinstance(value, date):
            return fields.Date.to_string(value)
        return str(value)

    def _truncate(self, text, max_chars=False):
        limit = max_chars or self._get_int_param("ob_ai_assistant.document_extract_max_chars", DEFAULT_MAX_CHARACTERS)
        return (text or "")[: max(limit, 1)]

    def _get_int_param(self, key, default):
        value = self.env["ir.config_parameter"].sudo().get_param(key, default=str(default))
        try:
            return int(value)
        except Exception:  # noqa: BLE001
            return int(default)

    def _guess_context_type(self, attachment):
        name = (attachment.display_name or "").lower()
        if "transcript" in name or "meeting" in name:
            return "transcript"
        if name.endswith(".txt") or name.endswith(".md"):
            return "note"
        return "attachment"
