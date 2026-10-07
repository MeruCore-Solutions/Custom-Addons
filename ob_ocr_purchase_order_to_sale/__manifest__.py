# -*- coding: utf-8 -*-
{
    "name": "OCR Customer Purchase Order to Sale Order",
    "version": "19.0.1.0.0",
    "summary": "Create sale quotations or orders from OCR customer purchase orders",
    "category": "Sales",
    "author": "OpenAI Codex",
    "license": "AGPL-3",
    "depends": [
        "ob_ocr_base",
        "sale",
        "purchase",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/ocr_document_type.xml",
        "data/ocr_mapping_data.xml",
        "views/sale_order_views.xml",
        "views/ob_ocr_document_views.xml",
    ],
    "installable": True,
    "application": False,
}
