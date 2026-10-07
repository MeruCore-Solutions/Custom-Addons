from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class MeruCoreIntercompanyRule(models.Model):
    _inherit = "merucore.intercompany.rule"

    m_stock_sync_enabled = fields.Boolean(
        string="Stock Synchronization",
        default=False,
        tracking=True,
    )
    m_stock_workflow = fields.Selection(
        selection=[
            ("automatic", "Automatic Counterpart Receipts"),
            ("manual_transfer", "Manual Transfer Requests"),
            ("both", "Automatic and Manual"),
        ],
        string="Stock Workflow",
        default="automatic",
        tracking=True,
    )
    m_stock_product_mapping_strategy = fields.Selection(
        selection=[
            ("same_product", "Same Product"),
            ("internal_reference", "Internal Reference"),
            ("barcode", "Barcode"),
        ],
        string="Stock Product Mapping",
        default="same_product",
        tracking=True,
    )
    m_stock_sync_lots = fields.Boolean(default=True)
    m_stock_sync_packages = fields.Boolean(default=True)
    m_stock_sync_owners = fields.Boolean(default=True)
    m_stock_auto_confirm_counterpart = fields.Boolean(default=True)
    m_stock_auto_assign_counterpart = fields.Boolean(default=True)
    m_stock_cancel_counterpart = fields.Boolean(default=True)
    m_stock_transit_location_id = fields.Many2one(
        "stock.location",
        string="Transit Location",
        check_company=False,
        tracking=True,
        domain="[('usage', '=', 'transit')]",
        default=lambda self: self.env.ref(
            "stock.stock_location_inter_company",
            raise_if_not_found=False,
        ),
    )
    m_stock_source_picking_type_id = fields.Many2one(
        "stock.picking.type",
        string="Manual Source Picking Type",
        tracking=True,
        domain="[('code', '=', 'outgoing')]",
        check_company=False,
    )
    m_stock_destination_picking_type_id = fields.Many2one(
        "stock.picking.type",
        string="Destination Receipt Type",
        tracking=True,
        domain="[('code', '=', 'incoming')]",
        check_company=False,
    )
    m_stock_destination_location_id = fields.Many2one(
        "stock.location",
        string="Destination Stock Location",
        tracking=True,
        check_company=False,
        domain="[('usage', 'in', ('internal', 'transit'))]",
    )

    @api.constrains(
        "m_stock_sync_enabled",
        "m_stock_workflow",
        "m_stock_source_picking_type_id",
        "m_stock_destination_picking_type_id",
        "m_stock_destination_location_id",
        "m_stock_transit_location_id",
        "m_source_company_id",
        "m_destination_company_id",
        "m_responsible_user_id",
    )
    def m_check_stock_configuration(self):
        for rule in self.filtered("m_stock_sync_enabled"):
            if rule.m_source_company_id == rule.m_destination_company_id:
                raise ValidationError(_("Stock synchronization requires two distinct companies."))
            if rule.m_stock_workflow in {"automatic", "both"} and not rule.m_responsible_user_id:
                raise ValidationError(
                    _("A responsible user is required when automatic stock synchronization is enabled.")
                )
            if (
                rule.m_stock_source_picking_type_id
                and rule.m_stock_source_picking_type_id.company_id
                and rule.m_stock_source_picking_type_id.company_id != rule.m_source_company_id
            ):
                raise ValidationError(_("The manual source picking type must belong to the source company."))
            if (
                rule.m_stock_source_picking_type_id
                and rule.m_stock_source_picking_type_id.code != "outgoing"
            ):
                raise ValidationError(_("The manual source picking type must be an outgoing operation type."))
            if (
                rule.m_stock_destination_picking_type_id
                and rule.m_stock_destination_picking_type_id.company_id
                and rule.m_stock_destination_picking_type_id.company_id != rule.m_destination_company_id
            ):
                raise ValidationError(
                    _("The destination receipt type must belong to the destination company.")
                )
            if (
                rule.m_stock_destination_picking_type_id
                and rule.m_stock_destination_picking_type_id.code != "incoming"
            ):
                raise ValidationError(_("The destination receipt type must be an incoming operation type."))
            if (
                rule.m_stock_destination_location_id
                and rule.m_stock_destination_location_id.company_id
                and rule.m_stock_destination_location_id.company_id != rule.m_destination_company_id
            ):
                raise ValidationError(
                    _("The destination stock location must belong to the destination company or be shared.")
                )
            if rule.m_stock_transit_location_id and rule.m_stock_transit_location_id.usage != "transit":
                raise ValidationError(_("The transit location must be of type Transit."))

    def m_allows_stock_automatic_sync(self):
        self.ensure_one()
        return self.m_stock_sync_enabled and self.m_stock_workflow in {"automatic", "both"}

    def m_allows_manual_transfer(self):
        self.ensure_one()
        return self.m_stock_sync_enabled and self.m_stock_workflow in {"manual_transfer", "both"}

    def m_get_stock_transit_location(self):
        self.ensure_one()
        return self.m_stock_transit_location_id or self.env.ref(
            "stock.stock_location_inter_company",
            raise_if_not_found=False,
        )
