from odoo import fields, models


class ExcelImportWizard(models.TransientModel):
    _name = "ob.excel.import.wizard"
    _description = "Excel Import Wizard"

    template_id = fields.Many2one(
        "ob.excel.import.template",
        required=True,
    )
    file = fields.Binary(required=True)
    filename = fields.Char(required=True)
    dry_run = fields.Boolean(default=False)

    def action_test_import(self):
        self.ensure_one()
        return self.template_id.run_import(
            file_content=self.file,
            filename=self.filename,
            dry_run=True,
        )

    def action_import_file(self):
        self.ensure_one()
        return self.template_id.run_import(
            file_content=self.file,
            filename=self.filename,
            dry_run=False,
        )
