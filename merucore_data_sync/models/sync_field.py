from odoo import models, fields, api, _
from odoo.exceptions import UserError


class GenericSyncField(models.Model):
    _name = "generic.sync.field"
    _description = "Field Mapping for Sync"
    _order = "sequence, id"

    job_id = fields.Many2one(
        comodel_name="generic.sync.job",
        required=True,
        ondelete="cascade",
    )

    sequence = fields.Integer(default=10)

    source_field = fields.Char(
        required=True,
        help="Field name in the *source* Odoo (remote DB).",
    )

    target_field = fields.Char(
        required=True,
        help="Field name in the *target* Odoo (this DB).",
    )

    transform = fields.Selection(
        [
            ("copy", "Copy as-is"),
            ("int", "Cast to Integer"),
            ("float", "Cast to Float"),
            ("bool", "Cast to Boolean"),
            ("m2o_name", "Many2one by Name"),
            ("m2o_self_hierarchy", "Self hierarchy (mapping-based)"),
            ("x2many_map", "One2many / Many2many via Mapping"),
            ("eval", "Python expression"),
            ("binary", "Binary / Image"),
            ("attachment", "Attachment (binary via HTTP)"),
        ],
        default="copy",
        required=True,
        help="How to transform the source value before writing to target.",
    )

    python_expr = fields.Text(
        help="Python expression used when transform = 'eval'.\n"
             "Variables available:\n"
             "- value: source field value\n"
             "- src: full source record (dict)\n"
             "- env: Odoo environment\n"
             "Example: value.upper()",
    )

    required = fields.Boolean(
        default=False,
        help="If checked and value is missing, sync will fail for that record.",
    )

    missing_m2o_policy = fields.Selection(
        [
            ("create", "Create Related Record"),
            ("skip", "Skip Field"),
            ("stop", "Stop Execution"),
        ],
        default="skip",
        required=True,
        help=(
            "Defines what happens if a related many2one record "
            "does not exist during synchronization."
        ),
    )
    create_job_id = fields.Many2one(
        comodel_name="generic.sync.job",
    )
    post_process = fields.Boolean(
        string="Post-Process",
        default=False,
        help=(
            "If enabled, missing related records are queued and created after the "
            "main record is imported. Use this for heavy relation fields such as "
            "message_ids, attachment_ids, and other dependency-heavy mappings."
        ),
    )
    post_process_priority = fields.Integer(string='Priority')

    # ---------------------------------------------------------------------
    # UX helpers
    # ---------------------------------------------------------------------
    @api.onchange("target_field")
    def _onchange_target_field(self):
        if not self.job_id or not self.target_field:
            return

        target_model = self.job_id.target_model
        if not target_model:
            return

        model = self.env[target_model]
        field = model._fields.get(self.target_field)
        if not field:
            return

        # -----------------------------
        # Binary / Image fields
        # -----------------------------
        if field.type == "binary":
            # ir.attachment.datas is special
            if target_model == "ir.attachment" and self.target_field == "datas":
                self.transform = "attachment"
            else:
                self.transform = "binary"
            return

        # -----------------------------
        # Self hierarchy
        # -----------------------------
        if field.type == "many2one" and field.comodel_name == target_model:
            self.transform = "m2o_self_hierarchy"

        # -----------------------------
        # X2Many mapping
        # -----------------------------
        elif field.type in ("one2many", "many2many"):
            self.transform = "x2many_map"

    # ---------------------------------------------------------------------
    # Hard safety constraints
    # ---------------------------------------------------------------------
    @api.constrains("transform", "target_field")
    def _check_transform_target_type(self):
        for rec in self:
            if not rec.job_id or not rec.target_field:
                continue

            model = rec.env[rec.job_id.target_model]
            field = model._fields.get(rec.target_field)
            if not field:
                continue

            # -----------------------------
            # Binary / Image
            # -----------------------------
            if rec.transform == "binary" and field.type != "binary":
                raise UserError(_(
                    "Transform 'Binary / Image' can only be used with "
                    "binary fields (field: %s)."
                ) % rec.target_field)

            # -----------------------------
            # Attachment
            # -----------------------------
            if rec.transform == "attachment":
                if not (
                        rec.job_id.target_model == "ir.attachment"
                        and rec.target_field == "datas"
                        and field.type == "binary"
                ):
                    raise UserError(_(
                        "Transform 'Attachment' can only be used for "
                        "ir.attachment.datas."
                    ))

            # -----------------------------
            # X2Many
            # -----------------------------
            if rec.transform == "x2many_map" and field.type not in ("one2many", "many2many"):
                raise UserError(_(
                    "Transform 'x2many_map' can only be used with "
                    "one2many or many2many fields (field: %s)."
                ) % rec.target_field)

            # -----------------------------
            # Self hierarchy
            # -----------------------------
            if rec.transform == "m2o_self_hierarchy" and field.type != "many2one":
                raise UserError(_(
                    "Transform 'm2o_self_hierarchy' can only be used with "
                    "many2one fields (field: %s)."
                ) % rec.target_field)

    @api.constrains("transform", "missing_m2o_policy")
    def _check_x2many_policy(self):
        for rec in self:

            if rec.transform == "attachment" and rec.missing_m2o_policy != "skip":
                raise UserError(_(
                    "Attachment fields do not support missing-record policies. "
                    "Use 'Skip Field'."
                ))

    @api.constrains("post_process", "transform", "missing_m2o_policy", "create_job_id", "required")
    def _check_post_process_configuration(self):
        allowed_transforms = {"m2o_name", "m2o_self_hierarchy", "x2many_map"}
        for rec in self:
            if not rec.post_process:
                continue

            if rec.transform not in allowed_transforms:
                raise UserError(_(
                    "Post-process can only be enabled for relation mappings "
                    "(many2one/self hierarchy/x2many)."
                ))

            if rec.missing_m2o_policy != "create":
                raise UserError(_(
                    "Post-process requires the missing-record policy to be "
                    "'Create Related Record'."
                ))

            if not rec.create_job_id:
                raise UserError(_(
                    "Post-process requires a Create Job so the missing records "
                    "can be imported later."
                ))

            if rec.required:
                raise UserError(_(
                    "Required fields cannot be marked as post-process because the "
                    "main record may not be creatable without them."
                ))
