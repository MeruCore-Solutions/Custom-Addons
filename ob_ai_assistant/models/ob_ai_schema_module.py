from odoo import fields, models


class OBAISchemaModule(models.Model):
    _name = "ob.ai.schema.module"
    _description = "AI Schema Registry Module"
    _order = "technical_name, id"

    schema_version_id = fields.Many2one("ob.ai.schema.version", required=True, ondelete="cascade", index=True)
    technical_name = fields.Char(required=True, index=True)
    display_name = fields.Char(required=True)
    installed_version = fields.Char()
    latest_version = fields.Char()
    category_name = fields.Char()
    summary = fields.Text()
    application = fields.Boolean()
    auto_install = fields.Boolean()
    dependency_names = fields.Text()
