from odoo import _, api, fields, models


class OcrProvider(models.Model):
    _inherit = "ob.ocr.provider"

    ai_backend = fields.Selection(
        [
            ("transformers_text", "Local Transformers (Text)"),
            ("stub", "Stub / Test Mode"),
        ],
        string="AI Backend",
        default="transformers_text",
    )
    ai_model_name = fields.Char(
        string="AI Model Name",
        default="Qwen/Qwen2.5-1.5B-Instruct",
        help="Hugging Face model name or local model path used for text-to-JSON extraction.",
    )
    ai_device = fields.Selection(
        [
            ("auto", "Auto"),
            ("cpu", "CPU"),
            ("cuda", "CUDA"),
            ("mps", "Apple Metal"),
        ],
        string="AI Device",
        default="auto",
    )
    ai_ocr_backend = fields.Selection(
        [
            ("tesseract", "Tesseract"),
            ("paddleocr", "PaddleOCR 3.x / PP-OCRv5"),
        ],
        string="OCR Backend",
        default="paddleocr",
    )
    ai_paddleocr_version = fields.Selection(
        [
            ("PP-OCRv5", "PP-OCRv5"),
            ("PP-OCRv4", "PP-OCRv4"),
        ],
        string="PaddleOCR Version",
        default="PP-OCRv5",
        help="OCR pipeline version passed to PaddleOCR. PP-OCRv5 is the recommended default for multilingual invoices and scans.",
    )
    ai_paddleocr_lang = fields.Char(
        string="PaddleOCR Language",
        default="en",
        help="PaddleOCR language abbreviation such as en, de, fr, ru, ar, or ch. Document language selection and detected language override this fallback when available.",
    )
    ai_paddleocr_detection_model_name = fields.Char(
        string="Detection Model Override",
        help="Optional PaddleOCR text detection model name. Leave empty to use the official default for the selected OCR version.",
    )
    ai_paddleocr_recognition_model_name = fields.Char(
        string="Recognition Model Override",
        help="Optional PaddleOCR text recognition model name. Leave empty to let PaddleOCR choose the model from the selected language and OCR version.",
    )
    ai_paddleocr_use_doc_orientation_classify = fields.Boolean(
        string="Detect Page Orientation",
        default=False,
        help="Enable PaddleOCR's document orientation classification stage.",
    )
    ai_paddleocr_use_doc_unwarping = fields.Boolean(
        string="Use Document Unwarping",
        default=False,
        help="Enable PaddleOCR's document unwarping stage for warped scans.",
    )
    ai_paddleocr_use_textline_orientation = fields.Boolean(
        string="Detect Textline Orientation",
        default=False,
        help="Enable PaddleOCR's textline orientation classification stage.",
    )
    ai_paddleocr_use_native_pdf_text = fields.Boolean(
        string="Merge Native PDF Text",
        default=True,
        help="When PDFs already contain embedded text, merge it with PaddleOCR output to improve references, dates, and vendor names.",
    )
    ai_context_chars = fields.Integer(
        string="Context Characters",
        default=12000,
        help="Maximum raw OCR text characters sent to the local AI model.",
    )
    ai_max_new_tokens = fields.Integer(
        string="Max New Tokens",
        default=1024,
    )
    ai_temperature = fields.Float(
        string="Temperature",
        default=0.0,
        digits=(16, 3),
    )
    ai_example_limit = fields.Integer(
        string="Feedback Examples",
        default=3,
        help="Maximum approved historical examples to add to the extraction prompt.",
    )
    ai_feedback_enabled = fields.Boolean(
        string="Use Feedback Memory",
        default=True,
        help="Reuse approved OCR examples from previous documents when building AI prompts.",
    )
    ai_additional_instructions = fields.Text(
        string="Additional AI Instructions",
        help="Extra provider-specific extraction guidance appended to the AI prompt.",
    )
    ai_runtime_status = fields.Selection(
        [
            ("ready", "Ready"),
            ("partial", "Partial"),
            ("missing_dependencies", "Missing Dependencies"),
            ("unsupported_platform", "Unsupported Platform"),
        ],
        string="Runtime Status",
        compute="_compute_ai_runtime_diagnostics",
    )
    ai_runtime_message = fields.Text(
        string="Runtime Diagnostics",
        compute="_compute_ai_runtime_diagnostics",
    )

    @api.depends(
        "provider_key",
        "ai_backend",
        "ai_ocr_backend",
        "ai_paddleocr_version",
        "ai_model_name",
        "ai_device",
        "ai_feedback_enabled",
    )
    def _compute_ai_runtime_diagnostics(self):
        runtime_service = self.env["ob.ocr.ai.runtime.service"]
        for record in self:
            diagnostics = runtime_service.get_provider_runtime_status(record)
            record.ai_runtime_status = diagnostics.get("status")
            record.ai_runtime_message = diagnostics.get("message")

    def action_validate_ai_runtime(self):
        self.ensure_one()
        diagnostics = self.env["ob.ocr.ai.runtime.service"].get_provider_runtime_status(self)
        notification_type = "success"
        if diagnostics.get("status") in ("partial", "missing_dependencies"):
            notification_type = "warning"
        elif diagnostics.get("status") == "unsupported_platform":
            notification_type = "danger"
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Local AI Runtime Check"),
                "message": diagnostics.get("message"),
                "type": notification_type,
                "sticky": diagnostics.get("status") != "ready",
            },
        }
