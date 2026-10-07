{
    "name": "MeruCore Intercompany Sale Purchase Sync",
    "version": "19.0.1.0.0",
    "summary": "Synchronize intercompany sales and purchase orders within one Odoo database",
    "category": "Sales/Intercompany",
    "description": """
MeruCore Intercompany Sale Purchase Sync

Automates intercompany Sales Order and Purchase Order pairing between two
companies in the same Odoo database. It creates or links one central
intercompany transaction, supports controlled synchronization, conflict
review, retries, and audit visibility through MeruCore Intercompany Control
Center.

Scope is limited to quotation and order level synchronization. Stock,
invoices, bills, payments, and accounting eliminations belong to separate
extensions.
""",
    "author": "MeruCore Solutions",
    "website": "https://merucore.com",
    "license": "OPL-1",
    "depends": [
        "merucore_intercompany_base",
        "sale_management",
        "purchase",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/intercompany_rule_views.xml",
        "views/intercompany_transaction_views.xml",
        "views/sale_order_views.xml",
        "views/purchase_order_views.xml",
        "wizard/intercompany_sync_preview_views.xml",
    ],
    "installable": True,
    "application": False,
}
