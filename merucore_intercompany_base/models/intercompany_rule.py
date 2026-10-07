from psycopg2 import IntegrityError

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class MeruCoreIntercompanyRule(models.Model):
    _name = "merucore.intercompany.rule"
    _description = "MeruCore Intercompany Rule"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "m_sequence, id"

    m_name = fields.Char(required=True, tracking=True, translate=True)
    m_active = fields.Boolean(default=True, tracking=True)
    m_sequence = fields.Integer(default=10)
    m_source_company_id = fields.Many2one(
        "res.company",
        required=True,
        index=True,
        ondelete="restrict",
        tracking=True,
    )
    m_destination_company_id = fields.Many2one(
        "res.company",
        required=True,
        index=True,
        ondelete="restrict",
        tracking=True,
    )
    m_direction = fields.Char(
        compute="m_compute_direction",
        store=True,
    )
    m_responsible_user_id = fields.Many2one(
        "res.users",
        string="Responsible",
        tracking=True,
        ondelete="set null",
    )
    m_auto_retry = fields.Boolean(default=False)
    m_max_retry_count = fields.Integer(default=3)
    m_retry_delay_minutes = fields.Integer(default=15)
    m_notify_on_warning = fields.Boolean(default=True)
    m_notify_on_failure = fields.Boolean(default=True)
    m_notes = fields.Html()
    m_transaction_ids = fields.One2many(
        "merucore.intercompany.transaction",
        "m_rule_id",
        string="Transactions",
    )
    m_transaction_count = fields.Integer(
        compute="m_compute_transaction_count",
    )

    def init(self):
        self.env.cr.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
                merucore_intercompany_rule_active_pair_uniq
            ON merucore_intercompany_rule (m_source_company_id, m_destination_company_id)
            WHERE m_active
            """
        )

    @api.model_create_multi
    def create(self, vals_list):
        try:
            return super().create(vals_list)
        except IntegrityError as error:
            raise ValidationError(
                _("An active directional rule already exists for this source and destination company pair.")
            ) from error

    @api.depends("m_source_company_id", "m_destination_company_id")
    def m_compute_direction(self):
        for rule in self:
            if rule.m_source_company_id and rule.m_destination_company_id:
                rule.m_direction = _(
                    "%(source)s -> %(destination)s",
                    source=rule.m_source_company_id.display_name,
                    destination=rule.m_destination_company_id.display_name,
                )
            else:
                rule.m_direction = False

    @api.depends("m_transaction_ids")
    def m_compute_transaction_count(self):
        grouped = self.env["merucore.intercompany.transaction"]._read_group(
            [("m_rule_id", "in", self.ids)],
            ["m_rule_id"],
            ["__count"],
        )
        counts = {rule.id: count for rule, count in grouped}
        for rule in self:
            rule.m_transaction_count = counts.get(rule.id, 0)

    @api.depends("m_name", "m_source_company_id", "m_destination_company_id")
    def _compute_display_name(self):
        for rule in self:
            direction = rule.m_direction or _("%(source)s -> %(destination)s",
                source=rule.m_source_company_id.display_name or _("Unknown"),
                destination=rule.m_destination_company_id.display_name or _("Unknown"),
            )
            rule.display_name = _("%(name)s [%(direction)s]", name=rule.m_name, direction=direction)

    @api.constrains("m_source_company_id", "m_destination_company_id")
    def m_check_company_pair(self):
        for rule in self:
            if rule.m_source_company_id and rule.m_source_company_id == rule.m_destination_company_id:
                raise ValidationError(_("Source and destination companies must be different."))

    @api.constrains("m_max_retry_count", "m_retry_delay_minutes")
    def m_check_retry_settings(self):
        for rule in self:
            if rule.m_max_retry_count < 0:
                raise ValidationError(_("Maximum retry count cannot be negative."))
            if rule.m_retry_delay_minutes < 0:
                raise ValidationError(_("Retry delay cannot be negative."))

    @api.constrains("m_source_company_id", "m_destination_company_id", "m_active")
    def m_check_duplicate_active_direction(self):
        for rule in self.filtered("m_active"):
            duplicate = self.search(
                [
                    ("id", "!=", rule.id),
                    ("m_active", "=", True),
                    ("m_source_company_id", "=", rule.m_source_company_id.id),
                    ("m_destination_company_id", "=", rule.m_destination_company_id.id),
                ],
                limit=1,
            )
            if duplicate:
                raise ValidationError(
                    _("An active directional rule already exists for this source and destination company pair.")
                )

    @api.constrains("m_responsible_user_id", "m_source_company_id", "m_destination_company_id")
    def m_check_responsible_user_companies(self):
        for rule in self.filtered("m_responsible_user_id"):
            allowed_companies = rule.m_responsible_user_id.company_ids
            if rule.m_source_company_id not in allowed_companies or rule.m_destination_company_id not in allowed_companies:
                raise ValidationError(
                    _("The responsible user must have access to both the source and destination companies.")
                )

    def m_action_archive(self):
        self.with_context(m_intercompany_internal_write=True).write({"m_active": False})

    def m_action_restore(self):
        self.with_context(m_intercompany_internal_write=True).write({"m_active": True})

    def m_action_open_transactions(self):
        self.ensure_one()
        action = self.env["ir.actions.actions"]._for_xml_id(
            "merucore_intercompany_base.m_action_intercompany_transactions"
        )
        action["domain"] = [("m_rule_id", "=", self.id)]
        action["context"] = {
            "default_m_rule_id": self.id,
            "default_m_source_company_id": self.m_source_company_id.id,
            "default_m_destination_company_id": self.m_destination_company_id.id,
            "allowed_company_ids": (self.m_source_company_id | self.m_destination_company_id).ids,
        }
        return action

    def unlink(self):
        if self.env.context.get("module_uninstall"):
            return super().unlink()
        self.check_access("unlink")
        if self.filtered("m_transaction_ids"):
            raise ValidationError(
                _("Rules with existing transactions cannot be deleted. Archive them instead to preserve audit integrity.")
            )
        return super().unlink()
