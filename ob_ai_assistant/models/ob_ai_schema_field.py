from odoo import fields, models


class OBAISchemaField(models.Model):
    _name = "ob.ai.schema.field"
    _description = "AI Schema Registry Field"
    _order = "schema_model_id, name, id"

    schema_version_id = fields.Many2one("ob.ai.schema.version", required=True, ondelete="cascade", index=True)
    schema_model_id = fields.Many2one("ob.ai.schema.model", required=True, ondelete="cascade", index=True)
    ir_model_field_id = fields.Many2one("ir.model.fields", string="Live Odoo Field", ondelete="set null")
    name = fields.Char(required=True, index=True)
    field_description = fields.Char(required=True)
    modules = fields.Char()
    ttype = fields.Char(required=True)
    relation = fields.Char()
    related = fields.Char()
    selection_json = fields.Json()
    required = fields.Boolean()
    readonly = fields.Boolean()
    store = fields.Boolean()
    index = fields.Boolean()
    copied = fields.Boolean()
    help_text = fields.Text()
