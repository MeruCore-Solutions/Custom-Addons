from odoo import _, api, fields, models


class OBAISchemaVersion(models.Model):
    _name = "ob.ai.schema.version"
    _description = "AI Schema Registry Version"
    _order = "create_date desc, id desc"

    name = fields.Char(required=True, default=lambda self: _("Schema Snapshot"))
    status = fields.Selection(
        [
            ("draft", "Draft"),
            ("running", "Running"),
            ("ready", "Ready"),
            ("error", "Error"),
            ("archived", "Archived"),
        ],
        default="draft",
        required=True,
        index=True,
    )
    trigger_source = fields.Selection(
        [
            ("manual", "Manual"),
            ("cron", "Cron"),
            ("auto", "Automatic"),
            ("conversation", "Conversation"),
        ],
        default="manual",
        required=True,
    )
    current = fields.Boolean(index=True)
    started_at = fields.Datetime()
    completed_at = fields.Datetime()
    duration_ms = fields.Integer(compute="_compute_duration_ms", store=False)
    checksum = fields.Char(index=True)
    odoo_version = fields.Char()
    module_count = fields.Integer(readonly=True)
    model_count = fields.Integer(readonly=True)
    field_count = fields.Integer(readonly=True)
    last_error = fields.Text(readonly=True)
    note = fields.Text()
    module_ids = fields.One2many("ob.ai.schema.module", "schema_version_id", readonly=True)
    schema_model_ids = fields.One2many("ob.ai.schema.model", "schema_version_id", readonly=True)
    schema_field_ids = fields.One2many("ob.ai.schema.field", "schema_version_id", readonly=True)

    @api.depends("started_at", "completed_at")
    def _compute_duration_ms(self):
        for record in self:
            if record.started_at and record.completed_at:
                record.duration_ms = int((record.completed_at - record.started_at).total_seconds() * 1000)
            else:
                record.duration_ms = 0

    @api.model
    def _cron_refresh_schema_registry(self):
        self.env["ob.ai.schema.service"].refresh_schema_registry(trigger_source="cron")

    def action_refresh_now(self):
        version = self.env["ob.ai.schema.service"].refresh_schema_registry(trigger_source="manual")
        return {
            "type": "ir.actions.act_window",
            "name": _("Schema Registry"),
            "res_model": "ob.ai.schema.version",
            "res_id": version.id,
            "view_mode": "form",
        }

    def action_mark_current(self):
        self.ensure_one()
        self.search([("current", "=", True), ("id", "!=", self.id)]).write({
            "current": False,
            "status": "archived",
        })
        self.write({
            "current": True,
            "status": "ready" if self.status != "error" else self.status,
        })
        return True

    def action_open_models(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Schema Models"),
            "res_model": "ob.ai.schema.model",
            "view_mode": "list,form",
            "domain": [("schema_version_id", "=", self.id)],
            "context": {"default_schema_version_id": self.id},
        }

    def action_open_fields(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Schema Fields"),
            "res_model": "ob.ai.schema.field",
            "view_mode": "list,form",
            "domain": [("schema_version_id", "=", self.id)],
            "context": {"default_schema_version_id": self.id},
        }

    def action_open_modules(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Schema Modules"),
            "res_model": "ob.ai.schema.module",
            "view_mode": "list,form",
            "domain": [("schema_version_id", "=", self.id)],
            "context": {"default_schema_version_id": self.id},
        }
