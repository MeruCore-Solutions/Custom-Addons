from odoo import _, fields, models
from odoo.exceptions import UserError


class OBAIKPISnapshot(models.Model):
    _name = "ob.ai.kpi.snapshot"
    _description = "AI KPI Snapshot"
    _order = "create_date desc, id desc"

    name = fields.Char(required=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company)
    user_id = fields.Many2one("res.users", string="Requested By", default=lambda self: self.env.user, required=True)
    source_conversation_id = fields.Many2one("ob.ai.conversation", string="Source Conversation", ondelete="set null")
    template_id = fields.Many2one("ob.ai.prompt.template", string="Prompt Template", ondelete="set null")
    provider_id = fields.Many2one("ob.ai.provider", string="Provider")
    model_id = fields.Many2one("ob.ai.model", string="Model")
    intent_type = fields.Selection(selection=lambda self: self.env["ob.ai.prompt.template"]._fields["intent_type"].selection)
    target_model = fields.Char()
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("done", "Done"),
            ("error", "Error"),
        ],
        default="done",
        required=True,
    )
    summary_text = fields.Text()
    generated_with_ai = fields.Boolean()
    line_ids = fields.One2many("ob.ai.kpi.snapshot.line", "snapshot_id", string="Lines")
    export_pdf_attachment_id = fields.Many2one("ir.attachment", string="PDF Export", readonly=True, ondelete="set null")
    export_image_attachment_id = fields.Many2one("ir.attachment", string="Image Export", readonly=True, ondelete="set null")

    def action_generate_pdf_dashboard(self):
        self.ensure_one()
        self.env["ob.ai.export.service"].export_snapshot_assets(self, include_pdf=True, include_image=False)
        return self.action_download_pdf_dashboard()

    def action_generate_image_dashboard(self):
        self.ensure_one()
        self.env["ob.ai.export.service"].export_snapshot_assets(self, include_pdf=False, include_image=True)
        return self.action_download_image_dashboard()

    def action_download_pdf_dashboard(self):
        self.ensure_one()
        attachment = self.export_pdf_attachment_id.exists()
        if not attachment:
            raise UserError(_("Generate a PDF export first."))
        return {
            "type": "ir.actions.act_url",
            "url": "/web/content/%s?download=true" % attachment.id,
            "target": "self",
        }

    def action_download_image_dashboard(self):
        self.ensure_one()
        attachment = self.export_image_attachment_id.exists()
        if not attachment:
            raise UserError(_("Generate an image export first."))
        return {
            "type": "ir.actions.act_url",
            "url": "/web/content/%s?download=true" % attachment.id,
            "target": "self",
        }


class OBAIKPISnapshotLine(models.Model):
    _name = "ob.ai.kpi.snapshot.line"
    _description = "AI KPI Snapshot Line"
    _order = "sequence, id"

    snapshot_id = fields.Many2one("ob.ai.kpi.snapshot", required=True, ondelete="cascade")
    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    metric_code = fields.Char(required=True)
    model_name = fields.Char()
    value_float = fields.Float()
    value_char = fields.Char()
    note = fields.Text()
    domain_summary = fields.Char()
