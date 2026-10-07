# -*- coding: utf-8 -*-
{
    "name": "OCR Delivery Slip",
    "version": "19.0.1.0.0",
    "summary": "Create or update stock pickings from OCR delivery slips",
    "category": "Inventory",
    "author": "OpenAI Codex",
    "license": "AGPL-3",
    "depends": [
        "ob_ocr_base",
        "stock",
        "sale",
        "purchase",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/ocr_document_type.xml",
        "data/ocr_mapping_data.xml",
        "views/stock_picking_views.xml",
        "views/ob_ocr_document_views.xml",
    ],
    "installable": True,
    "application": False,
}
