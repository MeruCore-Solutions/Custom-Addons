# -*- coding: utf-8 -*-
{
    "name": "OCR Supplier Quotation to Purchase Order",
    "version": "19.0.1.0.0",
    "summary": "Create draft RFQs or purchase orders from OCR supplier quotations",
    "category": "Purchase",
    "author": "OpenAI Codex",
    "license": "AGPL-3",
    "depends": [
        "ob_ocr_base",
        "purchase",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/ocr_document_type.xml",
        "data/ocr_mapping_data.xml",
        "views/purchase_order_views.xml",
        "views/ob_ocr_document_views.xml",
    ],
    "installable": True,
    "application": False,
}
