# -*- coding: utf-8 -*-
{
    "name": "OCR Framework Base",
    "version": "19.0.1.0.0",
    "summary": "Modular OCR framework for document ingestion, extraction, review, and record creation",
    "category": "Productivity",
    "author": "OpenAI Codex",
    "license": "AGPL-3",
    "depends": [
        "base_setup",
        "mail",
    ],
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/ir_sequence.xml",
        "data/ir_cron.xml",
        "data/ocr_document_type_data.xml",
        "data/ocr_provider_data.xml",
        "views/ob_ocr_document_views.xml",
        "views/ob_ocr_provider_views.xml",
        "views/ob_ocr_mapping_views.xml",
        "views/res_config_settings_views.xml",
        "views/menu_views.xml",
    ],
    "demo": [
        "demo/ocr_demo.xml",
        "demo/ocr_mapping_demo.xml",
    ],
    "installable": True,
    "application": True,
}
