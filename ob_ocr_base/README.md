# ob_ocr_base

`ob_ocr_base` is the reusable OCR foundation for Odoo 19. It accepts uploads from users, scanners, and authenticated API clients, runs OCR in the background, extracts raw text plus structured JSON, supports manual review, and creates or updates downstream Odoo records through extension modules.

## Features

- OCR document queue with states: `draft`, `queued`, `processing`, `done`, `failed`, `cancelled`
- Support for PDFs, PNG, JPG, JPEG, TIFF, WEBP, scanner uploads, and multi-page documents
- Provider abstraction through `ob.ocr.provider`
- Raw OCR text, structured JSON, confidence score, logs, processed-file storage, and review workflow
- Extendable document types through `ob.ocr.document.type`
- Regex, template, provider, and AI-ready extraction modes
- Background processing through `ir.cron`
- Secure authenticated upload endpoint: `POST /ocr/upload`
- Multi-company record rules and dedicated OCR user / manager groups

## Main Models

- `ob.ocr.document`
- `ob.ocr.document.line`
- `ob.ocr.provider`
- `ob.ocr.mapping`
- `ob.ocr.mapping.field`
- `ob.ocr.extraction.rule`
- `ob.ocr.log`
- `ob.ocr.document.type`

## Installation

Copy `ob_ocr_base` into your Odoo 19 addons path, update the app list, and install the module.

### Optional Python dependencies

Install the OCR-related Python packages in the same environment as Odoo:

- `pytesseract`
- `Pillow`
- `pypdfium2` or `pdf2image`
- `python-dateutil`

Example:

```bash
pip install pytesseract Pillow pypdfium2 python-dateutil
```

### System dependency

Install the Tesseract OCR engine plus the language packs you need:

- `tesseract`
- `tesseract-ocr-<language>`

Examples of language codes used by the module:

- `eng`
- `deu`
- `fra`
- `ara`

If `pdf2image` is used instead of `pypdfium2`, you may also need Poppler on the host system.

## Configuration

Configure OCR under:

- `OCR / Configuration / Providers`
- `OCR / Configuration / Mappings`
- `OCR / Configuration / Settings`

Important settings:

- default OCR provider
- handwriting enablement
- default OCR language
- auto language detection
- partner/product auto creation
- auto target record creation
- manual review requirement
- auto-confirm options for sale, purchase, and delivery flows
- confidence threshold

## Provider Setup

The default sample provider uses Tesseract through `ob.ocr.provider.service`.

Provider methods exposed on `ob.ocr.provider`:

- `extract_text(document)`
- `extract_json(document, schema)`
- `detect_language(document)`
- `supports_handwriting()`
- `supports_file_type(mimetype)`

To add a new provider:

1. Create a new provider record in `ob.ocr.provider`.
2. Point `service_model` to an abstract model that implements the provider methods.
3. Set `provider_key` to your provider identifier.
4. Extend `ob.ocr.provider.service` or add a new service model.

## How the Workflow Works

1. A user uploads or scans a file.
2. An `ob.ocr.document` record is created.
3. The record is queued for cron-based background processing.
4. OCR text is extracted.
5. Structured JSON is produced from provider output and/or regex rules.
6. The user reviews and corrects the OCR result.
7. The user creates or updates the target record.
8. The original file is attached to the target record.

## Secure Upload API

Authenticated route:

- `POST /ocr/upload`

Parameters:

- `file`
- `document_type`
- `source_type`
- `company_id` optional

The route uses `auth='user'` and is not publicly exposed.

## Extending the Framework

### Add a new document type

1. Create a new `ob.ocr.document.type` record with a unique `code`.
2. Set `target_model`.
3. Set the handler methods if you need custom record creation/update logic.
4. Add mappings and extraction rules for the new document type.

### Add mapping rules

1. Create an `ob.ocr.mapping`.
2. Define `schema_json` with the expected keys.
3. Add `ob.ocr.mapping.field` rows to map extracted keys to Odoo fields.
4. Add `ob.ocr.extraction.rule` rows for regex-based fallback extraction.

### Add AI-assisted extraction later

`ob.ocr.extraction.service` exposes `extract_structured_json(raw_text, document_type, schema)`. Override or extend this service to call a local model or an external AI API without changing business modules.

## Notes

- Optional dependencies are handled gracefully. The module can install even if OCR binaries are not yet present.
- The included `stub` provider is useful for tests and dry runs without external OCR software.
- Business modules should inherit `ob.ocr.document` and override only their record preparation / creation methods.
