# MeruCore Intercompany Control Center - Base

## Purpose And Scope

`merucore_intercompany_base` is the foundation addon for MeruCore's future
intercompany suite on Odoo 19. It provides:

- Directional company-pair rules.
- A central intercompany transaction record.
- Immutable synchronization and issue audit events.
- Health-check and retry orchestration hooks.
- Multi-company-safe menus, views, and access rules.
- A reusable mixin for future business-document modules.

This addon intentionally does not create sales orders, purchase orders, stock
pickings, invoices, bills, payments, or journal entries.

## Supported Odoo Version And Editions

- Odoo `19.0`
- Community and Enterprise, without depending on Enterprise-only addons

## Installation

1. Add the addon path containing `merucore_intercompany_base` to `--addons-path`.
2. Update the apps list.
3. Install `merucore_intercompany_base`.

Example command: `./odoo-bin -d <database> --addons-path=/path/to/community/addons,/path/to/InterCompany -i merucore_intercompany_base`

## Configuration

1. Go to `Settings > Companies`.
2. Open a company and enable `Intercompany`.
3. Set a default responsible user if desired.
4. Open `Intercompany > Configuration > Company Pair Rules`.
5. Create a directional rule between two distinct companies.

## Security Model

- `Intercompany User`: can read transactions and events only when both companies of the pair are allowed for the current user.
- `Intercompany User`: can create and update transactions only through non-technical fields.
- `Intercompany User`: cannot create, edit, or delete rules and cannot see event technical details.
- `Intercompany Manager`: can manage rules, transactions, retries, and issue resolution within the same company-pair visibility boundaries.
- `Intercompany Manager`: cannot delete immutable audit events.
- Record rules enforce dual-company visibility on rules, transactions, and
  events.

## Extension Guide

Future modules can inherit `merucore.intercompany.mixin` on business documents
and implement retry or health hooks on transactions.

Minimal example:

`SaleOrder` can inherit both `sale.order` and `merucore.intercompany.mixin`.

`IntercompanyTransaction` can inherit `merucore.intercompany.transaction`, add `m_retry_handler_sale_purchase()`, and extend `m_collect_extension_health_issues()`.

Handler contract:

- Return `True` to mark the retry successful and finish the transaction.
- Return `False` or `None` to keep the transaction in a non-success state.
- Raise an exception to mark the retry as failed with a sanitized error message.

## Known Limitations

- The base addon provides orchestration only. Business-document generation is
  intentionally left to follow-up modules.
- Generic linked-document actions rely on the user having access to the target
  record's model and record rules.
- Health checks validate foundational consistency only; extension modules should
  add domain-specific checks.

## Upgrade Notes

- Install the base addon before any MeruCore intercompany extension addon.
- Existing extension modules should keep custom fields and methods aligned with
  the `m_` naming convention used here.

## Support

Support contact to confirm: `support@merucore.com`
