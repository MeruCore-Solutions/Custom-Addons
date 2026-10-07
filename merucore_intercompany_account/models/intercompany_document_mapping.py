from odoo import fields, models


class MeruCoreIntercompanyDocumentMapping(models.Model):
    _name = "merucore.intercompany.document.mapping"
    _description = "MeruCore Intercompany Document Mapping"
    _order = "id"

    m_transaction_id = fields.Many2one(
        "merucore.intercompany.transaction",
        required=True,
        ondelete="cascade",
        index=True,
    )
    m_move_id = fields.Many2one(
        "account.move",
        required=True,
        ondelete="restrict",
        index=True,
        check_company=False,
    )
    m_company_id = fields.Many2one(
        "res.company",
        related="m_move_id.company_id",
        store=True,
        readonly=True,
    )
    m_role = fields.Selection(
        selection=[
            ("source_customer_invoice", "Source Customer Invoice"),
            ("destination_vendor_bill", "Destination Vendor Bill"),
            ("source_vendor_bill", "Source Vendor Bill"),
            ("destination_customer_invoice", "Destination Customer Invoice"),
            ("source_customer_refund", "Source Customer Refund"),
            ("destination_vendor_refund", "Destination Vendor Refund"),
            ("source_vendor_refund", "Source Vendor Refund"),
            ("destination_customer_refund", "Destination Customer Refund"),
        ],
        required=True,
        index=True,
    )
    m_document_key = fields.Char(required=True, index=True, copy=False)
    m_origin_move_id = fields.Many2one(
        "account.move",
        ondelete="set null",
        check_company=False,
        copy=False,
    )
    m_is_primary = fields.Boolean(default=True, copy=False)

    _m_intercompany_document_mapping_unique = models.Constraint(
        "UNIQUE(m_transaction_id, m_move_id, m_role)",
        "Each intercompany transaction can only link the same accounting move once for a given role.",
    )
