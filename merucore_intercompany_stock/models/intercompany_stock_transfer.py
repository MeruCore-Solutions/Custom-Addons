from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class MeruCoreIntercompanyStockTransfer(models.Model):
    _name = "merucore.intercompany.stock.transfer"
    _description = "MeruCore Intercompany Stock Transfer"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    m_name = fields.Char(
        required=True,
        copy=False,
        readonly=True,
        index=True,
        default="/",
        tracking=True,
    )
    m_rule_id = fields.Many2one(
        "merucore.intercompany.rule",
        required=True,
        index=True,
        ondelete="restrict",
        tracking=True,
    )
    m_source_company_id = fields.Many2one(
        "res.company",
        related="m_rule_id.m_source_company_id",
        store=True,
        readonly=True,
    )
    m_destination_company_id = fields.Many2one(
        "res.company",
        related="m_rule_id.m_destination_company_id",
        store=True,
        readonly=True,
    )
    m_state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("confirmed", "Documents Created"),
            ("done", "Done"),
            ("cancelled", "Cancelled"),
        ],
        default="draft",
        required=True,
        tracking=True,
    )
    m_reference = fields.Char(tracking=True)
    m_planned_date = fields.Datetime(
        default=fields.Datetime.now,
        required=True,
        tracking=True,
    )
    m_line_ids = fields.One2many(
        "merucore.intercompany.stock.transfer.line",
        "m_transfer_id",
        string="Lines",
        copy=True,
    )
    m_intercompany_transaction_id = fields.Many2one(
        "merucore.intercompany.transaction",
        copy=False,
        index=True,
        check_company=False,
    )
    m_source_picking_id = fields.Many2one(
        "stock.picking",
        copy=False,
        check_company=False,
    )
    m_destination_picking_id = fields.Many2one(
        "stock.picking",
        copy=False,
        check_company=False,
    )
    m_note = fields.Html()
    m_picking_count = fields.Integer(compute="m_compute_picking_count")

    @api.depends("m_source_picking_id", "m_destination_picking_id")
    def m_compute_picking_count(self):
        for transfer in self:
            transfer.m_picking_count = len(transfer.m_source_picking_id | transfer.m_destination_picking_id)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            vals.setdefault(
                "m_name",
                self.env["ir.sequence"].next_by_code("merucore.intercompany.stock.transfer") or "/",
            )
        return super().create(vals_list)

    @api.constrains("m_rule_id", "m_line_ids")
    def m_check_transfer_request(self):
        for transfer in self:
            transfer.m_validate_transfer_request()
            if not transfer.m_line_ids:
                raise ValidationError(_("A manual intercompany transfer request requires at least one line."))

    def m_validate_transfer_request(self):
        self.ensure_one()
        rule = self.m_rule_id
        if not rule.m_stock_sync_enabled:
            raise ValidationError(_("The selected rule does not have stock synchronization enabled."))
        if not rule.m_allows_manual_transfer():
            raise ValidationError(_("The selected rule is not configured for manual transfer requests."))
        if not rule.m_source_company_id.m_intercompany_enabled or not rule.m_destination_company_id.m_intercompany_enabled:
            raise ValidationError(_("Both companies must have intercompany enabled."))
        if self.m_state == "cancelled":
            raise UserError(_("Cancelled transfer requests cannot generate stock documents."))
        return rule

    def m_action_generate_documents(self):
        self.ensure_one()
        if self.m_state == "done":
            raise UserError(_("Done transfer requests cannot generate stock documents again."))
        return self.env["merucore.intercompany.transaction"].m_sync_from_stock_transfer(self)

    def m_action_mark_done(self):
        for transfer in self:
            transfer.write({"m_state": "done"})

    def m_action_cancel(self):
        for transfer in self:
            if transfer.m_source_picking_id and transfer.m_source_picking_id.state not in {"done", "cancel"}:
                transfer.m_source_picking_id.with_context(m_skip_intercompany_sync=True).action_cancel()
            if transfer.m_destination_picking_id and transfer.m_destination_picking_id.state not in {"done", "cancel"}:
                transfer.m_destination_picking_id.with_context(m_skip_intercompany_sync=True).action_cancel()
            if (
                transfer.m_intercompany_transaction_id
                and transfer.m_intercompany_transaction_id.m_state != "cancelled"
            ):
                transfer.m_intercompany_transaction_id.with_context(
                    m_intercompany_internal_write=True
                ).m_action_cancel()
            transfer.write({"m_state": "cancelled"})

    def m_action_open_source_picking(self):
        self.ensure_one()
        if not self.m_source_picking_id:
            raise UserError(_("No source picking is linked yet."))
        return {
            "type": "ir.actions.act_window",
            "res_model": "stock.picking",
            "res_id": self.m_source_picking_id.id,
            "view_mode": "form",
            "target": "current",
            "context": {
                "allowed_company_ids": [
                    self.m_source_company_id.id,
                    self.m_destination_company_id.id,
                ]
            },
        }

    def m_action_open_destination_picking(self):
        self.ensure_one()
        if not self.m_destination_picking_id:
            raise UserError(_("No destination picking is linked yet."))
        return {
            "type": "ir.actions.act_window",
            "res_model": "stock.picking",
            "res_id": self.m_destination_picking_id.id,
            "view_mode": "form",
            "target": "current",
            "context": {
                "allowed_company_ids": [
                    self.m_source_company_id.id,
                    self.m_destination_company_id.id,
                ]
            },
        }

    def unlink(self):
        if self.env.context.get("module_uninstall"):
            return super().unlink()
        if self.filtered("m_intercompany_transaction_id"):
            raise ValidationError(
                _("Linked manual intercompany transfer requests cannot be deleted.")
            )
        return super().unlink()


class MeruCoreIntercompanyStockTransferLine(models.Model):
    _name = "merucore.intercompany.stock.transfer.line"
    _description = "MeruCore Intercompany Stock Transfer Line"
    _order = "m_sequence, id"

    m_sequence = fields.Integer(default=10)
    m_transfer_id = fields.Many2one(
        "merucore.intercompany.stock.transfer",
        required=True,
        ondelete="cascade",
        index=True,
    )
    m_product_id = fields.Many2one(
        "product.product",
        required=True,
        domain="[('type', '!=', 'service')]",
    )
    m_description = fields.Char()
    m_quantity = fields.Float(required=True, default=1.0, digits="Product Unit")
    m_uom_id = fields.Many2one(
        "uom.uom",
        required=True,
    )
    m_allowed_uom_ids = fields.Many2many(
        "uom.uom",
        compute="_compute_m_allowed_uom_ids",
    )
    m_owner_id = fields.Many2one("res.partner")
    m_lot_name = fields.Char(string="Lot / Serial")

    @api.onchange("m_product_id")
    def _onchange_m_product_id(self):
        if self.m_product_id and not self.m_uom_id:
            self.m_uom_id = self.m_product_id.uom_id
            self.m_description = self.m_description or self.m_product_id.display_name

    @api.depends("m_product_id")
    def _compute_m_allowed_uom_ids(self):
        for line in self:
            product_uom = line.m_product_id.uom_id
            if not product_uom:
                line.m_allowed_uom_ids = [fields.Command.clear()]
                continue
            reference_uom = product_uom.relative_uom_id or product_uom
            allowed_uoms = self.env["uom.uom"].search(
                [
                    "|",
                    ("id", "=", reference_uom.id),
                    ("relative_uom_id", "=", reference_uom.id),
                ]
            )
            line.m_allowed_uom_ids = [fields.Command.set(allowed_uoms.ids)]

    @api.constrains("m_quantity", "m_uom_id", "m_product_id")
    def m_check_quantities(self):
        for line in self:
            if line.m_quantity <= 0:
                raise ValidationError(_("Transfer line quantities must be strictly positive."))
            reference_uom = line.m_product_id.uom_id.relative_uom_id or line.m_product_id.uom_id
            line_reference = line.m_uom_id.relative_uom_id or line.m_uom_id
            if reference_uom != line_reference:
                raise ValidationError(
                    _("The selected unit of measure must share the product's UoM reference chain.")
                )
