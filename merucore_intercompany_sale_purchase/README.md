# MeruCore Intercompany Sale Purchase Sync

`merucore_intercompany_sale_purchase` extends
`merucore_intercompany_base` for Odoo 19.0.

## Purpose

This addon synchronizes intercompany commercial documents inside one Odoo
database:

- Sales Order to Purchase Order
- Purchase Order to Sales Order
- Controlled manual or confirmation-time counterpart creation
- Central transaction, retry, health, and immutable event integration

It does not synchronize stock, deliveries, receipts, invoices, bills,
payments, or accounting entries.

## Dependencies

- `merucore_intercompany_base`
- `sale_management`
- `purchase`

## Configuration

1. Install the base control-center addon.
2. Enable intercompany on the participating companies.
3. Create a company-pair rule.
4. Enable `Sale & Purchase Synchronization`.
5. Configure trigger, creation timing, sync direction, product mapping, currency strategy, tax strategy, pricing, conflict handling, confirmation, and cancellation behavior.

## Workflows

### Sales Order to Purchase Order

- Create or confirm a Sales Order in the source company.
- If the rule is configured for SO triggering, the addon creates or updates one linked Purchase Order in the destination company.

### Purchase Order to Sales Order

- Create or confirm a Purchase Order in the destination company.
- If the rule is configured for PO triggering, the addon creates or updates one linked Sales Order in the source company.

## Security Model

- Reuses the base Intercompany User and Intercompany Manager groups.
- Central transactions remain visible only to users who have both companies in their allowed companies.
- Counterpart details are hidden from users who can access only one side.
- Native Sale and Purchase rights are still required in the relevant company.

## Extension Hooks

The addon extends:

- `merucore.intercompany.rule`
- `merucore.intercompany.transaction`
- `sale.order`
- `sale.order.line`
- `purchase.order`
- `purchase.order.line`

Retry and health integration reuse the base transaction hooks for the
`sale_purchase` transaction type.

## Known Limitations

- Same database only.
- Down-payment lines are blocked.
- Confirmed counterpart updates stay conservative to avoid forcing unsafe business changes.
- Product auto-creation is intentionally out of scope.

## Upgrade Notes

This addon does not change the standalone installability of
`merucore_intercompany_base`.

## Support

support@merucore.com
