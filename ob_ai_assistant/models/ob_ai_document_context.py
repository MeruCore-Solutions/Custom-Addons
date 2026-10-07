from odoo import api, fields, models


class OBAIDocumentContext(models.Model):
    _name = "ob.ai.document.context"
    _description = "AI Document Context"
    _order = "create_date desc, id desc"

    name = fields.Char(compute="_compute_name", store=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
    attachment_id = fields.Many2one("ir.attachment", required=True, ondelete="cascade")
    attachment_checksum = fields.Char(index=True)
    related_record_ref = fields.Reference(selection="_selection_reference_models", string="Related Record")
    source_conversation_id = fields.Many2one("ob.ai.conversation", string="Source Conversation", ondelete="set null")
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("ready", "Ready"),
            ("error", "Error"),
        ],
        default="ready",
        required=True,
    )
    context_type = fields.Selection(
        [
            ("attachment", "Attachment"),
            ("transcript", "Transcript"),
            ("note", "Note"),
        ],
        default="attachment",
        required=True,
    )
    extracted_text = fields.Text()
    character_count = fields.Integer()
    structured_payload = fields.Json(default=dict)
    structured_table_count = fields.Integer()
    structured_row_count = fields.Integer()
    extraction_engine = fields.Char()
    parse_metadata = fields.Json(default=dict)
    text_preview = fields.Text(compute="_compute_text_preview")
    error_message = fields.Text()

    _attachment_checksum_unique = models.Constraint(
        "UNIQUE(attachment_id, attachment_checksum)",
        "This attachment checksum is already cached.",
    )

    @api.depends("attachment_id", "attachment_checksum")
    def _compute_name(self):
        for record in self:
            checksum = (record.attachment_checksum or "")[:8]
            attachment_name = record.attachment_id.display_name or "Attachment"
            record.name = "%s %s" % (attachment_name, checksum) if checksum else attachment_name

    @api.depends("extracted_text")
    def _compute_text_preview(self):
        for record in self:
            record.text_preview = (record.extracted_text or "")[:500]

    def _selection_reference_models(self):
        return self.env["ob.ai.conversation"]._selection_reference_models()
