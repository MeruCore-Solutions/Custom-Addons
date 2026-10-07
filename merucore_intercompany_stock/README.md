# MeruCore Intercompany Stock Sync

This addon extends the MeruCore intercompany suite with stock-focused flows for
Odoo 19.0.

## Scope

- Automatic counterpart receipt creation from validated outgoing pickings
- Manual intercompany stock transfer requests that generate paired pickings
- Central transaction traceability through `merucore.intercompany.transaction`
- Lot, serial, owner, and package propagation where applicable
- Optional parent-transaction linkage when related sale or purchase flows are installed

## Design Notes

- Manifest dependencies stay limited to `merucore_intercompany_base` and `stock`
  so the module remains installable even when optional sale flows are unavailable.
- Automatic synchronization is driven from completed outgoing pickings. This
  keeps partial deliveries, backorders, and returns aligned with the real stock
  movement that was actually validated.
- Manual transfer requests create both source and destination pickings up front
  and link them to one intercompany stock transaction.
