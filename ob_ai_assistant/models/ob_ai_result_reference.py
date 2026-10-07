from odoo import _, api, fields, models


class OBAIResultReference(models.Model):
    _name = "ob.ai.result.reference"
    _description = "AI Result Reference"
    _order = "memory_state_id, sequence, id"

    name = fields.Char(compute="_compute_name")
    memory_state_id = fields.Many2one("ob.ai.memory.state", ondelete="cascade", required=True)
    trace_id = fields.Many2one("ob.ai.investigation.trace", ondelete="set null")
    conversation_id = fields.Many2one("ob.ai.conversation", ondelete="cascade", required=True)
    company_id = fields.Many2one("res.company", default=lambda self: self.env.company, required=True)
    user_id = fields.Many2one("res.users", default=lambda self: self.env.user, required=True)
    sequence = fields.Integer(default=10)
    model_name = fields.Char(required=True)
    record_id_value = fields.Integer()
    record_ref = fields.Char(required=True, index=True)
    display_name = fields.Char()
    summary_line = fields.Char()

    @api.depends("display_name", "record_ref")
    def _compute_name(self):
        for record in self:
            record.name = record.display_name or record.record_ref or _("AI Result Reference")
