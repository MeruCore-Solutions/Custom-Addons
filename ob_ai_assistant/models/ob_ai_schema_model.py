from odoo import _, fields, models


class OBAISchemaModel(models.Model):
    _name = "ob.ai.schema.model"
    _description = "AI Schema Registry Model"
    _order = "model_name, id"

    schema_version_id = fields.Many2one("ob.ai.schema.version", required=True, ondelete="cascade", index=True)
    ir_model_id = fields.Many2one("ir.model", string="Live Odoo Model", ondelete="set null")
    display_name = fields.Char(required=True)
    model_name = fields.Char(required=True, index=True)
    modules = fields.Char()
    info = fields.Text()
    transient = fields.Boolean()
    abstract = fields.Boolean()
    field_count = fields.Integer()
    relation_count = fields.Integer()
    field_ids = fields.One2many("ob.ai.schema.field", "schema_model_id", readonly=True)

    def action_open_fields(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Schema Fields"),
            "res_model": "ob.ai.schema.field",
            "view_mode": "list,form",
            "domain": [("schema_model_id", "=", self.id)],
            "context": {"default_schema_model_id": self.id, "default_schema_version_id": self.schema_version_id.id},
        }
