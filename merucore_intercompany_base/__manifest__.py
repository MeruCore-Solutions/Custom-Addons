{
    "name": "MeruCore Intercompany Control Center - Base",
    "version": "19.0.1.0.0",
    "summary": "Intercompany control center, audit trail, retry hooks, and company-pair governance",
    "category": "Operations/Intercompany",
    "description": """
MeruCore Intercompany Control Center - Base

Foundation addon for MeruCore's intercompany suite. It provides company-pair
configuration, transaction orchestration, immutable audit events, safe retry
hooks, issue monitoring, and reusable document-link infrastructure for future
intercompany extensions.

This addon does not create intercompany sales orders, purchase orders, stock
documents, invoices, bills, payments, or journal entries.
""",
    "author": "MeruCore Solutions",
    "website": "https://merucore.com",
    "license": "OPL-1",
    "depends": [
        "base",
        "mail",
    ],
    "data": [
        "security/intercompany_security.xml",
        "security/ir.model.access.csv",
        "data/intercompany_sequence.xml",
        "data/intercompany_cron.xml",
        "views/intercompany_rule_views.xml",
        "views/intercompany_transaction_views.xml",
        "views/intercompany_event_views.xml",
        "views/res_company_views.xml",
        "views/intercompany_menus.xml",
        "wizard/intercompany_retry_wizard_views.xml",
    ],
    "installable": True,
    "application": True,
}
