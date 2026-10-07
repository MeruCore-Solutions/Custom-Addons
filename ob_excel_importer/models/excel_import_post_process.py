import logging

from datetime import date, datetime, time

from dateutil.relativedelta import relativedelta

from odoo import _, Command, fields, models
from odoo.exceptions import UserError
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)


class ExcelImportPostProcess(models.Model):
    _name = "ob.excel.import.post.process"
    _description = "Excel Import Post Process"
    _order = "priority, id"

    template_id = fields.Many2one(
        "ob.excel.import.template",
        required=True,
        ondelete="cascade",
    )
    log_id = fields.Many2one("ob.excel.import.log")
    type = fields.Selection(
        [
            ("python", "Python"),
            ("relation_update", "Relation Update"),
            ("custom", "Custom"),
        ],
        default="python",
        required=True,
    )
    priority = fields.Integer(default=10)
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("done", "Done"),
            ("failed", "Failed"),
        ],
        default="pending",
    )
    res_model = fields.Char()
    res_ids = fields.Json()
    python_code = fields.Text()
    message = fields.Text()

    def execute(self):
        for process in self:
            process._execute_single()

    def _execute_single(self):
        self.ensure_one()
        records = self.env[self.res_model].browse(self.res_ids or []) if self.res_model and self.env.registry.get(self.res_model) else self.env["ir.model"]
        messages = []

        def hook_log(message, level="info"):
            messages.append("[%s] %s" % (level, message))
            log_method = getattr(_logger, level, _logger.info)
            log_method("%s", message)

        localdict = {
            "env": self.env,
            "template": self.template_id,
            "process": self,
            "records": records,
            "datetime": datetime,
            "date": date,
            "time": time,
            "relativedelta": relativedelta,
            "UserError": UserError,
            "Command": Command,
            "log": hook_log,
            "_logger": _logger,
        }
        try:
            if not self.python_code:
                raise UserError(_("Python code is required to execute this post process."))
            safe_eval(self.python_code.strip(), localdict, mode="exec", nocopy=True)
            self.write({
                "state": "done",
                "message": "\n".join(messages) or _("Post process executed successfully."),
            })
        except Exception as exc:
            self.write({
                "state": "failed",
                "message": str(exc),
            })
            raise
