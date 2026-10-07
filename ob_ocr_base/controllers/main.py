import base64

from odoo import http, _
from odoo.exceptions import AccessError, ValidationError
from odoo.http import request


class OCRUploadController(http.Controller):

    @http.route("/ocr/upload", type="http", auth="user", methods=["POST"], csrf=False)
    def upload_document(self, **post):
        user = request.env.user
        if not user.has_group("ob_ocr_base.group_ocr_user"):
            raise AccessError(_("You do not have access to upload OCR documents."))

        upload = request.httprequest.files.get("file")
        if not upload:
            return request.make_json_response({"error": _("A file is required.")}, status=400)

        document_type_value = post.get("document_type")
        source_type = post.get("source_type") or "api"
        company_id = post.get("company_id")
        if source_type not in {"upload", "scanner", "email", "api"}:
            return request.make_json_response({"error": _("Invalid source_type value.")}, status=400)

        env = request.env["ob.ocr.document"].with_user(user)
        document_type = self._get_document_type(document_type_value)
        if not document_type:
            return request.make_json_response({"error": _("Unknown OCR document type.")}, status=400)

        company = user.company_id
        if company_id:
            company = request.env["res.company"].browse(int(company_id)).exists()
            if not company or company not in user.company_ids:
                raise AccessError(_("You cannot upload OCR documents for the selected company."))

        try:
            document = env.create({
                "document_type_id": document_type.id,
                "file": base64.b64encode(upload.read()),
                "filename": upload.filename,
                "mimetype": upload.mimetype,
                "source_type": source_type,
                "company_id": company.id,
                "user_id": user.id,
            })
            document.action_process_ocr()
        except ValidationError as exc:
            return request.make_json_response({"error": str(exc)}, status=400)

        return request.make_json_response({
            "id": document.id,
            "name": document.name,
            "state": document.state,
        })

    def _get_document_type(self, value):
        if not value:
            return request.env["ob.ocr.document.type"]
        model = request.env["ob.ocr.document.type"]
        if str(value).isdigit():
            return model.browse(int(value)).exists()
        return model.search([("code", "=", value)], limit=1)
