# -*- coding: utf-8 -*-
{
    "name": "OCR Local AI Extraction",
    "version": "19.0.1.0.0",
    "summary": "Schema-based local AI extraction and feedback memory for OCR documents",
    "category": "Productivity",
    "author": "OpenAI Codex",
    "license": "AGPL-3",
    "depends": [
        "ob_ocr_base",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/ocr_provider_data.xml",
        "views/ob_ocr_provider_views.xml",
        "views/ob_ocr_feedback_example_views.xml",
        "views/ob_ocr_document_views.xml",
    ],
    "installable": True,
    "application": False,
}
