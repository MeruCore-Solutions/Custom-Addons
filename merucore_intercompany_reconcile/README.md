# MeruCore Intercompany Reconciliation & Netting

This addon extends the MeruCore intercompany suite with accounting settlement
controls for Odoo 19.0.

## Scope In This Repository

- Company-pair rule settings for matching and settlement behavior
- Operational pairing between reciprocal source and destination accounting moves
- Draft settlement proposals with approval checkpoints
- Bilateral clearing entries that reconcile only inside the owning company
- Optional native internal payments using `account.payment`
- Safe reversal support for clearing-entry settlements
- Security and audit integration with `merucore.intercompany.transaction`

## Design Notes

- The prompt for this addon references a future `merucore_intercompany_account`
  dependency. That addon is not present in this repository, so this module is
  implemented against the real dependency graph available here:
  `merucore_intercompany_base` plus Odoo `account`.
- Cross-company matching is operational only. Native reconciliation is still
  performed strictly within one company's ledger at a time.
- Draft proposals are the default. Posting remains an explicit user action even
  when a rule enables auto-post or auto-reconcile.
