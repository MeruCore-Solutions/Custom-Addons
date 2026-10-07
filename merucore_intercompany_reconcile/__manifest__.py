{
    "name": "MeruCore Intercompany Reconciliation & Netting",
    "version": "19.0.1.0.0",
    "summary": "Match reciprocal intercompany balances, propose settlements, and reconcile each ledger safely",
    "category": "Accounting/Intercompany",
    "description": """
MeruCore Intercompany Reconciliation & Netting

Adds accounting-focused intercompany controls on top of the MeruCore
Intercompany Control Center. The addon helps teams pair reciprocal invoices and
bills, draft settlement proposals, post bilateral clearing or native internal
payments only after approval, and reconcile entries safely inside each legal
company.

The implementation in this repository is intentionally aligned with the addons
that are actually present here. It integrates with `merucore_intercompany_base`
and Odoo Accounting directly, while keeping optional hooks for a future
invoice/bill synchronization addon.
""",
    "author": "MeruCore Solutions",
    "website": "https://merucore.com",
    "license": "OPL-1",
    "depends": [
        "merucore_intercompany_base",
        "account",
    ],
    "data": [
        "security/intercompany_reconcile_security.xml",
        "security/ir.model.access.csv",
        "data/intercompany_reconcile_sequence.xml",
        "views/intercompany_rule_views.xml",
        "views/intercompany_transaction_views.xml",
        "views/intercompany_match_views.xml",
        "views/intercompany_settlement_views.xml",
        "views/account_move_views.xml",
        "views/intercompany_reconcile_menus.xml",
    ],
    "installable": True,
    "application": False,
}
