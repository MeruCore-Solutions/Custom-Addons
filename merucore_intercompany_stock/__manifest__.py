{
    "name": "MeruCore Intercompany Stock Sync",
    "version": "19.0.1.0.0",
    "summary": "Synchronize intercompany stock transfers, receipts, and manual transfer requests",
    "category": "Inventory/Intercompany",
    "description": """
MeruCore Intercompany Stock Sync

Adds stock-focused intercompany orchestration on top of the MeruCore
Intercompany Control Center. It supports outbound-to-inbound stock pairing,
traceable transaction links, manual transfer requests, lot and package
propagation, and retryable counterpart document creation between companies in
the same Odoo database.

This addon intentionally keeps sale and purchase integration optional so it can
run independently from the stock application.
""",
    "author": "MeruCore Solutions",
    "website": "https://merucore.com",
    "license": "OPL-1",
    "depends": [
        "merucore_intercompany_base",
        "stock",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/intercompany_stock_transfer_sequence.xml",
        "views/intercompany_rule_views.xml",
        "views/intercompany_transaction_views.xml",
        "views/intercompany_stock_transfer_views.xml",
        "views/stock_picking_views.xml",
    ],
    "installable": True,
    "application": False,
}
