from odoo import models, fields, api


class GenericSyncRecordMap(models.Model):
    _name = "generic.sync.record.map"
    _description = "Source → Destination Record Mapping"
    _rec_name = "display_name"

    _uniq_job_source = models.Constraint(
        "unique(job_id, source_model, source_record_id)",
        "This source record is already mapped for this job.",
    )

    job_id = fields.Many2one(
        "generic.sync.job",
        required=True,
        ondelete="cascade",
    )

    source_model = fields.Char(required=True)
    source_record_id = fields.Char(
        required=True,
        help="ID of the record in SOURCE system (string to support UUIDs)",
    )

    target_model = fields.Char(required=True)

    # store target ID as plain integer so we can point to ANY model
    target_record_id = fields.Integer(
        string="Target Record ID",
        required=True,
        help="ID of the record in TARGET system",
    )
    target_record_ref_id = fields.Many2oneReference(
        string="Target Record ID",
        model_field='target_model',
        store=True,
        compute="_compute_target_record_ref_id",
        help="ID of the record in TARGET system",
    )
    vals = fields.Json()

    display_name = fields.Char(compute="_compute_display_name", store=True)

    active = fields.Boolean(default=True)

    @api.depends('target_record_id')
    def _compute_target_record_ref_id(self):
        for rec in self:
            rec.target_record_ref_id = rec.target_record_id

    @api.depends("source_model", "source_record_id", "target_model", "target_record_id")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = (
                f"{rec.source_model}:{rec.source_record_id} → "
                f"{rec.target_model}:{rec.target_record_id}"
            )
