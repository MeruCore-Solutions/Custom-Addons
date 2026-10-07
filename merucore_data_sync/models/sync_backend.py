import ssl
import certifi
import xmlrpc.client

from odoo import models, fields, _
from odoo.exceptions import UserError


class GenericSyncBackend(models.Model):
    _name = "generic.sync.backend"
    _description = "External Odoo Backend for Sync"

    name = fields.Char(required=True)
    url = fields.Char(
        required=True,
        help="Base URL of the remote Odoo, e.g. https://v16.example.com",
    )
    db_name = fields.Char(required=True, string="Database")
    username = fields.Char(required=True)
    password = fields.Char(required=True)
    active = fields.Boolean(default=True)
    timeout = fields.Integer(
        default=60,
        help="Timeout (in seconds) for XML-RPC calls.",
    )

    def get_connection(self):
        """Return (uid, models_proxy) for XML-RPC."""
        self.ensure_one()

        try:
            ssl_context = ssl.create_default_context(
                cafile=certifi.where()
            )

            common = xmlrpc.client.ServerProxy(
                f"{self.url}/xmlrpc/2/common",
                allow_none=True,
                context=ssl_context,
            )

            uid = common.authenticate(
                self.db_name,
                self.username,
                self.password,
                {},
            )

            if not uid:
                raise UserError(
                    _("Authentication failed for backend %s") % self.name
                )

            models_proxy = xmlrpc.client.ServerProxy(
                f"{self.url}/xmlrpc/2/object",
                allow_none=True,
                context=ssl_context,
            )

            return uid, models_proxy

        except Exception as e:
            raise UserError(
                _("Error connecting to backend %(name)s: %(error)s")
                % {"name": self.name, "error": str(e)}
            )

