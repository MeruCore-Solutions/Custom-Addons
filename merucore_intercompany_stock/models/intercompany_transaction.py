import uuid

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.fields import Command
from odoo.tools.float_utils import float_is_zero


class MeruCoreIntercompanyTransaction(models.Model):
    _inherit = "merucore.intercompany.transaction"

    m_parent_transaction_id = fields.Many2one(
        "merucore.intercompany.transaction",
        copy=False,
        index=True,
        check_company=False,
    )
    m_child_transaction_ids = fields.One2many(
        "merucore.intercompany.transaction",
        "m_parent_transaction_id",
        string="Child Transactions",
    )
    m_source_picking_id = fields.Many2one(
        "stock.picking",
        copy=False,
        index=True,
        check_company=False,
    )
    m_destination_picking_id = fields.Many2one(
        "stock.picking",
        copy=False,
        index=True,
        check_company=False,
    )
    m_stock_transfer_id = fields.Many2one(
        "merucore.intercompany.stock.transfer",
        copy=False,
        index=True,
        check_company=False,
    )
    m_source_picking_state = fields.Selection(
        related="m_source_picking_id.state",
        string="Source Picking State",
        readonly=True,
    )
    m_destination_picking_state = fields.Selection(
        related="m_destination_picking_id.state",
        string="Destination Picking State",
        readonly=True,
    )
    m_stock_transfer_state = fields.Selection(
        related="m_stock_transfer_id.m_state",
        string="Manual Transfer State",
        readonly=True,
    )

    def init(self):
        super().init()
        self.env.cr.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
                merucore_intercompany_tx_source_picking_uniq
            ON merucore_intercompany_transaction (m_source_picking_id)
            WHERE m_transaction_type = 'stock'
              AND m_source_picking_id IS NOT NULL
              AND COALESCE(m_state, '') <> 'cancelled'
            """
        )
        self.env.cr.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
                merucore_intercompany_tx_destination_picking_uniq
            ON merucore_intercompany_transaction (m_destination_picking_id)
            WHERE m_transaction_type = 'stock'
              AND m_destination_picking_id IS NOT NULL
              AND COALESCE(m_state, '') <> 'cancelled'
            """
        )
        self.env.cr.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
                merucore_intercompany_tx_stock_transfer_uniq
            ON merucore_intercompany_transaction (m_stock_transfer_id)
            WHERE m_transaction_type = 'stock'
              AND m_stock_transfer_id IS NOT NULL
              AND COALESCE(m_state, '') <> 'cancelled'
            """
        )

    @api.constrains(
        "m_source_picking_id",
        "m_destination_picking_id",
        "m_stock_transfer_id",
        "m_rule_id",
        "m_transaction_type",
    )
    def m_check_stock_links(self):
        for transaction in self.filtered(lambda tx: tx.m_transaction_type == "stock"):
            if (
                transaction.m_source_picking_id
                and transaction.m_source_picking_id.company_id != transaction.m_rule_id.m_source_company_id
            ):
                raise ValidationError(_("The linked source picking must belong to the source company."))
            if (
                transaction.m_destination_picking_id
                and transaction.m_destination_picking_id.company_id
                != transaction.m_rule_id.m_destination_company_id
            ):
                raise ValidationError(
                    _("The linked destination picking must belong to the destination company.")
                )
            if transaction.m_stock_transfer_id and transaction.m_stock_transfer_id.m_rule_id != transaction.m_rule_id:
                raise ValidationError(_("The linked manual transfer must use the same intercompany rule."))

    def m_action_open_source_picking(self):
        self.ensure_one()
        if not self.m_source_picking_id:
            raise UserError(_("There is no linked source picking."))
        return self.m_action_open_document("source")

    def m_action_open_destination_picking(self):
        self.ensure_one()
        if not self.m_destination_picking_id:
            raise UserError(_("There is no linked destination picking."))
        return self.m_action_open_document("destination")

    def m_action_open_stock_transfer(self):
        self.ensure_one()
        if not self.m_stock_transfer_id:
            raise UserError(_("There is no linked manual transfer request."))
        return {
            "type": "ir.actions.act_window",
            "res_model": "merucore.intercompany.stock.transfer",
            "res_id": self.m_stock_transfer_id.id,
            "view_mode": "form",
            "target": "current",
            "context": {"allowed_company_ids": self.m_company_ids.ids},
        }

    @api.model
    def m_build_stock_idempotency_key(self, m_rule, m_source_picking=False, m_stock_transfer=False):
        if m_source_picking:
            return f"stock:rule:{m_rule.id}:picking:{m_source_picking.id}"
        if m_stock_transfer:
            return f"stock:rule:{m_rule.id}:transfer:{m_stock_transfer.id}"
        raise ValidationError(_("A source picking or manual transfer request is required."))

    @api.model
    def m_get_stock_actor_environment(self, m_user, m_model_name, m_company, m_allowed_company_ids):
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
    def m_get_stock_actor(self, m_rule, m_model_name, m_company, m_operation, m_automatic=False):
        allowed_company_ids = [m_rule.m_source_company_id.id, m_rule.m_destination_company_id.id]
        actor = self.env.user
        if m_automatic:
            actor = m_rule.m_responsible_user_id or self.env.user
        if m_company not in actor.company_ids:
            raise AccessError(_("The selected user does not have access to the target company."))
        if (
            m_rule.m_source_company_id not in actor.company_ids
            or m_rule.m_destination_company_id not in actor.company_ids
        ):
            raise AccessError(
                _("The selected user must have access to both companies in the company pair.")
            )
        actor_env = self.m_get_stock_actor_environment(
            actor,
            m_model_name,
            m_company,
            m_allowed_company_ids=allowed_company_ids,
        )
        actor_env.check_access(m_operation)
        return actor, actor_env

    @api.model
    def m_get_company_warehouse(self, m_company):
        warehouse = self.env["stock.warehouse"].search([("company_id", "=", m_company.id)], limit=1)
        if not warehouse:
            raise ValidationError(
                _("No warehouse was found for company %(company)s.", company=m_company.display_name)
            )
        return warehouse

    @api.model
    def m_get_manual_source_picking_type(self, m_rule):
        if m_rule.m_stock_source_picking_type_id:
            return m_rule.m_stock_source_picking_type_id
        return self.m_get_company_warehouse(m_rule.m_source_company_id).out_type_id

    @api.model
    def m_get_destination_picking_type(self, m_rule):
        if m_rule.m_stock_destination_picking_type_id:
            return m_rule.m_stock_destination_picking_type_id
        return self.m_get_company_warehouse(m_rule.m_destination_company_id).in_type_id

    @api.model
    def m_get_destination_stock_location(self, m_rule, m_picking_type=False):
        if m_rule.m_stock_destination_location_id:
            return m_rule.m_stock_destination_location_id
        picking_type = m_picking_type or self.m_get_destination_picking_type(m_rule)
        return (
            picking_type.default_location_dest_id
            or self.m_get_company_warehouse(m_rule.m_destination_company_id).lot_stock_id
        )

    @api.model
    def m_resolve_stock_parent_transaction(self, m_picking):
        parent_transaction = self.browse()
        if "sale_id" in m_picking._fields and m_picking.sale_id:
            sale_order = m_picking.sale_id
            if "m_intercompany_transaction_id" in sale_order._fields:
                parent_transaction |= sale_order.m_intercompany_transaction_id
        move_fields = m_picking.move_ids._fields
        if not parent_transaction and "sale_line_id" in move_fields:
            sale_orders = m_picking.move_ids.mapped("sale_line_id.order_id")
            sale_orders = sale_orders.filtered(lambda order: "m_intercompany_transaction_id" in order._fields)
            parent_transaction |= sale_orders.m_intercompany_transaction_id
        if not parent_transaction and "purchase_line_id" in move_fields:
            purchase_orders = m_picking.move_ids.mapped("purchase_line_id.order_id")
            purchase_orders = purchase_orders.filtered(
                lambda order: "m_intercompany_transaction_id" in order._fields
            )
            parent_transaction |= purchase_orders.m_intercompany_transaction_id
        return parent_transaction[:1]

    @api.model
    def m_get_stock_transaction(
        self,
        m_rule,
        m_source_picking=False,
        m_stock_transfer=False,
        m_parent_transaction=False,
    ):
        if m_source_picking and m_source_picking.m_intercompany_transaction_id:
            return m_source_picking.m_intercompany_transaction_id
        if m_stock_transfer and m_stock_transfer.m_intercompany_transaction_id:
            return m_stock_transfer.m_intercompany_transaction_id
        domain = [("m_transaction_type", "=", "stock"), ("m_rule_id", "=", m_rule.id)]
        if m_source_picking:
            domain.append(("m_source_picking_id", "=", m_source_picking.id))
        if m_stock_transfer:
            domain.append(("m_stock_transfer_id", "=", m_stock_transfer.id))
        transaction = self.search(domain, limit=1)
        if transaction:
            return transaction
        idempotency_key = self.m_build_stock_idempotency_key(
            m_rule,
            m_source_picking=m_source_picking,
            m_stock_transfer=m_stock_transfer,
        )
        transaction = self.search([("m_idempotency_key", "=", idempotency_key)], limit=1)
        if transaction:
            return transaction
        vals = {
            "m_rule_id": m_rule.id,
            "m_source_company_id": m_rule.m_source_company_id.id,
            "m_destination_company_id": m_rule.m_destination_company_id.id,
            "m_transaction_type": "stock",
            "m_reference": (m_source_picking and m_source_picking.name) or (m_stock_transfer and m_stock_transfer.m_name),
            "m_idempotency_key": idempotency_key,
            "m_responsible_user_id": m_rule.m_responsible_user_id.id,
            "m_parent_transaction_id": m_parent_transaction.id if m_parent_transaction else False,
            "m_source_model": m_source_picking._name if m_source_picking else False,
            "m_source_res_id": m_source_picking.id if m_source_picking else False,
            "m_stock_transfer_id": m_stock_transfer.id if m_stock_transfer else False,
            "m_source_picking_id": m_source_picking.id if m_source_picking else False,
            "m_state": "draft",
        }
        try:
            transaction = self.with_context(m_intercompany_internal_write=True).create(vals)
        except ValidationError:
            transaction = self.search([("m_idempotency_key", "=", idempotency_key)], limit=1)
            if not transaction:
                raise
        if m_stock_transfer:
            m_stock_transfer.with_context(m_skip_intercompany_sync=True).write(
                {"m_intercompany_transaction_id": transaction.id}
            )
        return transaction

    @api.model
    def m_resolve_counterpart_stock_product(self, m_rule, m_source_product, m_destination_company):
        if not m_source_product:
            raise ValidationError(_("A product is required for stock synchronization."))
        search_domain = [
            ("type", "!=", "service"),
            "|",
            ("company_id", "=", False),
            ("company_id", "=", m_destination_company.id),
        ]
        strategy = m_rule.m_stock_product_mapping_strategy
        if strategy == "same_product":
            if m_source_product.company_id and m_source_product.company_id != m_destination_company:
                raise ValidationError(
                    _(
                        "Product %(product)s is company-specific and cannot be reused in %(company)s.",
                        product=m_source_product.display_name,
                        company=m_destination_company.display_name,
                    )
                )
            return m_source_product
        if strategy == "internal_reference":
            if not m_source_product.default_code:
                raise ValidationError(_("Internal-reference mapping requires a product internal reference."))
            search_domain.append(("default_code", "=", m_source_product.default_code))
        else:
            if not m_source_product.barcode:
                raise ValidationError(_("Barcode mapping requires a product barcode."))
            search_domain.append(("barcode", "=", m_source_product.barcode))
        matches = self.env["product.product"].search(search_domain)
        if not matches:
            raise ValidationError(
                _("No counterpart product mapping was found for %(product)s.", product=m_source_product.display_name)
            )
        if len(matches) > 1:
            raise ValidationError(
                _("Multiple counterpart products match %(product)s.", product=m_source_product.display_name)
            )
        return matches

    @api.model
    def m_uom_reference(self, m_uom):
        return m_uom.relative_uom_id or m_uom

    @api.model
    def m_uom_is_compatible(self, m_uom_a, m_uom_b):
        return bool(m_uom_a and m_uom_b and self.m_uom_reference(m_uom_a) == self.m_uom_reference(m_uom_b))

    @api.model
    def m_get_counterpart_line_qty(self, m_source_line, m_destination_uom):
        quantity_product_uom = (
            m_source_line.quantity_product_uom
            if "quantity_product_uom" in m_source_line._fields
            else m_source_line.quantity
        )
        return m_destination_uom._compute_quantity(
            quantity_product_uom,
            m_destination_uom,
            rounding_method="HALF-UP",
        )

    @api.model
    def m_get_or_create_counterpart_lot(self, m_actor, m_company, m_product, m_lot_name):
        if not m_lot_name:
            return False
        allowed_company_ids = [m_company.id]
        lot_env = (
            self.env["stock.lot"]
            .with_user(m_actor)
            .with_company(m_company)
            .with_context(allowed_company_ids=allowed_company_ids)
        )
        lot = lot_env.search(
            [
                ("product_id", "=", m_product.id),
                ("name", "=", m_lot_name),
                ("company_id", "=", m_company.id),
            ],
            limit=1,
        )
        if lot:
            return lot
        return lot_env.create(
            {
                "name": m_lot_name,
                "product_id": m_product.id,
                "company_id": m_company.id,
            }
        )

    @api.model
    def m_get_or_create_counterpart_package(self, m_actor, m_company, m_package):
        if not m_package:
            return False
        allowed_company_ids = [m_company.id]
        package_env = (
            self.env["stock.package"]
            .with_user(m_actor)
            .with_company(m_company)
            .with_context(allowed_company_ids=allowed_company_ids)
        )
        package = package_env.search([("name", "=", m_package.name)], limit=1)
        if package:
            return package
        values = {"name": m_package.name}
        if m_package.package_type_id:
            values["package_type_id"] = m_package.package_type_id.id
        return package_env.create(values)

    @api.model
    def m_build_done_source_lines(self, m_source_move):
        done_lines = m_source_move.move_line_ids.filtered(
            lambda line: not float_is_zero(
                line.quantity_product_uom,
                precision_rounding=line.product_id.uom_id.rounding,
            )
        )
        if done_lines:
            return done_lines
        if float_is_zero(
            m_source_move.quantity,
            precision_rounding=m_source_move.product_uom.rounding,
        ):
            return self.env["stock.move.line"]
        return self.env["stock.move.line"].new(
            {
                "product_id": m_source_move.product_id.id,
                "product_uom_id": m_source_move.product_uom.id,
                "quantity": m_source_move.quantity,
                "location_id": m_source_move.location_id.id,
                "location_dest_id": m_source_move.location_dest_id.id,
                "company_id": m_source_move.company_id.id,
            }
        )

    @api.model
    def m_prepare_counterpart_move_values(
        self,
        m_rule,
        m_source_move,
        m_source_picking,
        m_actor,
        m_destination_company,
        m_location_id,
        m_location_dest_id,
    ):
        source_product = m_source_move.product_id
        destination_product = self.m_resolve_counterpart_stock_product(
            m_rule,
            source_product,
            m_destination_company,
        )
        source_uom = m_source_move.product_uom
        destination_uom = source_uom
        if not self.m_uom_is_compatible(source_uom, destination_product.uom_id):
            raise ValidationError(
                _("The mapped destination product must share the same unit-of-measure reference chain.")
            )
        if destination_product != source_product:
            destination_uom = destination_product.uom_id
        total_qty = 0.0
        for source_line in self.m_build_done_source_lines(m_source_move):
            quantity_in_dest_uom = source_line.product_uom_id._compute_quantity(
                source_line.quantity,
                destination_uom,
                rounding_method="HALF-UP",
            )
            if float_is_zero(quantity_in_dest_uom, precision_rounding=destination_uom.rounding):
                continue
            total_qty += quantity_in_dest_uom
        if float_is_zero(total_qty, precision_rounding=destination_uom.rounding):
            return False
        return {
            "description_picking": m_source_move.description_picking or destination_product.display_name,
            "product_id": destination_product.id,
            "product_uom": destination_uom.id,
            "product_uom_qty": total_qty,
            "company_id": m_destination_company.id,
            "location_id": m_location_id.id,
            "location_dest_id": m_location_dest_id.id,
            "origin": m_source_picking.name,
        }

    @api.model
    def m_prepare_counterpart_picking_values(self, m_source_picking, m_rule, m_actor):
        picking_type = self.m_get_destination_picking_type(m_rule)
        transit_location = m_rule.m_get_stock_transit_location()
        if not transit_location:
            raise ValidationError(_("No intercompany transit location could be resolved for this rule."))
        destination_location = self.m_get_destination_stock_location(m_rule, m_picking_type=picking_type)
        move_commands = []
        for source_move in m_source_picking.move_ids.filtered(lambda move: move.state == "done"):
            move_values = self.m_prepare_counterpart_move_values(
                m_rule,
                source_move,
                m_source_picking,
                m_actor,
                m_rule.m_destination_company_id,
                transit_location,
                destination_location,
            )
            if move_values:
                move_commands.append(Command.create(move_values))
        if not move_commands:
            raise ValidationError(_("The validated source picking has no done stock quantities to synchronize."))
        return {
            "company_id": m_rule.m_destination_company_id.id,
            "partner_id": m_rule.m_source_company_id.partner_id.id,
            "picking_type_id": picking_type.id,
            "location_id": transit_location.id,
            "location_dest_id": destination_location.id,
            "origin": m_source_picking.name,
            "scheduled_date": m_source_picking.date_done or m_source_picking.scheduled_date,
            "move_type": m_source_picking.move_type,
            "note": _(
                "Auto-created from %(source)s (%(company)s).",
                source=m_source_picking.display_name,
                company=m_rule.m_source_company_id.display_name,
            ),
            "move_ids": move_commands,
        }

    @api.model
    def m_prepare_counterpart_move_line_values(
        self,
        m_rule,
        m_source_move,
        m_actor,
        m_destination_company,
        m_destination_move,
    ):
        source_product = m_source_move.product_id
        destination_product = self.m_resolve_counterpart_stock_product(
            m_rule,
            source_product,
            m_destination_company,
        )
        destination_uom = m_destination_move.product_uom
        if not self.m_uom_is_compatible(m_source_move.product_uom, destination_uom):
            raise ValidationError(
                _("The mapped destination product must share the same unit-of-measure reference chain.")
            )
        line_values_list = []
        for source_line in self.m_build_done_source_lines(m_source_move):
            quantity_in_dest_uom = source_line.product_uom_id._compute_quantity(
                source_line.quantity,
                destination_uom,
                rounding_method="HALF-UP",
            )
            if float_is_zero(quantity_in_dest_uom, precision_rounding=destination_uom.rounding):
                continue
            lot = False
            if m_rule.m_stock_sync_lots:
                lot_name = source_line.lot_id.name or source_line.lot_name
                lot = self.m_get_or_create_counterpart_lot(
                    m_actor,
                    m_destination_company,
                    destination_product,
                    lot_name,
                )
            result_package = False
            if m_rule.m_stock_sync_packages:
                result_package = self.m_get_or_create_counterpart_package(
                    m_actor,
                    m_destination_company,
                    source_line.result_package_id or source_line.package_id,
                )
            line_values = {
                "picking_id": m_destination_move.picking_id.id,
                "product_id": destination_product.id,
                "product_uom_id": destination_uom.id,
                "quantity": quantity_in_dest_uom,
                "company_id": m_destination_company.id,
                "location_id": m_destination_move.location_id.id,
                "location_dest_id": m_destination_move.location_dest_id.id,
            }
            if lot:
                line_values["lot_id"] = lot.id
            elif m_rule.m_stock_sync_lots and (source_line.lot_id.name or source_line.lot_name):
                line_values["lot_name"] = source_line.lot_id.name or source_line.lot_name
            if m_rule.m_stock_sync_owners and source_line.owner_id:
                line_values["owner_id"] = source_line.owner_id.id
            if result_package:
                line_values["result_package_id"] = result_package.id
            line_values_list.append(line_values)
        return line_values_list

    @api.model
    def m_apply_counterpart_move_lines(
        self,
        m_rule,
        m_source_picking,
        m_destination_picking,
        m_actor,
    ):
        source_moves = self.env["stock.move"]
        for source_move in m_source_picking.move_ids.filtered(lambda move: move.state == "done"):
            move_values = self.m_prepare_counterpart_move_values(
                m_rule,
                source_move,
                m_source_picking,
                m_actor,
                m_destination_picking.company_id,
                m_destination_picking.location_id,
                m_destination_picking.location_dest_id,
            )
            if move_values:
                source_moves |= source_move
        destination_moves = m_destination_picking.move_ids.sorted("id")
        if len(source_moves) != len(destination_moves):
            raise ValidationError(
                _("The synchronized picking structure changed unexpectedly; please retry the transfer.")
            )
        for source_move, destination_move in zip(source_moves, destination_moves):
            line_values_list = self.m_prepare_counterpart_move_line_values(
                m_rule,
                source_move,
                m_actor,
                m_destination_picking.company_id,
                destination_move,
            )
            if not line_values_list:
                continue
            commands = []
            candidate_lines = destination_move.move_line_ids.filtered(
                lambda line: not line.lot_id
                and not line.lot_name
                and not line.owner_id
                and not line.package_id
                and not line.result_package_id
            )
            for line_values in line_values_list:
                if candidate_lines[:1]:
                    line = candidate_lines[:1]
                    commands.append(Command.update(line.id, line_values))
                    candidate_lines -= line
                else:
                    commands.append(Command.create(line_values))
            if commands:
                destination_move.write({"move_line_ids": commands})

    @api.model
    def m_prepare_source_transfer_picking_values(self, m_transfer, m_rule):
        picking_type = self.m_get_manual_source_picking_type(m_rule)
        transit_location = m_rule.m_get_stock_transit_location()
        if not transit_location:
            raise ValidationError(_("No intercompany transit location could be resolved for this rule."))
        move_commands = []
        for line in m_transfer.m_line_ids:
            move_commands.append(
                Command.create(
                    {
                        "description_picking": line.m_description or line.m_product_id.display_name,
                        "product_id": line.m_product_id.id,
                        "product_uom": line.m_uom_id.id,
                        "product_uom_qty": line.m_quantity,
                        "company_id": m_rule.m_source_company_id.id,
                        "location_id": picking_type.default_location_src_id.id,
                        "location_dest_id": transit_location.id,
                        "origin": m_transfer.m_name,
                    }
                )
            )
        return {
            "company_id": m_rule.m_source_company_id.id,
            "partner_id": m_rule.m_destination_company_id.partner_id.id,
            "picking_type_id": picking_type.id,
            "location_id": picking_type.default_location_src_id.id,
            "location_dest_id": transit_location.id,
            "origin": m_transfer.m_name,
            "scheduled_date": m_transfer.m_planned_date,
            "move_type": "direct",
            "note": _(
                "Manual intercompany transfer request %(transfer)s.",
                transfer=m_transfer.m_name,
            ),
            "move_ids": move_commands,
        }

    @api.model
    def m_prepare_destination_transfer_picking_values(self, m_transfer, m_rule):
        picking_type = self.m_get_destination_picking_type(m_rule)
        transit_location = m_rule.m_get_stock_transit_location()
        destination_location = self.m_get_destination_stock_location(m_rule, m_picking_type=picking_type)
        move_commands = []
        for line in m_transfer.m_line_ids:
            destination_product = self.m_resolve_counterpart_stock_product(
                m_rule,
                line.m_product_id,
                m_rule.m_destination_company_id,
            )
            destination_uom = line.m_uom_id
            if destination_product != line.m_product_id:
                destination_uom = destination_product.uom_id
            quantity = line.m_uom_id._compute_quantity(
                line.m_quantity,
                destination_uom,
                rounding_method="HALF-UP",
            )
            move_commands.append(
                Command.create(
                    {
                        "description_picking": line.m_description or destination_product.display_name,
                        "product_id": destination_product.id,
                        "product_uom": destination_uom.id,
                        "product_uom_qty": quantity,
                        "company_id": m_rule.m_destination_company_id.id,
                        "location_id": transit_location.id,
                        "location_dest_id": destination_location.id,
                        "origin": m_transfer.m_name,
                    }
                )
            )
        return {
            "company_id": m_rule.m_destination_company_id.id,
            "partner_id": m_rule.m_source_company_id.partner_id.id,
            "picking_type_id": picking_type.id,
            "location_id": transit_location.id,
            "location_dest_id": destination_location.id,
            "origin": m_transfer.m_name,
            "scheduled_date": m_transfer.m_planned_date,
            "move_type": "direct",
            "note": _(
                "Manual intercompany transfer request %(transfer)s.",
                transfer=m_transfer.m_name,
            ),
            "move_ids": move_commands,
        }

    @api.model
    def m_mark_stock_sync_failure(self, m_transaction, m_origin_record, m_error):
        message = m_transaction.m_sanitize_exception_message(m_error)
        m_transaction.m_prepare_next_retry_at()
        if hasattr(m_origin_record, "m_mark_intercompany_sync_failed"):
            m_origin_record.m_mark_intercompany_sync_failed(message)
        m_transaction.m_mark_failed(
            m_summary=_("Stock synchronization failed"),
            m_message=_("The intercompany stock synchronization attempt could not complete."),
            m_technical_details=message,
        )

    @api.model
    def m_finalize_stock_sync(self, m_transaction, m_source_picking, m_destination_picking):
        timestamp = fields.Datetime.now()
        values = {
            "m_transaction_type": "stock",
            "m_source_picking_id": m_source_picking.id if m_source_picking else False,
            "m_destination_picking_id": m_destination_picking.id if m_destination_picking else False,
            "m_source_model": m_source_picking._name if m_source_picking else False,
            "m_source_res_id": m_source_picking.id if m_source_picking else False,
            "m_destination_model": m_destination_picking._name if m_destination_picking else False,
            "m_destination_res_id": m_destination_picking.id if m_destination_picking else False,
            "m_reference": m_source_picking.name if m_source_picking else m_transaction.m_reference,
            "m_last_sync_at": timestamp,
        }
        m_transaction.with_context(m_intercompany_internal_write=True).write(values)
        if m_source_picking:
            m_source_picking.with_context(m_skip_intercompany_sync=True).write(
                {
                    "m_intercompany_transaction_id": m_transaction.id,
                    "m_intercompany_counterpart_picking_id": m_destination_picking.id if m_destination_picking else False,
                    "m_intercompany_sync_state": "synced",
                    "m_intercompany_origin_company_id": m_source_picking.company_id.id,
                    "m_intercompany_root_picking_id": (
                        m_source_picking.m_intercompany_root_picking_id.id or m_source_picking.id
                    ),
                    "m_intercompany_last_sync_at": timestamp,
                }
            )
        if m_destination_picking:
            m_destination_picking.with_context(m_skip_intercompany_sync=True).write(
                {
                    "m_intercompany_transaction_id": m_transaction.id,
                    "m_intercompany_counterpart_picking_id": m_source_picking.id if m_source_picking else False,
                    "m_intercompany_sync_state": "synced",
                    "m_intercompany_origin_company_id": m_source_picking.company_id.id if m_source_picking else False,
                    "m_intercompany_root_picking_id": (
                        m_source_picking.m_intercompany_root_picking_id.id or m_source_picking.id
                    )
                    if m_source_picking
                    else False,
                    "m_intercompany_last_sync_at": timestamp,
                }
            )
        m_transaction.m_action_mark_done()

    @api.model
    def m_sync_from_stock_picking(
        self,
        m_picking,
        m_rule=False,
        m_automatic=False,
        m_raise_on_error=True,
    ):
        m_picking.ensure_one()
        rule = m_picking.m_validate_intercompany_stock_eligibility(
            m_rule=m_rule,
            m_automatic=m_automatic,
        )
        parent_transaction = self.m_resolve_stock_parent_transaction(m_picking)
        transaction = self.m_get_stock_transaction(
            m_rule=rule,
            m_source_picking=m_picking,
            m_parent_transaction=parent_transaction,
        )
        if transaction.m_destination_picking_id:
            return transaction.m_destination_picking_id
        try:
            if transaction.m_state == "draft":
                transaction.m_action_start()
            actor, actor_env = self.m_get_stock_actor(
                rule,
                "stock.picking",
                rule.m_destination_company_id,
                "create",
                m_automatic=True,
            )
            transaction.with_context(m_intercompany_internal_write=True).write(
                {"m_reference": m_picking.name, "m_last_error_message": False}
            )
            destination_vals = self.m_prepare_counterpart_picking_values(m_picking, rule, actor)
            destination_picking = actor_env.create(destination_vals)
            if rule.m_stock_auto_confirm_counterpart and destination_picking.state == "draft":
                destination_picking.action_confirm()
            if (
                destination_picking.location_id.usage == "transit"
                and destination_picking.state in {"assigned", "partially_available"}
            ):
                destination_picking.do_unreserve()
            if (
                rule.m_stock_auto_assign_counterpart
                and destination_picking.location_id.usage != "transit"
                and destination_picking.state in {"confirmed", "waiting", "partially_available"}
            ):
                destination_picking.action_assign()
            self.m_apply_counterpart_move_lines(rule, m_picking, destination_picking, actor)
            self.m_finalize_stock_sync(transaction, m_picking, destination_picking)
            return destination_picking
        except Exception as error:  # pylint: disable=broad-except
            self.m_mark_stock_sync_failure(transaction, m_picking, error)
            if m_raise_on_error:
                raise
            return False

    @api.model
    def m_sync_from_stock_transfer(
        self,
        m_transfer,
        m_raise_on_error=True,
    ):
        m_transfer.ensure_one()
        rule = m_transfer.m_validate_transfer_request()
        transaction = self.m_get_stock_transaction(m_rule=rule, m_stock_transfer=m_transfer)
        if transaction.m_source_picking_id and transaction.m_destination_picking_id:
            return transaction.m_source_picking_id | transaction.m_destination_picking_id
        try:
            if transaction.m_state == "draft":
                transaction.m_action_start()
            _source_actor, source_env = self.m_get_stock_actor(
                rule,
                "stock.picking",
                rule.m_source_company_id,
                "create",
                m_automatic=True,
            )
            destination_actor, destination_env = self.m_get_stock_actor(
                rule,
                "stock.picking",
                rule.m_destination_company_id,
                "create",
                m_automatic=True,
            )
            source_picking = source_env.create(
                self.m_prepare_source_transfer_picking_values(m_transfer, rule)
            )
            destination_picking = destination_env.create(
                self.m_prepare_destination_transfer_picking_values(m_transfer, rule)
            )
            if rule.m_stock_auto_confirm_counterpart:
                if source_picking.state == "draft":
                    source_picking.action_confirm()
                if destination_picking.state == "draft":
                    destination_picking.action_confirm()
            if rule.m_stock_auto_assign_counterpart:
                source_picking.action_assign()
                destination_picking.action_assign()
            source_picking.with_context(m_skip_intercompany_sync=True).write(
                {"m_intercompany_manual_transfer_id": m_transfer.id}
            )
            destination_picking.with_context(m_skip_intercompany_sync=True).write(
                {"m_intercompany_manual_transfer_id": m_transfer.id}
            )
            transaction.with_context(m_intercompany_internal_write=True).write(
                {
                    "m_stock_transfer_id": m_transfer.id,
                    "m_reference": m_transfer.m_name,
                }
            )
            self.m_finalize_stock_sync(transaction, source_picking, destination_picking)
            m_transfer.with_context(m_skip_intercompany_sync=True).write(
                {
                    "m_intercompany_transaction_id": transaction.id,
                    "m_source_picking_id": source_picking.id,
                    "m_destination_picking_id": destination_picking.id,
                    "m_state": "confirmed",
                }
            )
            return source_picking | destination_picking
        except Exception as error:  # pylint: disable=broad-except
            self.m_mark_stock_sync_failure(transaction, m_transfer, error)
            if m_raise_on_error:
                raise
            return False

    def m_collect_extension_health_issues(self):
        issues = super().m_collect_extension_health_issues()
        for transaction in self.filtered(lambda tx: tx.m_transaction_type == "stock"):
            if transaction.m_source_picking_id and transaction.m_source_picking_id.company_id != transaction.m_rule_id.m_source_company_id:
                issues.append(_("The linked source picking belongs to the wrong company."))
            if transaction.m_destination_picking_id and transaction.m_destination_picking_id.company_id != transaction.m_rule_id.m_destination_company_id:
                issues.append(_("The linked destination picking belongs to the wrong company."))
            if transaction.m_source_picking_id and transaction.m_destination_picking_id:
                if transaction.m_source_picking_id.state == "cancel" and transaction.m_destination_picking_id.state != "cancel":
                    issues.append(_("The source picking is cancelled while the destination picking remains active."))
                if transaction.m_destination_picking_id.state == "cancel" and transaction.m_source_picking_id.state != "cancel":
                    issues.append(_("The destination picking is cancelled while the source picking remains active."))
        return issues

    def m_retry_handler_stock(self):
        self.ensure_one()
        if self.m_source_picking_id and not self.m_destination_picking_id:
            return bool(
                self.m_sync_from_stock_picking(
                    self.m_source_picking_id,
                    m_rule=self.m_rule_id,
                    m_automatic=True,
                    m_raise_on_error=False,
                )
            )
        if self.m_stock_transfer_id and not (self.m_source_picking_id and self.m_destination_picking_id):
            return bool(
                self.m_sync_from_stock_transfer(
                    self.m_stock_transfer_id,
                    m_raise_on_error=False,
                )
            )
        return {
            "success": False,
            "health_state": "failed",
            "summary": _("Retry failed"),
            "message": _("The transaction does not have a surviving source record that can be retried."),
        }
