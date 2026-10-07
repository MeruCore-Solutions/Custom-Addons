# MeruCore Intercompany Invoice Bill Sync

This addon extends the MeruCore intercompany suite with draft invoice, bill,
and refund synchronization between legal companies in the same Odoo 19
database.

Implemented in this repository:

- Company-pair accounting rules with explicit journal, tax, account, currency,
  posting, and draft-sync controls.
- Safe creation of counterpart draft invoices, bills, and refunds linked to
  `merucore.intercompany.transaction`.
- Explicit account, tax, and analytic mapping tables.
- Idempotent transaction reuse and counterpart refresh.
- Audit-friendly document mapping, technical sync status, and retry handlers.
- Optional manual re-sync from the accounting document or transaction.

The module relies on native Odoo accounting APIs for creation, tax
recomputation, posting, cancellation, and reversals. It does not create
payments or reconciliation entries.
