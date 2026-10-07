from odoo import _, api, fields, models
from odoo.exceptions import UserError


class MeruCoreIntercompanyMixin(models.AbstractModel):
    _name = "merucore.intercompany.mixin"
    _description = "MeruCore Intercompany Document Link Mixin"

    m_intercompany_transaction_id = fields.Many2one(
        "merucore.intercompany.transaction",
        copy=False,
        index=True,
        check_company=False,
    )
    m_is_intercompany = fields.Boolean(
        compute="m_compute_is_intercompany",
        store=True,
    )
    m_intercompany_health_state = fields.Selection(
        related="m_intercompany_transaction_id.m_health_state",
        string="Intercompany Health",
        store=True,
        readonly=True,
    )
    m_intercompany_source_document = fields.Boolean(
        compute="m_compute_intercompany_document_context",
    )
    m_intercompany_counterpart_model = fields.Char(
        compute="m_compute_intercompany_document_context",
    )
    m_intercompany_counterpart_res_id = fields.Integer(
        compute="m_compute_intercompany_document_context",
    )

    @api.depends("m_intercompany_transaction_id")
    def m_compute_is_intercompany(self):
        for record in self:
            record.m_is_intercompany = bool(record.m_intercompany_transaction_id)

    @api.depends(
        "m_intercompany_transaction_id",
        "m_intercompany_transaction_id.m_source_model",
        "m_intercompany_transaction_id.m_source_res_id",
        "m_intercompany_transaction_id.m_destination_model",
        "m_intercompany_transaction_id.m_destination_res_id",
    )
    def m_compute_intercompany_document_context(self):
        for record in self:
            transaction = record.m_intercompany_transaction_id
            is_source = bool(
                transaction
                and transaction.m_source_model == record._name
                and transaction.m_source_res_id == record.id
            )
            if transaction and is_source:
                record.m_intercompany_counterpart_model = transaction.m_destination_model
                record.m_intercompany_counterpart_res_id = transaction.m_destination_res_id
            elif transaction:
                record.m_intercompany_counterpart_model = transaction.m_source_model
                record.m_intercompany_counterpart_res_id = transaction.m_source_res_id
            else:
                record.m_intercompany_counterpart_model = False
                record.m_intercompany_counterpart_res_id = False
            record.m_intercompany_source_document = is_source

    def m_action_open_intercompany_transaction(self):
        self.ensure_one()
        if not self.m_intercompany_transaction_id:
            raise UserError(_("No intercompany transaction is linked to this record."))
        return self.m_intercompany_transaction_id.m_action_open_transaction_form()

    def m_action_open_intercompany_counterpart(self):
        self.ensure_one()
        if not self.m_intercompany_transaction_id:
            raise UserError(_("No intercompany transaction is linked to this record."))
        if self.m_intercompany_source_document:
            return self.m_intercompany_transaction_id.m_action_open_destination_document()
        return self.m_intercompany_transaction_id.m_action_open_source_document()
