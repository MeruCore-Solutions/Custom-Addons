import uuid

from odoo import api, fields, models


class AccountMoveLine(models.Model):
    _inherit = "account.move.line"

    m_intercompany_transaction_id = fields.Many2one(
        "merucore.intercompany.transaction",
        related="move_id.m_intercompany_transaction_id",
        store=True,
        readonly=True,
        check_company=False,
    )
    m_intercompany_counterpart_line_ids = fields.Many2many(
        "account.move.line",
        compute="m_compute_intercompany_counterpart_line_ids",
        string="Intercompany Counterpart Lines",
    )
    m_intercompany_origin_line_id = fields.Many2one(
        "account.move.line",
        copy=False,
        index=True,
        check_company=False,
    )
    m_intercompany_line_key = fields.Char(
        copy=False,
        index=True,
    )
    m_intercompany_sync_state = fields.Selection(
        selection=[
            ("not_applicable", "Not Applicable"),
            ("pending", "Pending"),
            ("synced", "Synced"),
            ("warning", "Warning"),
            ("failed", "Failed"),
        ],
        default="not_applicable",
        copy=False,
        readonly=True,
    )
    m_intercompany_sync_version = fields.Integer(default=0, copy=False, readonly=True)
    m_intercompany_account_mapping_id = fields.Many2one(
        "merucore.intercompany.account.mapping",
        copy=False,
        readonly=True,
    )
    m_intercompany_tax_mapping_ids = fields.Many2many(
        "merucore.intercompany.tax.mapping",
        "m_intercompany_account_line_tax_rel",
        "m_line_id",
        "m_tax_mapping_id",
        copy=False,
        readonly=True,
    )
    m_intercompany_last_error = fields.Text(copy=False, readonly=True)
    m_intercompany_last_sync_at = fields.Datetime(copy=False, readonly=True)

    @api.depends("m_intercompany_transaction_id", "m_intercompany_line_key")
    def m_compute_intercompany_counterpart_line_ids(self):
        grouped = {}
        for line in self.filtered(lambda current: current.m_intercompany_transaction_id and current.m_intercompany_line_key):
            grouped.setdefault(
                (line.m_intercompany_transaction_id.id, line.m_intercompany_line_key),
                self.env["account.move.line"],
            )
            grouped[(line.m_intercompany_transaction_id.id, line.m_intercompany_line_key)] |= line
        search_domain = [
            ("m_intercompany_transaction_id", "in", [key[0] for key in grouped]),
            ("m_intercompany_line_key", "in", [key[1] for key in grouped]),
        ] if grouped else []
        candidates = self.env["account.move.line"].search(search_domain) if search_domain else self.env["account.move.line"]
        candidate_map = {}
        for candidate in candidates:
            candidate_map.setdefault(
                (candidate.m_intercompany_transaction_id.id, candidate.m_intercompany_line_key),
                self.env["account.move.line"],
            )
            candidate_map[(candidate.m_intercompany_transaction_id.id, candidate.m_intercompany_line_key)] |= candidate
        for line in self:
            matches = self.env["account.move.line"]
            if line.m_intercompany_transaction_id and line.m_intercompany_line_key:
                matches = candidate_map.get(
                    (line.m_intercompany_transaction_id.id, line.m_intercompany_line_key),
                    self.env["account.move.line"],
                ) - line
            line.m_intercompany_counterpart_line_ids = [fields.Command.set(matches.ids)]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("m_intercompany_line_key") and vals.get("display_type", "product") in {
                "product",
                "line_section",
                "line_subsection",
                "line_note",
            }:
                vals["m_intercompany_line_key"] = uuid.uuid4().hex
        lines = super().create(vals_list)
        if not self.env.context.get("m_skip_intercompany_account_sync"):
            lines.m_mark_parent_moves_pending()
        return lines

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get("m_skip_intercompany_account_sync"):
            self.m_mark_parent_moves_pending()
        return result

    def unlink(self):
        moves = self.move_id
        result = super().unlink()
        if not self.env.context.get("m_skip_intercompany_account_sync"):
            moves.m_mark_intercompany_pending()
        return result

    def copy_data(self, default=None):
        default = dict(default or {})
        default.update(
            {
                "m_intercompany_origin_line_id": False,
                "m_intercompany_line_key": False,
                "m_intercompany_sync_state": "not_applicable",
                "m_intercompany_sync_version": 0,
                "m_intercompany_account_mapping_id": False,
                "m_intercompany_tax_mapping_ids": False,
                "m_intercompany_last_error": False,
                "m_intercompany_last_sync_at": False,
            }
        )
        return super().copy_data(default=default)

    def read(self, fields=None, load="_classic_read"):
        rows = super().read(fields=fields, load=load)
        protected = {
            "m_intercompany_transaction_id",
            "m_intercompany_counterpart_line_ids",
            "m_intercompany_origin_line_id",
            "m_intercompany_account_mapping_id",
            "m_intercompany_tax_mapping_ids",
            "m_intercompany_last_error",
        }
        record_map = {line.id: line for line in self.browse([row["id"] for row in rows])}
        for row in rows:
            line = record_map.get(row["id"])
            if line and not line.move_id.m_intercompany_dual_company_access:
                for field_name in protected & set(row):
                    row[field_name] = False
        return rows

    def m_mark_parent_moves_pending(self):
        self.mapped("move_id").m_mark_intercompany_pending()
