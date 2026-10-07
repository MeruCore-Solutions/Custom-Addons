import base64
import re
from io import BytesIO

from odoo import _, fields, models
from odoo.exceptions import UserError


class OBAIExportService(models.AbstractModel):
    _name = "ob.ai.export.service"
    _description = "AI Export Service"

    def export_snapshot_assets(self, snapshot, conversation=False, include_pdf=False, include_image=False):
        snapshot = snapshot.exists()
        if not snapshot:
            raise UserError(_("No KPI snapshot is available to export."))
        snapshot.ensure_one()
        include_pdf = bool(include_pdf)
        include_image = bool(include_image)
        if not include_pdf and not include_image:
            include_pdf = True

        created_attachments = self.env["ir.attachment"]
        summary_parts = []
        action_parts = []

        if include_pdf:
            pdf_bytes = self._render_snapshot_pdf(snapshot)
            pdf_attachment = self._create_or_update_attachment(
                snapshot,
                binary_content=pdf_bytes,
                file_name=self._build_file_name(snapshot, "pdf"),
                mimetype="application/pdf",
                existing_attachment=snapshot.export_pdf_attachment_id,
            )
            snapshot.sudo().write({"export_pdf_attachment_id": pdf_attachment.id})
            created_attachments |= pdf_attachment
            summary_parts.append(_("PDF dashboard: %s", self._download_url(pdf_attachment)))
            action_parts.append("dashboard_pdf_generated")

        if include_image:
            image_bytes = self._render_snapshot_image(snapshot)
            image_attachment = self._create_or_update_attachment(
                snapshot,
                binary_content=image_bytes,
                file_name=self._build_file_name(snapshot, "png"),
                mimetype="image/png",
                existing_attachment=snapshot.export_image_attachment_id,
            )
            snapshot.sudo().write({"export_image_attachment_id": image_attachment.id})
            created_attachments |= image_attachment
            summary_parts.append(_("Image dashboard: %s", self._download_url(image_attachment)))
            action_parts.append("dashboard_image_generated")

        return {
            "action_performed": " + ".join(action_parts) if action_parts else "dashboard_export_generated",
            "summary_text": summary_parts and _(
                "Dashboard export completed.\n%s",
                "\n".join("- %s" % line for line in summary_parts),
            ) or _("Dashboard export completed."),
            "attachment_ids": created_attachments.ids,
            "urls": [self._download_url(attachment) for attachment in created_attachments],
        }

    def _render_snapshot_pdf(self, snapshot):
        try:
            from reportlab.lib import colors
            from reportlab.lib.pagesizes import A4, landscape
            from reportlab.lib.styles import getSampleStyleSheet
            from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
        except Exception as exc:  # noqa: BLE001
            raise UserError(_("PDF export requires the reportlab Python package.")) from exc

        buffer = BytesIO()
        document = SimpleDocTemplate(
            buffer,
            pagesize=landscape(A4),
            leftMargin=24,
            rightMargin=24,
            topMargin=24,
            bottomMargin=24,
            title=snapshot.name or "AI Dashboard",
        )
        styles = getSampleStyleSheet()
        story = [
            Paragraph(self._escape_html(snapshot.name or _("AI Dashboard")), styles["Title"]),
            Spacer(1, 8),
            Paragraph(
                self._escape_html(
                    _(
                        "Generated on %(date)s | Company: %(company)s",
                        date=fields.Datetime.to_string(fields.Datetime.now()),
                        company=snapshot.company_id.display_name or "-",
                    )
                ),
                styles["Normal"],
            ),
            Spacer(1, 10),
        ]
        if snapshot.summary_text:
            for paragraph in self._summary_paragraphs(snapshot.summary_text):
                story.append(Paragraph(self._escape_html(paragraph), styles["BodyText"]))
                story.append(Spacer(1, 6))

        rows = [[_("Metric"), _("Value"), _("Model"), _("Code")]]
        for line in snapshot.line_ids.sorted("sequence")[:120]:
            rows.append([
                self._cell_text(line.name),
                self._line_value_text(line),
                self._cell_text(line.model_name),
                self._cell_text(line.metric_code),
            ])
        table = Table(rows, repeatRows=1, colWidths=[260, 160, 180, 170])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("BACKGROUND", (0, 1), (-1, -1), colors.HexColor("#f9fafb")),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.HexColor("#d1d5db")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        story.append(table)
        document.build(story)
        return buffer.getvalue()

    def _render_snapshot_image(self, snapshot):
        try:
            from PIL import Image, ImageDraw, ImageFont
        except Exception as exc:  # noqa: BLE001
            raise UserError(_("Image export requires the Pillow (PIL) Python package.")) from exc

        lines = snapshot.line_ids.sorted("sequence")[:14]
        width = 1600
        row_height = 56
        summary_rows = 3
        summary_height = summary_rows * 28
        chart_height = 280
        base_height = 260 + summary_height + len(lines) * row_height + chart_height
        image = Image.new("RGB", (width, base_height), color=(17, 24, 39))
        draw = ImageDraw.Draw(image)
        font_title = ImageFont.load_default()
        font_text = ImageFont.load_default()
        accent = (16, 185, 129)
        muted = (156, 163, 175)
        white = (243, 244, 246)

        draw.text((40, 32), snapshot.name or "AI Dashboard", fill=white, font=font_title)
        draw.text(
            (40, 60),
            "Generated: %s" % fields.Datetime.to_string(fields.Datetime.now()),
            fill=muted,
            font=font_text,
        )

        summary_lines = self._summary_paragraphs(snapshot.summary_text or _("No summary text available."))[:summary_rows]
        y = 96
        for line in summary_lines:
            draw.text((40, y), line[:180], fill=white, font=font_text)
            y += 28

        table_y = y + 20
        draw.text((40, table_y), "Metric", fill=accent, font=font_text)
        draw.text((760, table_y), "Value", fill=accent, font=font_text)
        draw.text((980, table_y), "Model", fill=accent, font=font_text)

        numeric_values = [line.value_float for line in lines if line.value_float]
        max_numeric = max(numeric_values) if numeric_values else 0.0
        y = table_y + 28
        for line in lines:
            value_text = self._line_value_text(line)
            draw.text((40, y), self._cell_text(line.name)[:78], fill=white, font=font_text)
            draw.text((760, y), value_text[:24], fill=white, font=font_text)
            draw.text((980, y), self._cell_text(line.model_name)[:38], fill=muted, font=font_text)
            if max_numeric > 0 and line.value_float:
                normalized = min(max(line.value_float / max_numeric, 0.0), 1.0)
                bar_w = int(420 * normalized)
                draw.rectangle((1140, y + 8, 1140 + bar_w, y + 20), fill=accent)
            y += row_height

        footer_y = y + 16
        draw.text(
            (40, footer_y),
            "Generated by Odoo AI Assistant | Snapshot #%s" % snapshot.id,
            fill=muted,
            font=font_text,
        )

        output = BytesIO()
        image.save(output, format="PNG")
        return output.getvalue()

    def _create_or_update_attachment(self, snapshot, binary_content, file_name, mimetype, existing_attachment=False):
        existing_attachment = existing_attachment.exists() if existing_attachment else self.env["ir.attachment"]
        values = {
            "name": file_name,
            "type": "binary",
            "datas": base64.b64encode(binary_content),
            "mimetype": mimetype,
            "res_model": "ob.ai.kpi.snapshot",
            "res_id": snapshot.id,
            "company_id": snapshot.company_id.id if snapshot.company_id else False,
        }
        if existing_attachment:
            existing_attachment.sudo().write(values)
            return existing_attachment
        return self.env["ir.attachment"].sudo().create(values)

    def _build_file_name(self, snapshot, extension):
        name = snapshot.name or "ai_dashboard"
        safe_name = re.sub(r"[^a-zA-Z0-9._-]+", "_", name).strip("._")
        if not safe_name:
            safe_name = "ai_dashboard"
        return "%s_%s.%s" % (safe_name, snapshot.id, extension)

    def _download_url(self, attachment):
        return "/web/content/%s?download=true" % attachment.id

    def _line_value_text(self, line):
        if line.value_char:
            return self._cell_text(line.value_char)
        if line.value_float is None:
            return "-"
        return self._cell_text(self._format_float(line.value_float))

    def _cell_text(self, value):
        if value is None:
            return "-"
        text = str(value).strip()
        return text or "-"

    def _summary_paragraphs(self, text):
        paragraphs = [chunk.strip() for chunk in (text or "").splitlines() if chunk.strip()]
        return paragraphs or ["-"]

    def _format_float(self, value):
        if value is None:
            return "-"
        if float(value).is_integer():
            return str(int(value))
        return ("%.2f" % value).rstrip("0").rstrip(".")

    def _escape_html(self, text):
        text = self._cell_text(text)
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
