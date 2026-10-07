from odoo import _, api, fields, models


class OBAIAccessTemplate(models.Model):
    _name = "ob.ai.access.template"
    _description = "AI Access Template"
    _order = "sequence, name, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    allow_full_access = fields.Boolean(
        string="Admin Full Access",
        help="When enabled, users assigned to this template can access all readable fields on every active AI model without line-level reduction.",
    )
    company_id = fields.Many2one("res.company", string="Company", default=lambda self: self.env.company)
    description = fields.Text()
    user_ids = fields.Many2many(
        "res.users",
        "ob_ai_access_template_user_rel",
        "template_id",
        "user_id",
        string="Assigned Users",
    )
    line_ids = fields.One2many("ob.ai.access.template.line", "template_id", string="Model Policies")
    model_count = fields.Integer(compute="_compute_counts")
    active_line_count = fields.Integer(compute="_compute_counts")

    @api.depends("line_ids", "line_ids.active")
    def _compute_counts(self):
        for record in self:
            record.model_count = len(record.line_ids)
            record.active_line_count = len(record.line_ids.filtered("active"))

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records.action_sync_model_lines()
        return records

    def action_sync_model_lines(self):
        line_model = self.env["ob.ai.access.template.line"]
        allowed_model_model = self.env["ob.ai.allowed.model"]
        allowed_model_model.ensure_default_models()
        for template in self:
            all_lines = template.with_context(active_test=False).line_ids
            existing_allowed_model_ids = set(all_lines.mapped("allowed_model_id").ids)
            domain = [("active", "=", True)]
            if template.company_id:
                domain += ["|", ("company_id", "=", False), ("company_id", "=", template.company_id.id)]
            allowed_models = allowed_model_model.search(domain, order="company_id desc, sequence, id")
            create_vals = []
            for allowed_model in allowed_models:
                if allowed_model.id in existing_allowed_model_ids:
                    continue
                create_vals.append(line_model._prepare_create_values_from_allowed_model(allowed_model))
                create_vals[-1]["template_id"] = template.id
            if create_vals:
                line_model.create(create_vals)
        return True


class OBAIAccessTemplateLine(models.Model):
    _name = "ob.ai.access.template.line"
    _description = "AI Access Template Line"
    _order = "sequence, id"

    template_id = fields.Many2one("ob.ai.access.template", required=True, ondelete="cascade")
    company_id = fields.Many2one(related="template_id.company_id", store=True, readonly=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    allowed_model_id = fields.Many2one(
        "ob.ai.allowed.model",
        string="Allowed Model",
        required=True,
        domain="['|', ('company_id', '=', False), ('company_id', '=', company_id)]",
        ondelete="cascade",
    )
    model_id = fields.Many2one(related="allowed_model_id.model_id", store=True, readonly=True)
    allowed_field_ids = fields.Many2many(
        "ir.model.fields",
        "ob_ai_access_template_allowed_field_rel",
        "template_line_id",
        "field_id",
        string="Allowed Fields",
        domain="[('model_id', '=', model_id)]",
    )
    blocked_field_ids = fields.Many2many(
        "ir.model.fields",
        "ob_ai_access_template_blocked_field_rel",
        "template_line_id",
        "field_id",
        string="Blocked Fields",
        domain="[('model_id', '=', model_id)]",
    )
    max_record_count = fields.Integer(string="Max Records in Context", default=5)
    search_limit = fields.Integer(string="Search Limit", default=5)
    default_order = fields.Char(string="Default Search Order", default="write_date desc, id desc")
    reference_field_names = fields.Char(string="Reference Search Fields")
    name_field_names = fields.Char(string="Name Search Fields")
    date_field_names = fields.Char(string="Date Fields")
    allow_document_context = fields.Boolean(default=True)
    allow_chatter_posting = fields.Boolean()
    allow_activity_creation = fields.Boolean()
    allow_reminder_creation = fields.Boolean()
    allow_dashboard_generation = fields.Boolean(default=True)
    allow_validation = fields.Boolean(default=True)
    require_human_approval = fields.Boolean()
    sensitivity_level = fields.Selection(
        [
            ("general", "General"),
            ("accounting", "Accounting"),
            ("hr", "HR"),
            ("healthcare", "Healthcare"),
        ],
        default="general",
        required=True,
    )

    _template_model_unique = models.Constraint(
        "UNIQUE(template_id, allowed_model_id)",
        "Only one AI access-template line per template and allowed model is supported.",
    )

    @api.model
    def _prepare_create_values_from_allowed_model(self, allowed_model):
        allowed_model.ensure_one()
        return {
            "sequence": allowed_model.sequence,
            "allowed_model_id": allowed_model.id,
            "allowed_field_ids": [(6, 0, allowed_model.allowed_field_ids.ids)],
            "blocked_field_ids": [(6, 0, allowed_model.blocked_field_ids.ids)],
            "max_record_count": allowed_model.max_record_count,
            "search_limit": allowed_model.search_limit,
            "default_order": allowed_model.default_order,
            "reference_field_names": allowed_model.reference_field_names,
            "name_field_names": allowed_model.name_field_names,
            "date_field_names": allowed_model.date_field_names,
            "allow_document_context": allowed_model.allow_document_context,
            "allow_chatter_posting": allowed_model.allow_chatter_posting,
            "allow_activity_creation": allowed_model.allow_activity_creation,
            "allow_reminder_creation": allowed_model.allow_reminder_creation,
            "allow_dashboard_generation": allowed_model.allow_dashboard_generation,
            "allow_validation": allowed_model.allow_validation,
            "require_human_approval": allowed_model.require_human_approval,
            "sensitivity_level": allowed_model.sensitivity_level,
        }

    @api.onchange("allowed_model_id")
    def _onchange_allowed_model_id(self):
        for record in self:
            if not record.allowed_model_id:
                continue
            defaults = record._prepare_create_values_from_allowed_model(record.allowed_model_id)
            for field_name, value in defaults.items():
                if field_name in ("allowed_field_ids", "blocked_field_ids"):
                    record[field_name] = value
                elif field_name != "allowed_model_id":
                    record[field_name] = value

    def action_reset_from_allowed_model(self):
        for record in self:
            defaults = record._prepare_create_values_from_allowed_model(record.allowed_model_id)
            record.write({
                key: value
                for key, value in defaults.items()
                if key != "allowed_model_id"
            })
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Access template updated"),
                "message": _("The selected model policies were reset from their base allowed-model definitions."),
                "type": "success",
                "sticky": False,
            },
        }
