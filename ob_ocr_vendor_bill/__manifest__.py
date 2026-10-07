# -*- coding: utf-8 -*-
{
    "name": "OCR Vendor Bill",
    "version": "19.0.1.0.0",
    "summary": "Create draft vendor bills from OCR documents",
    "category": "Accounting",
    "author": "OpenAI Codex",
    "license": "AGPL-3",
    "depends": [
        "ob_ocr_base",
        "account",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/ocr_document_type.xml",
        "data/ocr_mapping_data.xml",
        "views/account_move_views.xml",
        "views/ob_ocr_document_views.xml",
    ],
    "installable": True,
    "application": False,
}
