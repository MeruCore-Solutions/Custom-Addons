from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from io import BytesIO


@dataclass
class BenchmarkLine:
    description: str
    quantity: Decimal
    unit_price: Decimal
    amount: Decimal
    code: str | None = None
    tax_label: str | None = "19%"
    uom: str | None = "PCS"


@dataclass
class BenchmarkExpectation:
    vendor_name: str
    bill_number: str
    bill_date: str
    untaxed_amount: str
    tax_amount: str
    total_amount: str
    line_count: int
    line_amounts: list[float]
    first_line_hint: str


@dataclass
class BenchmarkCase:
    case_id: str
    family: str
    filename: str
    mimetype: str
    content: bytes
    expected: BenchmarkExpectation


@dataclass
class BenchmarkSeed:
    style: str
    variant: int
    vendor_name: str
    bill_number: str
    bill_date: str
    currency_symbol: str
    locale: str
    tax_rate: Decimal
    lines: list[BenchmarkLine]
    payment_reference: str | None = None


class OCRBenchmarkFactory:
    """Build a reproducible OCR benchmark corpus without storing binary files in git."""

    SINGLE_PAGE_FORMATS = (
        ("native_pdf", "application/pdf", "pdf"),
        ("scanned_pdf", "application/pdf", "scan.pdf"),
        ("png_image", "image/png", "png"),
        ("jpeg_image", "image/jpeg", "jpg"),
    )

    def build_cases(self) -> list[BenchmarkCase]:
        cases: list[BenchmarkCase] = []
        for seed in self._build_single_page_seeds():
            pdf_bytes = self._render_seed_pdf(seed)
            expectation = self._build_expectation(seed)
            base_name = "%s_%02d" % (seed.style, seed.variant + 1)
            png_bytes = self._convert_pdf_to_image_bytes(pdf_bytes, "png")
            for format_key, mimetype, extension in self.SINGLE_PAGE_FORMATS:
                if format_key == "native_pdf":
                    content = pdf_bytes
                elif format_key == "scanned_pdf":
                    content = self._convert_image_bytes_to_pdf(png_bytes)
                else:
                    content = png_bytes if extension == "png" else self._convert_pdf_to_image_bytes(pdf_bytes, extension)
                cases.append(BenchmarkCase(
                    case_id="%s_%s" % (base_name, format_key),
                    family=seed.style,
                    filename="%s.%s" % (base_name, extension),
                    mimetype=mimetype,
                    content=content,
                    expected=expectation,
                ))
        return cases

    def _build_single_page_seeds(self) -> list[BenchmarkSeed]:
        seeds: list[BenchmarkSeed] = []
        for variant in range(5):
            seeds.extend([
                self._build_en_table_seed(variant),
                self._build_de_table_seed(variant),
                self._build_service_seed(variant),
                self._build_compact_seed(variant),
                self._build_dense_seed(variant),
            ])
        return seeds

    def _build_en_table_seed(self, variant: int) -> BenchmarkSeed:
        vendor = [
            "Atlas Supplies Ltd",
            "Blue Harbor Components LLC",
            "Northwind Industrial Ltd",
            "Sunrise Office Goods LLC",
            "Pioneer Tech Parts Ltd",
        ][variant]
        base = Decimal("42.50") + Decimal(variant * 7)
        lines = [
            self._line("Blue Widget", Decimal("2.00"), base, code="A-%02d" % (variant + 11)),
            self._line("Steel Fastener Pack", Decimal("3.00"), base + Decimal("9.25"), code="B-%02d" % (variant + 21)),
        ]
        return BenchmarkSeed(
            style="en_table",
            variant=variant,
            vendor_name=vendor,
            bill_number="INV-2026-%04d" % (1100 + variant),
            bill_date="2026-05-%02d" % (10 + variant),
            currency_symbol="$",
            locale="en",
            tax_rate=Decimal("0.19"),
            lines=lines,
            payment_reference="PO-%04d" % (5100 + variant),
        )

    def _build_de_table_seed(self, variant: int) -> BenchmarkSeed:
        vendor = [
            "Nordhandel GmbH",
            "Rhein Elektronik GmbH",
            "Kaiser Industriebedarf GmbH",
            "Hansa Buero Systeme GmbH",
            "Bergwerk Technik GmbH",
        ][variant]
        base = Decimal("58.40") + Decimal(variant * 8)
        lines = [
            self._line("Montage Set", Decimal("2.00"), base, code="DE-%02d" % (variant + 31), uom="PCS"),
            self._line("Werkzeughalter", Decimal("1.00"), base + Decimal("15.10"), code="DE-%02d" % (variant + 41), uom="PCS"),
            self._line("Kabelsatz", Decimal("4.00"), Decimal("12.80") + Decimal(variant), code="DE-%02d" % (variant + 51), uom="PCS"),
        ]
        return BenchmarkSeed(
            style="de_table",
            variant=variant,
            vendor_name=vendor,
            bill_number="RG-2026-%04d" % (2100 + variant),
            bill_date="%02d.05.2026" % (11 + variant),
            currency_symbol="EUR",
            locale="de",
            tax_rate=Decimal("0.19"),
            lines=lines,
            payment_reference="BEST-%04d" % (6100 + variant),
        )

    def _build_service_seed(self, variant: int) -> BenchmarkSeed:
        vendor = [
            "Lander, Kohlmann & Partner",
            "Steuerkanzlei Adler Partner",
            "Fiscalis Beratung Partner",
            "Recht Steuer Partner mbB",
            "Weber Audit Partner",
        ][variant]
        fee = Decimal("1260.75") + Decimal(variant * 35)
        lines = [
            self._line("Einkommensteuererklaerung ohne Ermittlung der einzelnen Einkuenfte", Decimal("1.00"), fee, uom=None, tax_label=None),
            self._line("Ermittlung des Ueberschusses der Einnahmen ueber die Werbungskosten", Decimal("1.00"), fee, uom=None, tax_label=None),
        ]
        return BenchmarkSeed(
            style="de_service",
            variant=variant,
            vendor_name=vendor,
            bill_number="2026/%04d" % (3200 + variant),
            bill_date="%02d.05.2026" % (12 + variant),
            currency_symbol="EUR",
            locale="de",
            tax_rate=Decimal("0.19"),
            lines=lines,
        )

    def _build_compact_seed(self, variant: int) -> BenchmarkSeed:
        vendor = [
            "Pixel Parts LLC",
            "Harbor Devices Ltd",
            "Metro Office Supply LLC",
            "Clearview Systems Ltd",
            "Orbit Components LLC",
        ][variant]
        lines = [
            self._line("Compact Sensor", Decimal("1.00"), Decimal("89.00") + Decimal(variant * 3), code="CS-%02d" % (variant + 61)),
            self._line("Signal Board", Decimal("2.00"), Decimal("54.50") + Decimal(variant * 2), code="SB-%02d" % (variant + 71)),
            self._line("Support Kit", Decimal("1.00"), Decimal("24.20") + Decimal(variant), code="SK-%02d" % (variant + 81)),
        ]
        return BenchmarkSeed(
            style="compact_en",
            variant=variant,
            vendor_name=vendor,
            bill_number="BILL-%04d" % (4100 + variant),
            bill_date="%02d/%02d/2026" % (13 + variant, 5),
            currency_symbol="GBP" if variant % 2 else "$",
            locale="en",
            tax_rate=Decimal("0.07") if variant % 2 else Decimal("0.15"),
            lines=lines,
            payment_reference="REF-%04d" % (7100 + variant),
        )

    def _build_dense_seed(self, variant: int) -> BenchmarkSeed:
        vendor = [
            "Summit Distribution Ltd",
            "Red Maple Trade LLC",
            "Canyon Logistics Ltd",
            "Green Valley Supplies LLC",
            "Silver Peak Components Ltd",
        ][variant]
        lines = [
            self._line("Router Rack", Decimal("1.00"), Decimal("145.00") + Decimal(variant * 2), code="RR-%02d" % (variant + 91)),
            self._line("Patch Cable Bundle", Decimal("5.00"), Decimal("8.80") + Decimal(variant), code="PC-%02d" % (variant + 101)),
            self._line("Label Strip", Decimal("3.00"), Decimal("6.40") + Decimal(variant), code="LS-%02d" % (variant + 111)),
            self._line("Power Adapter", Decimal("2.00"), Decimal("18.25") + Decimal(variant), code="PA-%02d" % (variant + 121)),
        ]
        return BenchmarkSeed(
            style="dense_en",
            variant=variant,
            vendor_name=vendor,
            bill_number="DN-%04d" % (5100 + variant),
            bill_date="2026/05/%02d" % (14 + variant),
            currency_symbol="EUR" if variant % 2 else "$",
            locale="en",
            tax_rate=Decimal("0.19"),
            lines=lines,
            payment_reference="SHIP-%04d" % (8100 + variant),
        )

    def _line(self, description: str, quantity: Decimal, unit_price: Decimal, code: str | None = None, uom: str | None = "PCS", tax_label: str | None = "19%") -> BenchmarkLine:
        amount = (quantity * unit_price).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return BenchmarkLine(
            description=description,
            quantity=quantity,
            unit_price=unit_price.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP),
            amount=amount,
            code=code,
            tax_label=tax_label,
            uom=uom,
        )

    def _build_expectation(self, seed: BenchmarkSeed) -> BenchmarkExpectation:
        untaxed = sum((line.amount for line in seed.lines), start=Decimal("0.00")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        tax = (untaxed * seed.tax_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        total = (untaxed + tax).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        return BenchmarkExpectation(
            vendor_name=seed.vendor_name,
            bill_number=seed.bill_number,
            bill_date=seed.bill_date,
            untaxed_amount=self._format_amount(untaxed, seed.locale),
            tax_amount=self._format_amount(tax, seed.locale),
            total_amount=self._format_amount(total, seed.locale),
            line_count=len(seed.lines),
            line_amounts=[float(line.amount) for line in seed.lines],
            first_line_hint=seed.lines[0].description.split()[0],
        )

    def _render_seed_pdf(self, seed: BenchmarkSeed) -> bytes:
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.pdfgen import canvas
        except Exception as exc:  # pragma: no cover - benchmark dependency
            raise RuntimeError("reportlab is required for OCR benchmark generation") from exc

        buffer = BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4
        if seed.style == "de_service":
            self._draw_service_layout(pdf, width, height, seed)
        else:
            self._draw_table_layout(pdf, width, height, seed)
        pdf.showPage()
        pdf.save()
        return buffer.getvalue()

    def _draw_table_layout(self, pdf, width: float, height: float, seed: BenchmarkSeed) -> None:
        vendor_label = "Vendor" if seed.locale == "en" else "Lieferant"
        number_label = "Invoice Number" if seed.locale == "en" else "Rechnung-Nr."
        date_label = "Invoice Date" if seed.locale == "en" else "Rechnungsdatum"
        total_label = "Total" if seed.locale == "en" else "Gesamtbetrag"
        untaxed_label = "Subtotal" if seed.locale == "en" else "Nettobetrag"
        tax_label = "Tax" if seed.locale == "en" else "MwSt."

        if seed.style == "compact_en":
            number_label = "Bill Number"
            date_label = "Bill Date"
            untaxed_label = "Net Total"
            total_label = "Amount Due"
        elif seed.style == "dense_en":
            vendor_label = "From"
            date_label = "Date"

        pdf.setTitle(seed.bill_number)
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(40, height - 50, "INVOICE")
        pdf.setFont("Helvetica-Bold", 12)
        pdf.drawString(40, height - 82, "%s: %s" % (vendor_label, seed.vendor_name))
        pdf.setFont("Helvetica", 11)
        pdf.drawString(40, height - 104, "%s: %s" % (number_label, seed.bill_number))
        pdf.drawString(40, height - 122, "%s: %s" % (date_label, seed.bill_date))
        if seed.payment_reference:
            pdf.drawString(40, height - 140, "Payment Reference: %s" % seed.payment_reference)

        if seed.style == "de_table":
            header = ("Code", "Beschreibung", "UOM", "Menge", "Einzelpreis", "MwSt.", "Gesamt")
        else:
            header = ("Code", "Description", "UOM", "Qty", "Unit Price", "VAT", "Amount")
        start_y = height - 190
        self._draw_table_header(pdf, start_y, header)
        current_y = start_y - 22
        font_name = "Courier" if seed.style in ("compact_en", "dense_en") else "Helvetica"
        font_size = 10 if seed.style == "compact_en" else 10.5
        pdf.setFont(font_name, font_size)
        for line in seed.lines:
            self._draw_table_row(pdf, current_y, seed, line)
            current_y -= 18

        pdf.setFont("Helvetica-Oblique", 9)
        if seed.style == "dense_en":
            pdf.drawString(40, current_y - 6, "Delivery note attached. Please reference %s when paying." % (seed.payment_reference or seed.bill_number))
            current_y -= 20

        pdf.setFont("Helvetica-Bold", 11)
        summary_x = width - 210
        amount_x = width - 48
        untaxed = self._build_expectation(seed).untaxed_amount
        tax = self._build_expectation(seed).tax_amount
        total = self._build_expectation(seed).total_amount
        rows = [
            (untaxed_label, untaxed),
            (tax_label, tax),
            (total_label, total),
        ]
        for label, value in rows:
            pdf.drawString(summary_x, current_y - 8, label)
            pdf.drawRightString(amount_x, current_y - 8, self._render_currency(seed, value))
            current_y -= 18

    def _draw_table_header(self, pdf, y: float, header: tuple[str, ...]) -> None:
        pdf.setFont("Helvetica-Bold", 10.5)
        positions = (40, 115, 345, 395, 455, 535, 595)
        for position, label in zip(positions, header):
            pdf.drawString(position, y, label)
        pdf.line(40, y - 4, 610, y - 4)

    def _draw_table_row(self, pdf, y: float, seed: BenchmarkSeed, line: BenchmarkLine) -> None:
        values = (
            line.code or "",
            line.description,
            line.uom or "",
            self._format_quantity(line.quantity, seed.locale),
            self._format_amount(line.unit_price, seed.locale),
            line.tax_label or "0%",
            self._format_amount(line.amount, seed.locale),
        )
        positions = (40, 115, 345, 395, 455, 535, 595)
        for index, (position, value) in enumerate(zip(positions, values)):
            if index >= 3:
                pdf.drawString(position, y, value)
            else:
                pdf.drawString(position, y, value)

    def _draw_service_layout(self, pdf, width: float, height: float, seed: BenchmarkSeed) -> None:
        expectation = self._build_expectation(seed)
        pdf.setTitle(seed.bill_number)
        pdf.setFont("Helvetica-Bold", 15)
        pdf.drawString(40, height - 48, seed.vendor_name)
        pdf.setFont("Helvetica", 11)
        pdf.drawString(40, height - 70, "Mandant 53150")
        pdf.drawString(40, height - 88, "Telefon: 07243 / 7645-417")
        pdf.drawString(40, height - 106, "ku@benchmark.local")
        pdf.drawString(350, height - 70, seed.bill_date)
        pdf.drawString(350, height - 88, "Rechnung-Nr. %s" % seed.bill_number)
        pdf.drawString(40, height - 136, "Fuer die in Ihrem Auftrag ausgefuehrten Leistungen erlauben wir uns zu berechnen:")
        pdf.drawString(40, height - 164, "Gegenstandswert/")
        pdf.drawString(238, height - 164, "Satz/")
        pdf.drawString(40, height - 182, "Gebiihrentext nach StBVV Einheiten Tab")
        pdf.drawString(238, height - 182, "Euro Euro")

        current_y = height - 214
        refs = (
            "§ 24 Abs. 1 Nr. 1 StBVV 1.148.573,00 EUR A",
            "§ 27 Abs. 1 StBVV 1.149.573,00 EUR A",
        )
        rates = (
            "2,50/10 %s" % self._format_amount(seed.lines[0].amount, "de"),
            "5,00/20 %s" % self._format_amount(seed.lines[1].amount, "de"),
        )
        descriptions = (
            (
                "Auftrag: Einkommensteuer 2026 - Nr. %04d (USt-Leistungsdatum bis 04.2026)" % (9100 + seed.variant),
                seed.lines[0].description,
                "Steuerpflichtiger",
            ),
            (
                "Ermittlung des Ueberschusses der Einnahmen ueber die",
                "Werbungskosten bei Einkuenften aus Kapitalvermoegen",
                "Steuerpflichtiger",
            ),
        )
        pdf.setFont("Helvetica", 10.5)
        for description_block, ref_line, rate_line in zip(descriptions, refs, rates):
            for chunk in description_block:
                pdf.drawString(40, current_y, chunk)
                current_y -= 15
            pdf.drawString(40, current_y, ref_line)
            current_y -= 15
            pdf.drawString(238, current_y, rate_line)
            current_y -= 22

        summary_rows = (
            ("Summe Gebiihren (USt 19,00%)", expectation.untaxed_amount),
            ("USt 19,00%", expectation.tax_amount),
            ("zu zahlender Betrag", expectation.total_amount),
        )
        pdf.setFont("Helvetica-Bold", 11)
        for label, value in summary_rows:
            pdf.drawString(40, current_y, label)
            current_y -= 15
            pdf.drawString(238, current_y, value)
            current_y -= 18
        pdf.setFont("Helvetica", 9)
        pdf.drawString(40, current_y - 6, "Wir bitten um Ueberweisung unter Angabe der Rechnungsnummer.")

    def _render_currency(self, seed: BenchmarkSeed, amount_text: str) -> str:
        if seed.currency_symbol in ("EUR", "GBP"):
            prefix = seed.currency_symbol
        else:
            prefix = seed.currency_symbol
        return "%s %s" % (prefix, amount_text)

    def _convert_pdf_to_image_bytes(self, pdf_bytes: bytes, extension: str) -> bytes:
        try:
            import pypdfium2 as pdfium
        except Exception as exc:  # pragma: no cover - benchmark dependency
            raise RuntimeError("pypdfium2 is required for OCR benchmark image generation") from exc

        pdf = pdfium.PdfDocument(pdf_bytes)
        page = pdf.get_page(0)
        bitmap = page.render(scale=2.6)
        image = bitmap.to_pil()
        page.close()

        output = BytesIO()
        save_format = {"png": "PNG", "jpg": "JPEG"}[extension]
        save_kwargs = {}
        if save_format == "JPEG":
            image = image.convert("RGB")
            save_kwargs["quality"] = 96
        image.save(output, format=save_format, **save_kwargs)
        return output.getvalue()

    def _convert_image_bytes_to_pdf(self, image_bytes: bytes) -> bytes:
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib.utils import ImageReader
            from reportlab.pdfgen import canvas
        except Exception as exc:  # pragma: no cover - benchmark dependency
            raise RuntimeError("reportlab is required for scanned PDF benchmark generation") from exc

        buffer = BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A4)
        width, height = A4
        image_reader = ImageReader(BytesIO(image_bytes))
        pdf.drawImage(image_reader, 0, 0, width=width, height=height, preserveAspectRatio=True, anchor="c")
        pdf.showPage()
        pdf.save()
        return buffer.getvalue()

    def _format_quantity(self, quantity: Decimal, locale: str) -> str:
        if locale == "de":
            return ("%0.2f" % float(quantity)).replace(".", ",")
        return "%0.2f" % float(quantity)

    def _format_amount(self, amount: Decimal, locale: str) -> str:
        value = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if locale == "de":
            rendered = f"{float(value):,.2f}"
            return rendered.replace(",", "_").replace(".", ",").replace("_", ".")
        return f"{float(value):.2f}"
