import json
import uuid

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.float_utils import float_compare


class MeruCoreIntercompanyTransaction(models.Model):
    _inherit = "merucore.intercompany.transaction"

    m_sale_order_id = fields.Many2one(
        "sale.order",
        copy=False,
        index=True,
        check_company=False,
    )
    m_purchase_order_id = fields.Many2one(
        "purchase.order",
        copy=False,
        index=True,
        check_company=False,
    )
    m_sale_company_id = fields.Many2one(
        "res.company",
        related="m_sale_order_id.company_id",
        store=True,
        readonly=True,
    )
    m_purchase_company_id = fields.Many2one(
        "res.company",
        related="m_purchase_order_id.company_id",
        store=True,
        readonly=True,
    )
    m_sale_state = fields.Selection(
        related="m_sale_order_id.state",
        string="Sales Order State",
        readonly=True,
    )
    m_purchase_state = fields.Selection(
        related="m_purchase_order_id.state",
        string="Purchase Order State",
        readonly=True,
    )
    m_sale_amount_total = fields.Monetary(
        related="m_sale_order_id.amount_total",
        currency_field="m_sale_currency_id",
        readonly=True,
    )
    m_purchase_amount_total = fields.Monetary(
        related="m_purchase_order_id.amount_total",
        currency_field="m_purchase_currency_id",
        readonly=True,
    )
    m_sale_currency_id = fields.Many2one(
        "res.currency",
        related="m_sale_order_id.currency_id",
        readonly=True,
    )
    m_purchase_currency_id = fields.Many2one(
        "res.currency",
        related="m_purchase_order_id.currency_id",
        readonly=True,
    )
    m_amount_difference = fields.Monetary(
        compute="m_compute_amount_difference",
        currency_field="m_sale_currency_id",
        store=True,
    )
    m_currency_mismatch = fields.Boolean(
        compute="m_compute_amount_difference",
        store=True,
    )
    m_line_mismatch_count = fields.Integer(
        compute="m_compute_line_mismatch_count",
        store=True,
    )
    m_last_sale_write_at = fields.Datetime(copy=False)
    m_last_purchase_write_at = fields.Datetime(copy=False)
    m_last_sync_token = fields.Char(copy=False)
    m_sync_version = fields.Integer(default=0, copy=False, readonly=True)
    m_pending_conflict = fields.Boolean(default=False, copy=False, index=True, readonly=True)
    m_counterpart_creation_state = fields.Selection(
        selection=[
            ("not_created", "Not Created"),
            ("creating", "Creating"),
            ("created", "Created"),
            ("failed", "Failed"),
        ],
        default="not_created",
        copy=False,
        readonly=True,
    )

    def init(self):
        super().init()
        self.env.cr.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
                merucore_intercompany_tx_sale_order_uniq
            ON merucore_intercompany_transaction (m_sale_order_id)
            WHERE m_transaction_type = 'sale_purchase'
              AND m_sale_order_id IS NOT NULL
              AND COALESCE(m_state, '') <> 'cancelled'
            """
        )
        self.env.cr.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
                merucore_intercompany_tx_purchase_order_uniq
            ON merucore_intercompany_transaction (m_purchase_order_id)
            WHERE m_transaction_type = 'sale_purchase'
              AND m_purchase_order_id IS NOT NULL
              AND COALESCE(m_state, '') <> 'cancelled'
            """
        )

    @api.depends(
        "m_sale_order_id.amount_total",
        "m_purchase_order_id.amount_total",
        "m_sale_order_id.currency_id",
        "m_purchase_order_id.currency_id",
    )
    def m_compute_amount_difference(self):
        for transaction in self:
            transaction.m_currency_mismatch = bool(
                transaction.m_sale_currency_id
                and transaction.m_purchase_currency_id
                and transaction.m_sale_currency_id != transaction.m_purchase_currency_id
            )
            if (
                transaction.m_sale_currency_id
                and transaction.m_purchase_currency_id
                and transaction.m_sale_currency_id == transaction.m_purchase_currency_id
            ):
                transaction.m_amount_difference = (
                    transaction.m_sale_amount_total - transaction.m_purchase_amount_total
                )
            else:
                transaction.m_amount_difference = 0.0

    @api.depends(
        "m_sale_order_id.order_line.m_intercompany_line_key",
        "m_sale_order_id.order_line.product_uom_qty",
        "m_sale_order_id.order_line.price_unit",
        "m_purchase_order_id.order_line.m_intercompany_line_key",
        "m_purchase_order_id.order_line.product_qty",
        "m_purchase_order_id.order_line.price_unit",
    )
    def m_compute_line_mismatch_count(self):
        for transaction in self:
            issues = transaction.m_collect_sale_purchase_line_issues()
            transaction.m_line_mismatch_count = len(issues)

    @api.constrains("m_sale_order_id", "m_purchase_order_id", "m_rule_id", "m_transaction_type")
    def m_check_sale_purchase_links(self):
        for transaction in self.filtered(lambda tx: tx.m_transaction_type == "sale_purchase"):
            if transaction.m_sale_order_id and transaction.m_sale_order_id.company_id != transaction.m_rule_id.m_source_company_id:
                raise ValidationError(_("The linked sales order must belong to the source company of the rule."))
            if transaction.m_purchase_order_id and transaction.m_purchase_order_id.company_id != transaction.m_rule_id.m_destination_company_id:
                raise ValidationError(_("The linked purchase order must belong to the destination company of the rule."))

    def m_action_open_sale_order(self):
        self.ensure_one()
        if not self.m_sale_order_id:
            raise UserError(_("There is no linked sales order."))
        return self.m_action_open_document("source")

    def m_action_open_purchase_order(self):
        self.ensure_one()
        if not self.m_purchase_order_id:
            raise UserError(_("There is no linked purchase order."))
        return self.m_action_open_document("destination")

    @api.model
    def m_build_sale_purchase_idempotency_key(self, m_rule, m_sale_order=False, m_purchase_order=False):
        if m_sale_order:
            return f"sale_purchase:rule:{m_rule.id}:sale:{m_sale_order.id}"
        if m_purchase_order:
            return f"sale_purchase:rule:{m_rule.id}:purchase:{m_purchase_order.id}"
        raise ValidationError(_("An originating sales order or purchase order is required."))

    @api.model
    def m_get_sale_purchase_transaction(
        self,
        m_rule,
        m_sale_order=False,
        m_purchase_order=False,
    ):
        if m_sale_order and m_sale_order.m_intercompany_transaction_id:
            return m_sale_order.m_intercompany_transaction_id
        if m_purchase_order and m_purchase_order.m_intercompany_transaction_id:
            return m_purchase_order.m_intercompany_transaction_id
        domain = [("m_transaction_type", "=", "sale_purchase"), ("m_rule_id", "=", m_rule.id)]
        if m_sale_order:
            domain.append(("m_sale_order_id", "=", m_sale_order.id))
        if m_purchase_order:
            domain.append(("m_purchase_order_id", "=", m_purchase_order.id))
        transaction = self.search(domain, limit=1)
        if transaction:
            return transaction
        idempotency_key = self.m_build_sale_purchase_idempotency_key(
            m_rule,
            m_sale_order=m_sale_order,
            m_purchase_order=m_purchase_order,
        )
        transaction = self.search([("m_idempotency_key", "=", idempotency_key)], limit=1)
        if transaction:
            return transaction
        vals = {}
        if m_sale_order:
            vals.update(m_sale_order.m_prepare_intercompany_transaction_values(m_rule))
        elif m_purchase_order:
            vals.update(m_purchase_order.m_prepare_intercompany_transaction_values(m_rule))
        vals.update(
            {
                "m_idempotency_key": idempotency_key,
                "m_counterpart_creation_state": "not_created",
                "m_state": "draft",
            }
        )
        try:
            transaction = self.with_context(m_intercompany_internal_write=True).create(vals)
        except ValidationError:
            transaction = self.search([("m_idempotency_key", "=", idempotency_key)], limit=1)
            if not transaction:
                raise
        return transaction

    @api.model
    def m_get_actor_environment(self, m_user, m_model_name, m_company, m_allowed_company_ids):
        return (
            self.env[m_model_name]
            .with_user(m_user)
            .with_company(m_company)
            .with_context(
                allowed_company_ids=m_allowed_company_ids,
                m_skip_intercompany_sync=True,
            )
        )

    @api.model
    def m_get_counterpart_actor(
        self,
        m_rule,
        m_model_name,
        m_company,
        m_operation,
        m_automatic=False,
    ):
        allowed_company_ids = [m_rule.m_source_company_id.id, m_rule.m_destination_company_id.id]
        actor = self.env.user
        if m_automatic:
            actor = m_rule.m_responsible_user_id or self.env.user
        if m_company not in actor.company_ids:
            raise AccessError(_("The selected user does not have access to the destination company."))
        if m_rule.m_source_company_id not in actor.company_ids or m_rule.m_destination_company_id not in actor.company_ids:
            raise AccessError(_("The selected user must have access to both companies in the company pair."))
        actor_env = self.m_get_actor_environment(actor, m_model_name, m_company, m_allowed_company_ids=allowed_company_ids)
        actor_env.check_access_rights(m_operation)
        return actor, actor_env

    @api.model
    def m_resolve_purchase_partner_from_sale(self, m_rule):
        partner = m_rule.m_source_company_id.partner_id.commercial_partner_id
        if not partner or not partner.active:
            raise ValidationError(_("The source company partner is missing or archived."))
        return partner

    @api.model
    def m_resolve_sale_partner_from_purchase(self, m_rule):
        partner = m_rule.m_destination_company_id.partner_id.commercial_partner_id
        if not partner or not partner.active:
            raise ValidationError(_("The destination company partner is missing or archived."))
        return partner

    @api.model
    def m_resolve_counterpart_currency(self, m_rule, m_source_order, m_destination_company, m_destination_model_name, m_partner):
        if m_rule.m_currency_strategy == "source_document_currency":
            return m_source_order.currency_id
        if m_rule.m_currency_strategy == "destination_pricelist_currency" and m_destination_model_name == "sale.order":
            pricelist = m_partner.with_company(m_destination_company).property_product_pricelist
            if pricelist:
                return pricelist.currency_id
        return m_destination_company.currency_id

    @api.model
    def m_resolve_destination_pricelist(self, m_destination_company, m_partner):
        return m_partner.with_company(m_destination_company).property_product_pricelist

    @api.model
    def m_resolve_counterpart_product(
        self,
        m_rule,
        m_source_line,
        m_destination_company,
        m_destination_model_name,
    ):
        if m_source_line.display_type:
            return False
        source_product = m_source_line.product_id
        if not source_product:
            raise ValidationError(_("Product lines require a product to synchronize."))
        search_domain = []
        if m_destination_model_name == "purchase.order":
            search_domain.append(("purchase_ok", "=", True))
        else:
            search_domain.append(("sale_ok", "=", True))
        search_domain.extend(["|", ("company_id", "=", False), ("company_id", "=", m_destination_company.id)])
        if m_rule.m_product_mapping_strategy == "same_product":
            product = source_product
            if product.company_id and product.company_id != m_destination_company:
                accessible = (
                    product.company_id._accessible_branches()
                    if hasattr(product.company_id, "_accessible_branches")
                    else product.company_id
                )
                if m_destination_company not in accessible:
                    raise ValidationError(
                        _("Product %(product)s is not compatible with company %(company)s.",
                          product=product.display_name,
                          company=m_destination_company.display_name)
                    )
            return product
        if m_rule.m_product_mapping_strategy == "internal_reference":
            if not source_product.default_code:
                raise ValidationError(_("Internal-reference mapping requires a product internal reference."))
            search_domain.append(("default_code", "=", source_product.default_code))
        else:
            if not source_product.barcode:
                raise ValidationError(_("Barcode mapping requires a product barcode."))
            search_domain.append(("barcode", "=", source_product.barcode))
        matches = self.env["product.product"].search(search_domain)
        if not matches:
            raise ValidationError(
                _("No counterpart product mapping was found for %(product)s.", product=source_product.display_name)
            )
        if len(matches) > 1:
            raise ValidationError(
                _("Multiple counterpart products match %(product)s.", product=source_product.display_name)
            )
        return matches

    @api.model
    def m_resolve_counterpart_uom(self, m_rule, m_source_line, m_destination_product):
        if m_source_line.display_type:
            return False
        source_uom = m_source_line.product_uom_id
        destination_uom = m_destination_product.uom_id
        if not source_uom or not destination_uom:
            raise ValidationError(_("Both source and destination products need a unit of measure."))
        if not source_uom._has_common_reference(destination_uom):
            raise ValidationError(_("The source and destination units of measure must share the same category."))
        return source_uom if m_rule.m_sync_uom else destination_uom

    @api.model
    def m_get_source_line_quantity(self, m_source_line):
        return (
            m_source_line.product_uom_qty
            if m_source_line._name == "sale.order.line"
            else m_source_line.product_qty
        )

    @api.model
    def m_get_sale_line_planned_date(self, m_sale_line):
        if m_sale_line.order_id.commitment_date:
            return m_sale_line.order_id.commitment_date
        date_order = m_sale_line.order_id.date_order or fields.Datetime.now()
        return fields.Datetime.add(date_order, days=m_sale_line.customer_lead or 0.0)

    @api.model
    def m_resolve_counterpart_taxes(
        self,
        m_rule,
        m_destination_product,
        m_destination_order,
    ):
        if not m_destination_product:
            return self.env["account.tax"]
        if m_rule.m_tax_strategy == "no_taxes":
            return self.env["account.tax"]
        taxes = (
            m_destination_product.supplier_taxes_id._filter_taxes_by_company(m_destination_order.company_id)
            if m_destination_order._name == "purchase.order"
            else m_destination_product.taxes_id._filter_taxes_by_company(m_destination_order.company_id)
        )
        if m_rule.m_tax_strategy == "destination_fiscal_position":
            fpos = m_destination_order.fiscal_position_id
            if not fpos and hasattr(fpos, "_get_fiscal_position"):
                fpos = fpos._get_fiscal_position(m_destination_order.partner_id)
            if fpos:
                taxes = fpos.map_tax(taxes, m_destination_product, m_destination_order.partner_id)
        return taxes

    @api.model
    def m_compute_intercompany_unit_price(
        self,
        m_rule,
        m_source_line,
        m_destination_order,
        m_destination_product,
        m_destination_uom,
    ):
        if m_source_line.display_type:
            return 0.0
        business_date = (
            (m_destination_order.date_order or fields.Datetime.now()).date()
            if hasattr(m_destination_order, "date_order")
            else fields.Date.today()
        )
        if m_rule.m_price_strategy in {"product_cost", "cost_plus"}:
            cost_currency = getattr(m_destination_product, "cost_currency_id", m_destination_order.company_id.currency_id)
            price = m_destination_product.with_company(m_destination_order.company_id).standard_price
            if m_rule.m_price_strategy == "cost_plus":
                price *= 1.0 + (m_rule.m_cost_plus_percentage / 100.0)
            price = cost_currency._convert(
                price,
                m_destination_order.currency_id,
                m_destination_order.company_id,
                business_date,
                round=False,
            )
            return m_destination_product.uom_id._compute_price(price, m_destination_uom)
        source_price = m_source_line.price_unit
        if not m_rule.m_sync_discounts and getattr(m_source_line, "discount", 0.0):
            source_price *= 1.0 - (m_source_line.discount / 100.0)
        price = m_source_line.product_uom_id._compute_price(source_price, m_destination_uom)
        return m_source_line.currency_id._convert(
            price,
            m_destination_order.currency_id,
            m_destination_order.company_id,
            business_date,
            round=False,
        )

    @api.model
    def m_prepare_purchase_line_values_from_sale(
        self,
        m_rule,
        m_sale_line,
        m_purchase_order,
    ):
        values = {
            "m_intercompany_line_key": m_sale_line.m_intercompany_line_key or uuid.uuid4().hex,
            "sequence": m_sale_line.sequence,
            "display_type": m_sale_line.display_type or False,
        }
        if m_sale_line.display_type:
            values["name"] = m_sale_line.name
            return values
        product = self.m_resolve_counterpart_product(
            m_rule,
            m_sale_line,
            m_purchase_order.company_id,
            "purchase.order",
        )
        uom = self.m_resolve_counterpart_uom(m_rule, m_sale_line, product)
        quantity = m_sale_line.product_uom_id._compute_quantity(
            m_sale_line.product_uom_qty,
            uom,
        )
        values.update(
            {
                "product_id": product.id,
                "product_uom_id": uom.id,
                "product_qty": quantity,
                "name": m_sale_line.name if m_rule.m_sync_descriptions else product.display_name,
                "date_planned": self.m_get_sale_line_planned_date(m_sale_line)
                if m_rule.m_sync_planned_dates
                else False,
                "tax_ids": [(6, 0, self.m_resolve_counterpart_taxes(m_rule, product, m_purchase_order).ids)],
            }
        )
        if m_rule.m_price_strategy != "destination_pricelist":
            values["price_unit"] = self.m_compute_intercompany_unit_price(
                m_rule,
                m_sale_line,
                m_purchase_order,
                product,
                uom,
            )
        if m_rule.m_sync_discounts:
            values["discount"] = m_sale_line.discount
        return values

    @api.model
    def m_prepare_sale_line_values_from_purchase(
        self,
        m_rule,
        m_purchase_line,
        m_sale_order,
    ):
        values = {
            "m_intercompany_line_key": m_purchase_line.m_intercompany_line_key or uuid.uuid4().hex,
            "sequence": m_purchase_line.sequence,
            "display_type": m_purchase_line.display_type or False,
        }
        if m_purchase_line.display_type:
            values["name"] = m_purchase_line.name
            return values
        product = self.m_resolve_counterpart_product(
            m_rule,
            m_purchase_line,
            m_sale_order.company_id,
            "sale.order",
        )
        uom = self.m_resolve_counterpart_uom(m_rule, m_purchase_line, product)
        quantity = m_purchase_line.product_uom_id._compute_quantity(
            m_purchase_line.product_qty,
            uom,
        )
        values.update(
            {
                "product_id": product.id,
                "product_uom_id": uom.id,
                "product_uom_qty": quantity,
                "name": m_purchase_line.name if m_rule.m_sync_descriptions else product.display_name,
                "tax_ids": [(6, 0, self.m_resolve_counterpart_taxes(m_rule, product, m_sale_order).ids)],
            }
        )
        if m_rule.m_price_strategy != "destination_pricelist":
            values["price_unit"] = self.m_compute_intercompany_unit_price(
                m_rule,
                m_purchase_line,
                m_sale_order,
                product,
                uom,
            )
        if m_rule.m_sync_discounts:
            values["discount"] = m_purchase_line.discount
        return values

    @api.model
    def m_prepare_purchase_values_from_sale(self, m_rule, m_sale_order, m_purchase_order=False):
        partner = self.m_resolve_purchase_partner_from_sale(m_rule)
        currency = self.m_resolve_counterpart_currency(
            m_rule,
            m_sale_order,
            m_rule.m_destination_company_id,
            "purchase.order",
            partner,
        )
        values = {
            "company_id": m_rule.m_destination_company_id.id,
            "partner_id": partner.id,
            "currency_id": currency.id,
            "date_order": m_sale_order.date_order or fields.Datetime.now(),
            "origin": m_sale_order.name,
            "user_id": m_rule.m_responsible_user_id.id or self.env.user.id,
            "m_intercompany_origin_company_id": m_sale_order.company_id.id,
        }
        if m_rule.m_sync_header_values:
            values["note"] = m_sale_order.note
            if m_sale_order.client_order_ref:
                values["partner_ref"] = m_sale_order.client_order_ref
        line_values = [
            self.m_prepare_purchase_line_values_from_sale(m_rule, line, m_purchase_order or self.env["purchase.order"].new(values))
            for line in m_sale_order.order_line.sorted("sequence")
        ]
        return values, line_values

    @api.model
    def m_prepare_sale_values_from_purchase(self, m_rule, m_purchase_order, m_sale_order=False):
        partner = self.m_resolve_sale_partner_from_purchase(m_rule)
        pricelist = self.m_resolve_destination_pricelist(m_rule.m_source_company_id, partner)
        currency = self.m_resolve_counterpart_currency(
            m_rule,
            m_purchase_order,
            m_rule.m_source_company_id,
            "sale.order",
            partner,
        )
        values = {
            "company_id": m_rule.m_source_company_id.id,
            "partner_id": partner.id,
            "currency_id": currency.id,
            "date_order": m_purchase_order.date_order or fields.Datetime.now(),
            "origin": m_purchase_order.name,
            "user_id": m_rule.m_responsible_user_id.id or self.env.user.id,
            "m_intercompany_origin_company_id": m_purchase_order.company_id.id,
        }
        if pricelist:
            values["pricelist_id"] = pricelist.id
        if m_rule.m_sync_header_values:
            values["note"] = m_purchase_order.note
            if m_purchase_order.partner_ref:
                values["client_order_ref"] = m_purchase_order.partner_ref
        if m_rule.m_sync_planned_dates:
            planned_dates = m_purchase_order.order_line.filtered(lambda line: not line.display_type).mapped("date_planned")
            values["commitment_date"] = min(planned_dates) if planned_dates else False
        line_values = [
            self.m_prepare_sale_line_values_from_purchase(m_rule, line, m_sale_order or self.env["sale.order"].new(values))
            for line in m_purchase_order.order_line.sorted("sequence")
        ]
        return values, line_values

    @api.model
    def m_get_diffable_fields(self, m_destination_model_name, m_rule):
        fields_by_model = {
            "purchase.order": {
                "header": ["partner_id", "currency_id", "date_order", "origin", "note", "partner_ref"],
                "line": ["display_type", "product_id", "product_uom_id", "product_qty", "name", "sequence", "date_planned", "price_unit", "discount", "tax_ids"],
                "line_qty_field": "product_qty",
            },
            "sale.order": {
                "header": ["partner_id", "currency_id", "date_order", "origin", "note", "client_order_ref", "commitment_date", "pricelist_id"],
                "line": ["display_type", "product_id", "product_uom_id", "product_uom_qty", "name", "sequence", "price_unit", "discount", "tax_ids"],
                "line_qty_field": "product_uom_qty",
            },
        }
        return fields_by_model[m_destination_model_name]

    @api.model
    def m_normalize_field_value(self, m_record, m_field_name, m_value):
        if m_field_name in {"partner_id", "currency_id", "product_id", "product_uom_id", "pricelist_id"}:
            return m_value.id if m_value else False
        if m_field_name == "tax_ids":
            return tuple(sorted(m_value.ids if hasattr(m_value, "ids") else m_value[0][2]))
        if m_field_name in {"price_unit", "discount", "product_qty", "product_uom_qty"}:
            return round(float(m_value or 0.0), 6)
        return m_value or False

    @api.model
    def m_collect_preview_differences(self, m_destination_order, m_header_values, m_line_values):
        differences = []
        fields_meta = self.m_get_diffable_fields(m_destination_order._name, False)
        for field_name in fields_meta["header"]:
            if field_name not in m_header_values:
                continue
            current_value = self.m_normalize_field_value(m_destination_order, field_name, m_destination_order[field_name])
            desired_value = self.m_normalize_field_value(m_destination_order, field_name, m_header_values[field_name])
            if current_value != desired_value:
                differences.append(
                    {
                        "action": "update",
                        "target": "header",
                        "field": field_name,
                        "old": current_value,
                        "new": desired_value,
                        "destructive": field_name == "partner_id",
                    }
                )
        current_lines = {
            line.m_intercompany_line_key: line
            for line in m_destination_order.order_line
            if line.m_intercompany_line_key
        }
        desired_keys = set()
        for line_value in m_line_values:
            line_key = line_value["m_intercompany_line_key"]
            desired_keys.add(line_key)
            current_line = current_lines.get(line_key)
            if not current_line:
                differences.append(
                    {
                        "action": "create",
                        "target": "line",
                        "field": line_key,
                        "old": False,
                        "new": line_value.get("name") or line_value.get("product_id"),
                        "destructive": False,
                    }
                )
                continue
            for field_name in fields_meta["line"]:
                if field_name not in line_value:
                    continue
                current_value = self.m_normalize_field_value(current_line, field_name, current_line[field_name])
                desired_value = self.m_normalize_field_value(current_line, field_name, line_value[field_name])
                if current_value != desired_value:
                    differences.append(
                        {
                            "action": "update",
                            "target": "line",
                            "field": f"{line_key}:{field_name}",
                            "old": current_value,
                            "new": desired_value,
                            "destructive": field_name in {"product_id", "product_uom_id"},
                        }
                    )
        for line_key in set(current_lines) - desired_keys:
            differences.append(
                {
                    "action": "delete",
                    "target": "line",
                    "field": line_key,
                    "old": current_lines[line_key].display_name,
                    "new": False,
                    "destructive": True,
                }
            )
        return differences

    @api.model
    def m_check_confirmation_sync_policy(self, m_rule, m_destination_order, m_differences):
        if not m_differences:
            return
        state = m_destination_order.state
        locked_state = state in {"sale", "purchase"}
        if not locked_state:
            return
        if not m_rule.m_allow_sync_after_confirmation:
            raise UserError(_("Confirmed counterpart documents cannot be updated by this rule."))
        unsafe_fields = {
            difference["field"]
            for difference in m_differences
            if difference["target"] == "line" or difference["field"] in {"partner_id", "currency_id", "pricelist_id"}
        }
        if unsafe_fields:
            raise UserError(_("Only conservative post-confirmation updates are allowed; the requested changes are unsafe."))

    @api.model
    def m_apply_payload_to_counterpart(
        self,
        m_rule,
        m_destination_order,
        m_header_values,
        m_line_values,
    ):
        differences = self.m_collect_preview_differences(m_destination_order, m_header_values, m_line_values)
        self.m_check_confirmation_sync_policy(m_rule, m_destination_order, differences)
        if m_rule.m_sync_header_values:
            header_payload = {
                key: value
                for key, value in m_header_values.items()
                if key in self.m_get_diffable_fields(m_destination_order._name, m_rule)["header"]
            }
            if header_payload:
                m_destination_order.write(header_payload)
        existing_lines = {
            line.m_intercompany_line_key: line
            for line in m_destination_order.order_line
            if line.m_intercompany_line_key
        }
        desired_keys = set()
        line_model = self.env["purchase.order.line"] if m_destination_order._name == "purchase.order" else self.env["sale.order.line"]
        for line_value in m_line_values:
            line_key = line_value["m_intercompany_line_key"]
            desired_keys.add(line_key)
            current_line = existing_lines.get(line_key)
            if not current_line:
                if existing_lines and not m_rule.m_allow_counterpart_line_creation:
                    raise UserError(_("This rule does not allow creating additional counterpart lines."))
                create_values = dict(line_value, order_id=m_destination_order.id)
                line_model.with_context(m_skip_intercompany_sync=True).create(create_values)
                continue
            update_values = {}
            for field_name in self.m_get_diffable_fields(m_destination_order._name, m_rule)["line"]:
                if field_name not in line_value:
                    continue
                current_value = self.m_normalize_field_value(current_line, field_name, current_line[field_name])
                desired_value = self.m_normalize_field_value(current_line, field_name, line_value[field_name])
                if current_value == desired_value:
                    continue
                if field_name == "tax_ids":
                    update_values[field_name] = [(6, 0, line_value[field_name][0][2])]
                else:
                    update_values[field_name] = line_value[field_name]
            if update_values:
                current_line.with_context(m_skip_intercompany_sync=True).write(update_values)
        orphan_lines = [line for key, line in existing_lines.items() if key not in desired_keys]
        if orphan_lines:
            if not m_rule.m_allow_counterpart_line_deletion:
                raise UserError(_("This rule does not allow deleting counterpart lines."))
            self.env["purchase.order.line" if m_destination_order._name == "purchase.order" else "sale.order.line"].browse(
                [line.id for line in orphan_lines]
            ).with_context(m_skip_intercompany_sync=True).unlink()
        return differences

    @api.model
    def m_build_order_snapshot(self, m_order):
        lines = []
        for line in m_order.order_line.sorted("sequence"):
            quantity = line.product_uom_qty if line._name == "sale.order.line" else line.product_qty
            lines.append(
                {
                    "key": line.m_intercompany_line_key,
                    "display_type": line.display_type or False,
                    "product_id": line.product_id.id,
                    "quantity": quantity,
                    "uom_id": line.product_uom_id.id if line.product_uom_id else False,
                    "price_unit": line.price_unit,
                    "discount": getattr(line, "discount", 0.0),
                }
            )
        snapshot = {
            "order_id": m_order.id,
            "model": m_order._name,
            "state": m_order.state,
            "amount_total": m_order.amount_total,
            "currency_id": m_order.currency_id.id,
            "lines": lines,
        }
        return json.dumps(snapshot, sort_keys=True)

    @api.model
    def m_link_counterpart_lines(self, m_sale_order, m_purchase_order, m_sync_version, m_sync_at):
        purchase_lines_by_key = {
            line.m_intercompany_line_key: line
            for line in m_purchase_order.order_line
            if line.m_intercompany_line_key
        }
        sale_lines_by_key = {
            line.m_intercompany_line_key: line
            for line in m_sale_order.order_line
            if line.m_intercompany_line_key
        }
        for sale_line in sale_lines_by_key.values():
            counterpart = purchase_lines_by_key.get(sale_line.m_intercompany_line_key)
            values = {
                "m_intercompany_counterpart_line_id": counterpart.id if counterpart else False,
                "m_intercompany_sync_version": m_sync_version,
                "m_intercompany_last_sync_at": m_sync_at,
                "m_intercompany_sync_state": "synced",
                "m_intercompany_last_error": False,
            }
            sale_line.with_context(m_skip_intercompany_sync=True).write(values)
        for purchase_line in purchase_lines_by_key.values():
            counterpart = sale_lines_by_key.get(purchase_line.m_intercompany_line_key)
            values = {
                "m_intercompany_counterpart_line_id": counterpart.id if counterpart else False,
                "m_intercompany_sync_version": m_sync_version,
                "m_intercompany_last_sync_at": m_sync_at,
                "m_intercompany_sync_state": "synced",
                "m_intercompany_last_error": False,
            }
            purchase_line.with_context(m_skip_intercompany_sync=True).write(values)

    @api.model
    def m_finalize_sale_purchase_sync(
        self,
        m_transaction,
        m_sale_order,
        m_purchase_order,
        m_origin_company,
        m_sync_token,
    ):
        m_sync_at = fields.Datetime.now()
        m_sync_version = (m_transaction.m_sync_version or 0) + 1
        sale_snapshot = self.m_build_order_snapshot(m_sale_order)
        purchase_snapshot = self.m_build_order_snapshot(m_purchase_order)
        m_transaction.with_context(m_intercompany_internal_write=True).write(
            {
                "m_source_model": "sale.order",
                "m_source_res_id": m_sale_order.id,
                "m_destination_model": "purchase.order",
                "m_destination_res_id": m_purchase_order.id,
                "m_sale_order_id": m_sale_order.id,
                "m_purchase_order_id": m_purchase_order.id,
                "m_last_sync_at": m_sync_at,
                "m_last_sale_write_at": m_sale_order.write_date or m_sync_at,
                "m_last_purchase_write_at": m_purchase_order.write_date or m_sync_at,
                "m_last_sync_token": m_sync_token,
                "m_sync_version": m_sync_version,
                "m_pending_conflict": False,
                "m_counterpart_creation_state": "created",
                "m_state": "done",
                "m_health_state": "healthy",
                "m_last_error_message": False,
                "m_next_retry_at": False,
            }
        )
        m_sale_order.with_context(m_skip_intercompany_sync=True).write(
            {
                "m_intercompany_transaction_id": m_transaction.id,
                "m_intercompany_origin_company_id": m_origin_company.id,
            }
        )
        m_purchase_order.with_context(m_skip_intercompany_sync=True).write(
            {
                "m_intercompany_transaction_id": m_transaction.id,
                "m_intercompany_origin_company_id": m_origin_company.id,
            }
        )
        m_sale_order.m_mark_intercompany_synced(m_sync_version, sale_snapshot, m_sync_at)
        m_purchase_order.m_mark_intercompany_synced(m_sync_version, purchase_snapshot, m_sync_at)
        self.m_link_counterpart_lines(m_sale_order, m_purchase_order, m_sync_version, m_sync_at)
        m_transaction.m_mark_healthy(
            m_summary=_("Sale and purchase synchronization completed"),
            m_message=_("The intercompany sales and purchase documents are aligned."),
        )
        m_transaction.m_log_event(
            m_event_type="sync",
            m_summary=_("Sale and purchase synchronized"),
            m_message=_("%(sale)s is linked with %(purchase)s.", sale=m_sale_order.name, purchase=m_purchase_order.name),
            m_company_id=m_origin_company.id,
        )
        return True

    @api.model
    def m_handle_conflicts(
        self,
        m_transaction,
        m_rule,
        m_driving_company,
        m_differences,
    ):
        if not m_differences:
            return True
        both_changed = bool(
            m_transaction.m_last_sale_write_at
            and m_transaction.m_last_purchase_write_at
            and m_transaction.m_sale_order_id.write_date
            and m_transaction.m_purchase_order_id.write_date
            and m_transaction.m_sale_order_id.write_date > m_transaction.m_last_sale_write_at
            and m_transaction.m_purchase_order_id.write_date > m_transaction.m_last_purchase_write_at
        )
        if not both_changed:
            return True
        if m_rule.m_conflict_policy == "block_and_review":
            m_transaction.with_context(m_intercompany_internal_write=True).write({"m_pending_conflict": True})
            m_transaction.m_mark_warning(
                m_summary=_("Synchronization conflict detected"),
                m_message=_("Both sides changed after the last successful synchronization."),
            )
            return False
        winning_company = (
            m_rule.m_source_company_id
            if m_rule.m_conflict_policy == "source_wins"
            else m_rule.m_destination_company_id
        )
        if winning_company != m_driving_company:
            m_transaction.m_mark_warning(
                m_summary=_("Synchronization changes skipped"),
                m_message=_("The configured conflict policy preserved the other side."),
            )
            return False
        return True

    @api.model
    def m_create_purchase_from_sale(self, m_sale_order, m_rule, m_transaction, m_automatic):
        actor, actor_env = self.m_get_counterpart_actor(
            m_rule,
            "purchase.order",
            m_rule.m_destination_company_id,
            "create",
            m_automatic=m_automatic,
        )
        header_values, line_values = self.m_prepare_purchase_values_from_sale(m_rule, m_sale_order)
        purchase_order = actor_env.create(
            dict(
                header_values,
                order_line=[(0, 0, line_value) for line_value in line_values],
            )
        )
        if m_rule.m_requires_counterpart_confirmation() and purchase_order.state in {"draft", "sent"}:
            purchase_order.with_context(m_skip_intercompany_sync=True).button_confirm()
        return purchase_order

    @api.model
    def m_update_purchase_from_sale(self, m_sale_order, m_purchase_order, m_rule, m_transaction, m_automatic):
        actor, _actor_env = self.m_get_counterpart_actor(
            m_rule,
            "purchase.order",
            m_rule.m_destination_company_id,
            "write",
            m_automatic=m_automatic,
        )
        header_values, line_values = self.m_prepare_purchase_values_from_sale(m_rule, m_sale_order, m_purchase_order)
        differences = self.m_collect_preview_differences(m_purchase_order, header_values, line_values)
        if not self.m_handle_conflicts(m_transaction, m_rule, m_sale_order.company_id, differences):
            return False
        m_purchase_order = m_purchase_order.with_user(actor).with_company(m_rule.m_destination_company_id).with_context(
            allowed_company_ids=[m_rule.m_source_company_id.id, m_rule.m_destination_company_id.id],
            m_skip_intercompany_sync=True,
        )
        self.m_apply_payload_to_counterpart(m_rule, m_purchase_order, header_values, line_values)
        if m_rule.m_requires_counterpart_confirmation() and m_purchase_order.state in {"draft", "sent"}:
            m_purchase_order.button_confirm()
        return m_purchase_order

    @api.model
    def m_create_sale_from_purchase(self, m_purchase_order, m_rule, m_transaction, m_automatic):
        actor, actor_env = self.m_get_counterpart_actor(
            m_rule,
            "sale.order",
            m_rule.m_source_company_id,
            "create",
            m_automatic=m_automatic,
        )
        header_values, line_values = self.m_prepare_sale_values_from_purchase(m_rule, m_purchase_order)
        sale_order = actor_env.create(
            dict(
                header_values,
                order_line=[(0, 0, line_value) for line_value in line_values],
            )
        )
        if m_rule.m_requires_counterpart_confirmation() and sale_order.state in {"draft", "sent"}:
            sale_order.with_context(m_skip_intercompany_sync=True).action_confirm()
        return sale_order

    @api.model
    def m_update_sale_from_purchase(self, m_purchase_order, m_sale_order, m_rule, m_transaction, m_automatic):
        actor, _actor_env = self.m_get_counterpart_actor(
            m_rule,
            "sale.order",
            m_rule.m_source_company_id,
            "write",
            m_automatic=m_automatic,
        )
        header_values, line_values = self.m_prepare_sale_values_from_purchase(m_rule, m_purchase_order, m_sale_order)
        differences = self.m_collect_preview_differences(m_sale_order, header_values, line_values)
        if not self.m_handle_conflicts(m_transaction, m_rule, m_purchase_order.company_id, differences):
            return False
        m_sale_order = m_sale_order.with_user(actor).with_company(m_rule.m_source_company_id).with_context(
            allowed_company_ids=[m_rule.m_source_company_id.id, m_rule.m_destination_company_id.id],
            m_skip_intercompany_sync=True,
        )
        self.m_apply_payload_to_counterpart(m_rule, m_sale_order, header_values, line_values)
        if m_rule.m_requires_counterpart_confirmation() and m_sale_order.state in {"draft", "sent"}:
            m_sale_order.action_confirm()
        return m_sale_order

    @api.model
    def m_mark_sync_failure(self, m_transaction, m_origin_order, m_error):
        message = self.m_sanitize_exception_message(m_error)
        m_transaction.with_context(m_intercompany_internal_write=True).write(
            {"m_counterpart_creation_state": "failed"}
        )
        m_transaction.m_prepare_next_retry_at()
        m_origin_order.m_mark_intercompany_sync_failed(message)
        m_transaction.m_mark_failed(
            m_summary=_("Sale and purchase synchronization failed"),
            m_message=_("The intercompany synchronization attempt could not complete."),
            m_technical_details=message,
        )

    @api.model
    def m_sync_from_sale_order(
        self,
        m_sale_order,
        m_rule=False,
        m_automatic=False,
        m_raise_on_error=True,
        m_preview_only=False,
        m_from_retry=False,
    ):
        m_sale_order.ensure_one()
        rule = m_sale_order.m_validate_intercompany_eligibility(m_rule=m_rule, m_automatic=m_automatic)
        transaction = self.m_get_sale_purchase_transaction(m_rule=rule, m_sale_order=m_sale_order)
        if transaction and transaction.m_purchase_order_id and rule.m_sync_direction not in {"source_to_destination", "bidirectional"}:
            raise UserError(_("This rule does not allow the sales order side to push synchronization updates."))
        try:
            transaction.with_context(m_intercompany_internal_write=True).write(
                {"m_counterpart_creation_state": "creating", "m_last_sync_token": uuid.uuid4().hex}
            )
            if m_preview_only:
                return self.m_collect_sale_to_purchase_preview(m_sale_order=m_sale_order, m_rule=rule)
            purchase_order = transaction.m_purchase_order_id
            if purchase_order:
                purchase_order = self.m_update_purchase_from_sale(
                    m_sale_order,
                    purchase_order,
                    rule,
                    transaction,
                    m_automatic or m_from_retry,
                )
                if purchase_order is False:
                    return transaction.m_purchase_order_id
            else:
                purchase_order = self.m_create_purchase_from_sale(
                    m_sale_order,
                    rule,
                    transaction,
                    m_automatic or m_from_retry,
                )
            self.m_finalize_sale_purchase_sync(
                transaction,
                m_sale_order,
                purchase_order,
                m_sale_order.company_id,
                transaction.m_last_sync_token,
            )
            return purchase_order
        except Exception as error:  # pylint: disable=broad-except
            self.m_mark_sync_failure(transaction, m_sale_order, error)
            if m_raise_on_error:
                raise
            return False

    @api.model
    def m_sync_from_purchase_order(
        self,
        m_purchase_order,
        m_rule=False,
        m_automatic=False,
        m_raise_on_error=True,
        m_preview_only=False,
        m_from_retry=False,
    ):
        m_purchase_order.ensure_one()
        rule = m_purchase_order.m_validate_intercompany_eligibility(m_rule=m_rule, m_automatic=m_automatic)
        transaction = self.m_get_sale_purchase_transaction(m_rule=rule, m_purchase_order=m_purchase_order)
        if transaction and transaction.m_sale_order_id and rule.m_sync_direction not in {"destination_to_source", "bidirectional"}:
            raise UserError(_("This rule does not allow the purchase order side to push synchronization updates."))
        try:
            transaction.with_context(m_intercompany_internal_write=True).write(
                {"m_counterpart_creation_state": "creating", "m_last_sync_token": uuid.uuid4().hex}
            )
            if m_preview_only:
                return self.m_collect_purchase_to_sale_preview(m_purchase_order=m_purchase_order, m_rule=rule)
            sale_order = transaction.m_sale_order_id
            if sale_order:
                sale_order = self.m_update_sale_from_purchase(
                    m_purchase_order,
                    sale_order,
                    rule,
                    transaction,
                    m_automatic or m_from_retry,
                )
                if sale_order is False:
                    return transaction.m_sale_order_id
            else:
                sale_order = self.m_create_sale_from_purchase(
                    m_purchase_order,
                    rule,
                    transaction,
                    m_automatic or m_from_retry,
                )
            self.m_finalize_sale_purchase_sync(
                transaction,
                sale_order,
                m_purchase_order,
                m_purchase_order.company_id,
                transaction.m_last_sync_token,
            )
            return sale_order
        except Exception as error:  # pylint: disable=broad-except
            self.m_mark_sync_failure(transaction, m_purchase_order, error)
            if m_raise_on_error:
                raise
            return False

    @api.model
    def m_collect_sale_to_purchase_preview(self, m_sale_order, m_rule=False):
        m_sale_order.ensure_one()
        rule = m_rule or m_sale_order.m_find_applicable_intercompany_rule()
        transaction = self.m_get_sale_purchase_transaction(m_rule=rule, m_sale_order=m_sale_order)
        purchase_order = transaction.m_purchase_order_id
        if purchase_order:
            header_values, line_values = self.m_prepare_purchase_values_from_sale(rule, m_sale_order, purchase_order)
            changes = self.m_collect_preview_differences(purchase_order, header_values, line_values)
            counterpart_label = purchase_order.display_name
        else:
            header_values, line_values = self.m_prepare_purchase_values_from_sale(rule, m_sale_order)
            changes = [
                {
                    "action": "create",
                    "target": "document",
                    "field": "purchase.order",
                    "old": False,
                    "new": header_values.get("partner_id"),
                    "destructive": False,
                }
            ]
            changes.extend(
                {
                    "action": "create",
                    "target": "line",
                    "field": line_value["m_intercompany_line_key"],
                    "old": False,
                    "new": line_value.get("name") or line_value.get("product_id"),
                    "destructive": False,
                }
                for line_value in line_values
            )
            counterpart_label = _("New Purchase Order")
        return {
            "m_source_label": m_sale_order.display_name,
            "m_counterpart_label": counterpart_label,
            "m_changes": changes,
            "m_destructive_change": any(change["destructive"] for change in changes),
        }

    @api.model
    def m_collect_purchase_to_sale_preview(self, m_purchase_order, m_rule=False):
        m_purchase_order.ensure_one()
        rule = m_rule or m_purchase_order.m_find_applicable_intercompany_rule()
        transaction = self.m_get_sale_purchase_transaction(m_rule=rule, m_purchase_order=m_purchase_order)
        sale_order = transaction.m_sale_order_id
        if sale_order:
            header_values, line_values = self.m_prepare_sale_values_from_purchase(rule, m_purchase_order, sale_order)
            changes = self.m_collect_preview_differences(sale_order, header_values, line_values)
            counterpart_label = sale_order.display_name
        else:
            header_values, line_values = self.m_prepare_sale_values_from_purchase(rule, m_purchase_order)
            changes = [
                {
                    "action": "create",
                    "target": "document",
                    "field": "sale.order",
                    "old": False,
                    "new": header_values.get("partner_id"),
                    "destructive": False,
                }
            ]
            changes.extend(
                {
                    "action": "create",
                    "target": "line",
                    "field": line_value["m_intercompany_line_key"],
                    "old": False,
                    "new": line_value.get("name") or line_value.get("product_id"),
                    "destructive": False,
                }
                for line_value in line_values
            )
            counterpart_label = _("New Sales Order")
        return {
            "m_source_label": m_purchase_order.display_name,
            "m_counterpart_label": counterpart_label,
            "m_changes": changes,
            "m_destructive_change": any(change["destructive"] for change in changes),
        }

    def m_collect_sale_purchase_line_issues(self):
        self.ensure_one()
        if not self.m_sale_order_id or not self.m_purchase_order_id:
            return []
        issues = []
        purchase_lines_by_key = {
            line.m_intercompany_line_key: line
            for line in self.m_purchase_order_id.order_line
            if line.m_intercompany_line_key
        }
        sale_lines_by_key = {
            line.m_intercompany_line_key: line
            for line in self.m_sale_order_id.order_line
            if line.m_intercompany_line_key
        }
        if len(purchase_lines_by_key) != len(self.m_purchase_order_id.order_line.filtered("m_intercompany_line_key")):
            issues.append(_("Duplicate purchase-order line keys were detected."))
        if len(sale_lines_by_key) != len(self.m_sale_order_id.order_line.filtered("m_intercompany_line_key")):
            issues.append(_("Duplicate sales-order line keys were detected."))
        for line_key, sale_line in sale_lines_by_key.items():
            purchase_line = purchase_lines_by_key.get(line_key)
            if not purchase_line:
                issues.append(
                    _("Missing counterpart purchase line for %(line)s.", line=sale_line.display_name)
                )
                continue
            if sale_line.display_type != purchase_line.display_type:
                issues.append(
                    _("Display type differs for linked line %(line)s.", line=sale_line.display_name)
                )
            if (
                not sale_line.display_type
                and sale_line.product_id
                and not purchase_line.product_uom_id._has_common_reference(sale_line.product_uom_id)
            ):
                issues.append(
                    _("Unit of measure category mismatch for line %(line)s.", line=sale_line.display_name)
                )
        for line_key in set(purchase_lines_by_key) - set(sale_lines_by_key):
            issues.append(
                _(
                    "Purchase line %(line)s has no counterpart sales-order line.",
                    line=purchase_lines_by_key[line_key].display_name,
                )
            )
        return issues

    def m_collect_extension_health_issues(self):
        issues = super().m_collect_extension_health_issues()
        for transaction in self.filtered(lambda tx: tx.m_transaction_type == "sale_purchase"):
            if not transaction.m_sale_order_id:
                issues.append(_("The linked sales order is missing."))
            if not transaction.m_purchase_order_id:
                issues.append(_("The linked purchase order is missing."))
            if transaction.m_sale_order_id and transaction.m_sale_order_id.company_id != transaction.m_rule_id.m_source_company_id:
                issues.append(_("The linked sales order belongs to the wrong company."))
            if transaction.m_purchase_order_id and transaction.m_purchase_order_id.company_id != transaction.m_rule_id.m_destination_company_id:
                issues.append(_("The linked purchase order belongs to the wrong company."))
            if transaction.m_sale_order_id and transaction.m_sale_order_id.partner_id.commercial_partner_id != transaction.m_rule_id.m_destination_company_id.partner_id.commercial_partner_id:
                issues.append(_("The linked sales order customer no longer represents the destination company."))
            if transaction.m_purchase_order_id and transaction.m_purchase_order_id.partner_id.commercial_partner_id != transaction.m_rule_id.m_source_company_id.partner_id.commercial_partner_id:
                issues.append(_("The linked purchase order vendor no longer represents the source company."))
            duplicate_sale = self.search_count(
                [
                    ("id", "!=", transaction.id),
                    ("m_transaction_type", "=", "sale_purchase"),
                    ("m_sale_order_id", "=", transaction.m_sale_order_id.id),
                    ("m_state", "!=", "cancelled"),
                ]
            )
            if duplicate_sale:
                issues.append(_("Multiple active transactions point to the same sales order."))
            duplicate_purchase = self.search_count(
                [
                    ("id", "!=", transaction.id),
                    ("m_transaction_type", "=", "sale_purchase"),
                    ("m_purchase_order_id", "=", transaction.m_purchase_order_id.id),
                    ("m_state", "!=", "cancelled"),
                ]
            )
            if duplicate_purchase:
                issues.append(_("Multiple active transactions point to the same purchase order."))
            issues.extend(transaction.m_collect_sale_purchase_line_issues())
            if transaction.m_rule_id.m_requires_counterpart_confirmation() and transaction.m_purchase_order_id and transaction.m_purchase_order_id.state in {"draft", "sent"}:
                issues.append(_("The counterpart purchase order was expected to be confirmed but is still draft."))
            if transaction.m_sale_order_id and transaction.m_purchase_order_id:
                if transaction.m_sale_order_id.state == "cancel" and transaction.m_purchase_order_id.state != "cancel":
                    issues.append(_("The sales order is cancelled while the purchase order remains active."))
                if transaction.m_purchase_order_id.state == "cancel" and transaction.m_sale_order_id.state != "cancel":
                    issues.append(_("The purchase order is cancelled while the sales order remains active."))
            if transaction.m_counterpart_creation_state == "creating":
                stale_since = transaction.write_date or transaction.create_date
                if stale_since and stale_since < fields.Datetime.add(fields.Datetime.now(), minutes=-15):
                    issues.append(_("The transaction stayed in creating state for more than 15 minutes."))
        return issues

    def m_retry_handler_sale_purchase(self):
        self.ensure_one()
        if self.m_sale_order_id and not self.m_purchase_order_id:
            return bool(
                self.m_sync_from_sale_order(
                    self.m_sale_order_id,
                    m_rule=self.m_rule_id,
                    m_automatic=True,
                    m_raise_on_error=False,
                    m_from_retry=True,
                )
            )
        if self.m_purchase_order_id and not self.m_sale_order_id:
            return bool(
                self.m_sync_from_purchase_order(
                    self.m_purchase_order_id,
                    m_rule=self.m_rule_id,
                    m_automatic=True,
                    m_raise_on_error=False,
                    m_from_retry=True,
                )
            )
        if self.m_sale_order_id and self.m_purchase_order_id:
            if self.m_purchase_order_id.m_intercompany_sync_state in {"pending", "warning", "failed"} and self.m_rule_id.m_sync_direction in {"destination_to_source", "bidirectional"}:
                return bool(
                    self.m_sync_from_purchase_order(
                        self.m_purchase_order_id,
                        m_rule=self.m_rule_id,
                        m_automatic=True,
                        m_raise_on_error=False,
                        m_from_retry=True,
                    )
                )
            return bool(
                self.m_sync_from_sale_order(
                    self.m_sale_order_id,
                    m_rule=self.m_rule_id,
                    m_automatic=True,
                    m_raise_on_error=False,
                    m_from_retry=True,
                )
            )
        return {
            "success": False,
            "health_state": "failed",
            "summary": _("Retry failed"),
            "message": _("The transaction has no surviving sales or purchase document to retry from."),
        }
