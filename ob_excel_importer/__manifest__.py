# -*- coding: utf-8 -*-
{
    "name": "OB Excel Importer",
    "version": "19.0.1.0.0",
    "summary": "Generic Excel Importer with Field Mapping, FTP Import, Failed Line Re-import, and Dynamic Logic",
    "category": "Tools",
    "author": "OB",
    "license": "LGPL-3",
    "depends": [
        "base",
        "mail",
    ],
    "external_dependencies": {
        "python": ["openpyxl"],
    },
    "data": [
        "security/security.xml",
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "views/menu.xml",
        "views/excel_import_template_views.xml",
        "views/excel_import_log_views.xml",
        "views/excel_import_failed_line_views.xml",
        "views/excel_import_post_process_views.xml",
    ],
    "application": True,
    "installable": True,
}
