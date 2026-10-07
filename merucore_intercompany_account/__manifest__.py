{
    "name": "MeruCore Intercompany Invoice Bill Sync",
    "version": "19.0.1.0.0",
    "summary": "Create and govern draft intercompany invoices, bills, and refunds across company pairs",
    "category": "Accounting/Intercompany",
    "description": """
MeruCore Intercompany Invoice Bill Sync

Adds invoice, bill, and refund synchronization on top of the MeruCore
Intercompany Control Center. The addon links native Odoo accounting documents
to central intercompany transactions, applies company-pair rules and explicit
mapping tables, and creates or refreshes counterpart draft documents without
bypassing native accounting validations.

This implementation is intentionally aligned with the addons that are actually
present in this repository. It depends on `merucore_intercompany_base` and
Odoo Accounting directly, while keeping optional hooks for existing
MeruCore sale/purchase and stock addons when they are installed.
""",
    "author": "MeruCore Solutions",
    "website": "https://merucore.com",
    "license": "OPL-1",
    "depends": [
        "merucore_intercompany_base",
        "account",
    ],
    "data": [
        "security/intercompany_account_security.xml",
        "security/ir.model.access.csv",
        "views/intercompany_rule_views.xml",
        "views/intercompany_transaction_views.xml",
        "views/intercompany_mapping_views.xml",
        "views/account_move_views.xml",
        "views/intercompany_account_menus.xml",
    ],
    "installable": True,
    "application": False,
}
