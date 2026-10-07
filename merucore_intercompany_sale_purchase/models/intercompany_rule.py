from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class MeruCoreIntercompanyRule(models.Model):
    _inherit = "merucore.intercompany.rule"

    m_sale_purchase_enabled = fields.Boolean(
        string="Sale & Purchase Synchronization",
        default=False,
        tracking=True,
    )
    m_trigger_document = fields.Selection(
        selection=[
            ("sale_order", "Sales Order"),
            ("purchase_order", "Purchase Order"),
            ("both", "Both"),
        ],
        string="Trigger Document",
        default="both",
        tracking=True,
    )
    m_creation_timing = fields.Selection(
        selection=[
            ("on_manual_action", "On Manual Action"),
            ("on_confirmation", "On Confirmation"),
        ],
        string="Creation Timing",
        default="on_confirmation",
        tracking=True,
    )
    m_counterpart_document_state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("confirmed", "Confirmed"),
        ],
        string="Counterpart Document State",
        default="draft",
        tracking=True,
    )
    m_sync_direction = fields.Selection(
        selection=[
            ("source_to_destination", "Source to Destination"),
            ("destination_to_source", "Destination to Source"),
            ("bidirectional", "Bidirectional"),
        ],
        string="Synchronization Direction",
        default="source_to_destination",
        tracking=True,
    )
    m_sync_header_values = fields.Boolean(default=True)
    m_sync_order_lines = fields.Boolean(default=True)
    m_sync_quantities = fields.Boolean(default=True)
    m_sync_unit_prices = fields.Boolean(default=False)
    m_sync_discounts = fields.Boolean(default=False)
    m_sync_descriptions = fields.Boolean(default=True)
    m_sync_planned_dates = fields.Boolean(default=True)
    m_sync_uom = fields.Boolean(default=True)
    m_allow_counterpart_line_creation = fields.Boolean(default=True)
    m_allow_counterpart_line_deletion = fields.Boolean(default=False)
    m_allow_sync_after_confirmation = fields.Boolean(default=False)
    m_cancel_counterpart = fields.Boolean(default=False)
    m_company_partner_validation = fields.Boolean(default=True)
    m_price_strategy = fields.Selection(
        selection=[
            ("source_document", "Source Document"),
            ("destination_pricelist", "Destination Pricelist"),
            ("product_cost", "Product Cost"),
            ("cost_plus", "Cost Plus"),
        ],
        string="Price Strategy",
        default="source_document",
        tracking=True,
    )
    m_cost_plus_percentage = fields.Float(
        string="Cost Plus Percentage",
        default=0.0,
    )
    m_currency_strategy = fields.Selection(
        selection=[
            ("destination_company_currency", "Destination Company Currency"),
            ("source_document_currency", "Source Document Currency"),
            ("destination_pricelist_currency", "Destination Pricelist Currency"),
        ],
        string="Currency Strategy",
        default="destination_company_currency",
        tracking=True,
    )
    m_tax_strategy = fields.Selection(
        selection=[
            ("destination_fiscal_position", "Destination Fiscal Position"),
            ("destination_product_taxes", "Destination Product Taxes"),
            ("no_taxes", "No Taxes"),
        ],
        string="Tax Strategy",
        default="destination_fiscal_position",
        tracking=True,
    )
    m_product_mapping_strategy = fields.Selection(
        selection=[
            ("same_product", "Same Product"),
            ("internal_reference", "Internal Reference"),
            ("barcode", "Barcode"),
        ],
        string="Product Mapping",
        default="same_product",
        tracking=True,
    )
    m_conflict_policy = fields.Selection(
        selection=[
            ("block_and_review", "Block and Review"),
            ("source_wins", "Source Wins"),
            ("destination_wins", "Destination Wins"),
        ],
        string="Conflict Policy",
        default="block_and_review",
        tracking=True,
    )
    m_confirm_counterpart_automatically = fields.Boolean(default=False)

    @api.constrains(
        "m_sale_purchase_enabled",
        "m_cost_plus_percentage",
        "m_counterpart_document_state",
        "m_confirm_counterpart_automatically",
        "m_responsible_user_id",
        "m_source_company_id",
        "m_destination_company_id",
    )
    def m_check_sale_purchase_configuration(self):
        for rule in self.filtered("m_sale_purchase_enabled"):
            if rule.m_source_company_id == rule.m_destination_company_id:
                raise ValidationError(_("Sale and purchase synchronization requires two distinct companies."))
            if rule.m_cost_plus_percentage < 0:
                raise ValidationError(_("Cost-plus percentage cannot be negative."))
            if (
                rule.m_counterpart_document_state == "confirmed"
                or rule.m_confirm_counterpart_automatically
                or rule.m_creation_timing == "on_confirmation"
            ) and not rule.m_responsible_user_id:
                raise ValidationError(
                    _("A responsible user is required when confirmation-time automation or counterpart confirmation is enabled.")
                )

    def m_requires_counterpart_confirmation(self):
        self.ensure_one()
        return self.m_counterpart_document_state == "confirmed" or self.m_confirm_counterpart_automatically

    def m_allows_sale_trigger(self):
        self.ensure_one()
        return self.m_sale_purchase_enabled and self.m_trigger_document in {"sale_order", "both"}

    def m_allows_purchase_trigger(self):
        self.ensure_one()
        return self.m_sale_purchase_enabled and self.m_trigger_document in {"purchase_order", "both"}
