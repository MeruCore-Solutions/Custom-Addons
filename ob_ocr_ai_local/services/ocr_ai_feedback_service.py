import re

from odoo import fields, models


class OCRAIFeedbackService(models.AbstractModel):
    _name = "ob.ocr.ai.feedback.service"
    _description = "OCR AI Feedback Service"

    def capture_from_documents(self, documents):
        example_model = self.env["ob.ocr.feedback.example"]
        for document in documents:
            if not document.reviewed or not document.extracted_json or not document.raw_text:
                continue
            values = self._prepare_example_values(document)
            example = example_model.search([("document_id", "=", document.id)], limit=1)
            if example:
                example.write(values)
            else:
                example_model.create(values)
        return True

    def find_examples(self, document, provider=None, limit=None):
        limit = limit or max((provider.ai_example_limit if provider else 0), 0) or 3
        if limit <= 0 or not document.document_type_id:
            return self.env["ob.ocr.feedback.example"]

        candidates = self.env["ob.ocr.feedback.example"].search([
            ("active", "=", True),
            ("document_type_id", "=", document.document_type_id.id),
            ("document_id", "!=", document.id),
            "|",
            ("company_id", "=", False),
            ("company_id", "=", document.company_id.id),
        ])
        scored = sorted(
            ((self._score_example(example, document, provider=provider), example) for example in candidates),
            key=lambda item: (-item[0], -item[1].use_count, item[1].id),
        )
        return self.env["ob.ocr.feedback.example"].browse([
            example.id for score, example in scored if score > 0
        ][:limit])

    def mark_examples_used(self, examples):
        now = fields.Datetime.now()
        for example in examples:
            example.write({
                "use_count": example.use_count + 1,
                "last_used_date": now,
            })
        return True

    def _prepare_example_values(self, document):
        payload = document.extracted_json or {}
        return {
            "name": "%s [%s]" % (document.name, document.document_type or "ocr"),
            "company_id": document.company_id.id,
            "document_type_id": document.document_type_id.id,
            "provider_id": document.ocr_provider_id.id,
            "document_id": document.id,
            "related_model": document.related_model,
            "related_res_id": document.related_res_id,
            "language": document.language or document.detected_language,
            "partner_name": self._extract_partner_name(payload),
            "reference_text": self._extract_reference_text(payload),
            "raw_text": document.raw_text,
            "extracted_json": payload,
            "note": document.review_note,
        }

    def _score_example(self, example, document, provider=None):
        score = 10
        raw_text = self._normalize(document.raw_text or "")
        detected_language = (document.language or document.detected_language or "").strip().lower()

        if provider and example.provider_id == provider:
            score += 10
        if detected_language and example.language and example.language.strip().lower() == detected_language:
            score += 15
        if example.partner_name and self._normalize(example.partner_name) in raw_text:
            score += 40
        if example.reference_text and self._normalize(example.reference_text) in raw_text:
            score += 20
        if not raw_text:
            score = 0
        return score

    def _extract_partner_name(self, payload):
        for key in ("vendor_name", "customer_name", "partner_name"):
            if payload.get(key):
                return payload.get(key)
        return False

    def _extract_reference_text(self, payload):
        for key in (
            "bill_number",
            "quotation_number",
            "po_number",
            "customer_reference",
            "delivery_slip_number",
            "payment_reference",
            "source_document",
        ):
            if payload.get(key):
                return payload.get(key)
        return False

    def _normalize(self, value):
        return re.sub(r"\s+", " ", (value or "").strip().lower())
