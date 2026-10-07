import copy
import logging
import re
import unicodedata

from odoo import models

_logger = logging.getLogger(__name__)


class OCRExtractionService(models.AbstractModel):
    _name = "ob.ocr.extraction.service"
    _description = "OCR Extraction Service"

    def extract_document_data(self, document):
        mapping = document._get_effective_mapping()
        schema = mapping.schema_json if mapping else {}
        provider_data = {}
        provider = document._get_effective_provider()
        if provider and mapping and mapping.extraction_mode in ("provider", "ai"):
            try:
                provider_data = provider.extract_json(document, schema)
            except Exception as exc:  # pragma: no cover - optional provider behavior
                _logger.info("Provider JSON extraction failed for %s: %s", document.display_name, exc)
                document._log_event("warning", "Provider JSON extraction fallback used.", {"error": str(exc)})
        regex_data = self.extract_structured_json(
            document.raw_text or "",
            document.document_type,
            schema,
            mapping=mapping,
            document=document,
        )
        merged = self._merge_payloads(regex_data, provider_data)
        merged.setdefault("document_type", document.document_type)
        merged.setdefault("line_items", merged.get("line_items") or [])
        return merged

    def extract_structured_json(self, raw_text, document_type, schema, mapping=None, document=None):
        """Fallback, schema-aware extraction interface for regex/template/AI extensions."""
        payload = {}
        if isinstance(schema, dict):
            payload = self._seed_from_schema(schema)
        if document:
            payload = self._merge_payloads(payload, self._apply_rules(document, mapping=mapping))
        payload = self._merge_payloads(
            payload,
            self._apply_heuristics(
                raw_text,
                document_type,
                schema if isinstance(schema, dict) else {},
                payload,
                document=document,
            ),
        )
        return payload

    def _seed_from_schema(self, schema):
        payload = {}
        for field_name in schema.get("fields", []):
            payload.setdefault(field_name, False)
        if "line_items" in schema.get("collections", []):
            payload.setdefault("line_items", [])
        return payload

    def _apply_rules(self, document, mapping=None):
        payload = {}
        line_items = []
        rules = self._get_rules(document, mapping=mapping)
        raw_text = document.raw_text or ""
        for rule in rules:
            if rule.rule_type == "static":
                if rule.is_line_rule:
                    line_items.append({rule.target_key: rule.default_value})
                else:
                    payload.setdefault(rule.target_key, rule.default_value)
                continue
            if not rule.pattern:
                continue
            regex = re.compile(rule.pattern, self._parse_flags(rule.flags))
            if rule.is_line_rule:
                for match in regex.finditer(raw_text):
                    line_payload = match.groupdict() or {rule.target_key: self._first_group(match)}
                    line_items.append(line_payload)
                continue
            match = regex.search(raw_text)
            if match:
                payload[rule.target_key] = match.groupdict() or self._first_group(match)
                if isinstance(payload[rule.target_key], dict):
                    payload[rule.target_key] = next(iter(payload[rule.target_key].values()), False)
                payload[rule.target_key] = self._sanitize_extracted_value(rule.target_key, payload[rule.target_key])
            elif rule.default_value:
                payload.setdefault(rule.target_key, rule.default_value)
        if line_items:
            payload["line_items"] = line_items
        return payload

    def _apply_heuristics(self, raw_text, document_type, schema, current_payload=None, document=None):
        text = self._normalize_text(raw_text)
        if not text:
            return {}

        payload = {}
        current_payload = current_payload or {}
        fields = set(schema.get("fields", []))
        collections = set(schema.get("collections", []))

        if "currency" in fields and not current_payload.get("currency"):
            currency = self._extract_currency(text)
            if currency:
                payload["currency"] = currency

        if document and document.ocr_layout_json:
            payload = self._merge_payloads(payload, self._extract_layout_summary_values(document, fields))

        for field_name, labels in self._summary_field_labels().items():
            if field_name in fields and not current_payload.get(field_name) and not payload.get(field_name):
                amount = self._extract_summary_amount(text, field_name, labels)
                if amount is not False:
                    payload[field_name] = amount

        handler = getattr(self, f"_extract_{document_type}_heuristics", None)
        if handler:
            payload = self._merge_payloads(payload, handler(text, current_payload, document=document))

        if "line_items" in collections and not current_payload.get("line_items") and not payload.get("line_items"):
            line_items = []
            if document and document.ocr_layout_json:
                line_items = self._extract_layout_line_items(document, document_type)
            if not line_items:
                line_items = self._extract_flat_line_items(text)
            if line_items:
                payload["line_items"] = line_items

        return payload

    def _extract_supplier_quotation_heuristics(self, text, current_payload, document=None):
        dates = self._find_dates(text)
        return {
            "vendor_name": self._usable_party_candidate(current_payload.get("vendor_name"))
            or self._extract_party_after_labels(
                text,
                ["Vendor", "Supplier", "From", "Lieferant", "Anbieter"],
                ["Quotation", "Quote", "Angebot", "USt-IdNr", "VAT", "Customer", "Kunde", "Description", "Artikel"],
            )
            or self._extract_party_before_title(text, ["Quotation", "Quote"]),
            "quotation_number": current_payload.get("quotation_number")
            or self._extract_reference(text, ["Quotation", "Quote"]),
            "quotation_date": current_payload.get("quotation_date") or (dates[0] if len(dates) >= 1 else False),
            "validity_date": current_payload.get("validity_date") or (dates[1] if len(dates) >= 2 else False),
        }

    def _extract_customer_purchase_order_heuristics(self, text, current_payload, document=None):
        dates = self._find_dates(text)
        return {
            "customer_name": self._usable_party_candidate(current_payload.get("customer_name"))
            or self._extract_party_after_labels(
                text,
                ["Customer", "Buyer", "Bill To", "Client", "Kunde"],
                ["Purchase Order", "PO", "Bestellung", "Bestellnummer", "Order Date", "Artikel", "Description"],
            )
            or self._extract_party_before_title(text, ["Purchase Order", "PO"]),
            "po_number": current_payload.get("po_number")
            or self._extract_reference(text, ["Purchase Order", "PO"]),
            "customer_reference": current_payload.get("customer_reference")
            or current_payload.get("po_number")
            or self._extract_reference(text, ["Purchase Order", "PO"]),
            "order_date": current_payload.get("order_date") or (dates[0] if len(dates) >= 1 else False),
            "expected_delivery_date": current_payload.get("expected_delivery_date") or (dates[1] if len(dates) >= 2 else False),
        }

    def _extract_vendor_bill_heuristics(self, text, current_payload, document=None):
        dates = self._find_dates(text)
        generic = {
            "vendor_name": self._usable_party_candidate(current_payload.get("vendor_name"))
            or self._extract_party_after_labels(
                text,
                ["Vendor", "Supplier", "From", "Lieferant", "Aussteller"],
                [
                    "Invoice",
                    "Bill",
                    "Rechnung",
                    "Rechnungsnummer",
                    "USt-IdNr",
                    "VAT",
                    "Tax ID",
                    "Issue Date",
                    "Ausstellungsdatum",
                    "Customer",
                    "Kunde",
                    "Description",
                    "Artikel",
                ],
            )
            or self._extract_leading_company_name(text)
            or self._extract_header_company_from_layout(document)
            or self._extract_party_before_title(text, ["Invoice", "Bill", "Rechnung"]),
            "bill_number": current_payload.get("bill_number")
            or self._extract_reference(text, ["Invoice", "Bill", "Rechnung", "Rechnungsnummer"]),
            "bill_date": current_payload.get("bill_date") or (dates[0] if len(dates) >= 1 else False),
            "due_date": current_payload.get("due_date")
            or self._search_first(text, [
                r"(?:Due Date|Payment Due|Scadenza|F[aä]lligkeit(?:sdatum)?)\s*:?[\s]*([0-9.\-\/]+)",
            ]),
            "vendor_email": current_payload.get("vendor_email") or self._extract_email(text),
            "vendor_phone": current_payload.get("vendor_phone") or self._extract_phone(text),
            "payment_reference": self._usable_reference_candidate(current_payload.get("payment_reference"))
            or self._search_first(text, [
                r"(?:Payment Reference|Reference|Bestellnummer|Bestellung|Order Number)\s*(?:#|:)?\s*([A-Z0-9][A-Z0-9\/\-.]*)",
            ]),
        }
        commercial = self._extract_commercial_invoice_vendor_bill_values(document, current_payload=current_payload)
        payload = self._merge_payloads(generic, commercial)
        payload["bill_number"] = self._choose_preferred_reference(
            generic.get("bill_number"),
            commercial.get("bill_number"),
            current_payload.get("bill_number"),
        ) or False
        payload["bill_date"] = generic.get("bill_date") or commercial.get("bill_date") or current_payload.get("bill_date") or False
        return payload

    def _extract_delivery_slip_heuristics(self, text, current_payload, document=None):
        dates = self._find_dates(text)
        return {
            "partner_name": self._usable_party_candidate(current_payload.get("partner_name"))
            or self._extract_party_after_labels(
                text,
                ["Customer", "Vendor", "Partner", "Deliver To", "Kunde", "Lieferant"],
                ["Delivery Slip", "Delivery Note", "Picking", "Lieferschein", "Tracking", "Artikel", "Description"],
            )
            or self._extract_party_before_title(text, ["Delivery Slip", "Delivery Note", "Picking"]),
            "delivery_slip_number": current_payload.get("delivery_slip_number")
            or self._extract_reference(text, ["Delivery Slip", "Delivery Note", "Picking"]),
            "source_document": current_payload.get("source_document")
            or self._search_first(text, [r"(?:Source Document|Reference|Origin)\s*:?\s*([A-Z0-9\/\-]+)"]),
            "scheduled_date": current_payload.get("scheduled_date") or (dates[0] if len(dates) >= 1 else False),
            "delivery_date": current_payload.get("delivery_date") or (dates[1] if len(dates) >= 2 else False),
            "tracking_number": current_payload.get("tracking_number")
            or self._search_first(text, [r"(?:Tracking|Tracking Number)\s*:?\s*([A-Z0-9\-]+)"]),
        }

    def _extract_commercial_invoice_vendor_bill_values(self, document, current_payload=None):
        if not document or not document.ocr_layout_json:
            return {}
        lines = self._get_grouped_layout_lines(document)
        if not lines:
            return {}
        if not any(
            any(token in self._normalize_layout_text(line.get("text")) for token in ("commercial invoice", "fattura accompagnatoria"))
            for line in lines[:20]
        ):
            return {}

        payload = {}
        issuer_name = self._extract_layout_issuer_name(document)
        if issuer_name:
            payload["vendor_name"] = issuer_name
        issuer_vat = self._extract_layout_label_value(document, ["VAT NUMBER", "P.IVA", "VAT No"], value_pattern=r"([A-Z]{2}[A-Z0-9]{8,})")
        if issuer_vat:
            payload["vendor_vat"] = issuer_vat
        bill_number, bill_date = self._extract_layout_commercial_header_values(document)
        if bill_number:
            payload["bill_number"] = bill_number
        if bill_date:
            payload["bill_date"] = bill_date
        payload = self._merge_payloads(payload, self._extract_layout_commercial_footer_values(document))
        payload = self._merge_payloads(payload, self._extract_text_commercial_invoice_values(document.raw_text or ""))
        return payload

    def _normalize_text(self, raw_text):
        text = (raw_text or "").replace("®", " ").replace("\ufeff", " ")
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    def _find_dates(self, text):
        date_pattern = r"(?<!\d)(?:\d{4}-\d{2}-\d{2}|\d{1,2}[./-]\d{1,2}[./-]\d{2,4})(?!\d)"
        seen = set()
        dates = []
        for date_value in re.findall(date_pattern, text):
            if date_value not in seen:
                seen.add(date_value)
                dates.append(date_value)
        return dates

    def _extract_reference(self, text, labels):
        labels_pattern = "|".join(re.escape(label) for label in labels)
        boundary_ref_label = r"(?:(?<![A-Za-z])(?:N°|Nº|No\.?|Nr\.?|Number|Nummer)(?![A-Za-z])|#)"
        patterns = [
            rf"(?:{labels_pattern})[^\n]{{0,80}}?{boundary_ref_label}\s*:?\s*([A-Z0-9][A-Z0-9\/\-.]*)",
            rf"(?:{labels_pattern})\s*#\s*([A-Z0-9][A-Z0-9\/\-]*)",
            rf"(?:{labels_pattern})\s*(?:No\.?|Number)\s*:?\s*([A-Z0-9][A-Z0-9\/\-]*)",
            rf"(?:{labels_pattern})\s*(?:Nr\.?|Nummer)\s*:?\s*([A-Z0-9][A-Z0-9\/\-.]*)",
            rf"(?:{labels_pattern})[\s-]*(?:Nr\.?|Number|Nummer)\s*:?\s*([A-Z0-9][A-Z0-9\/\-.]*)",
        ]
        return self._search_first(text, patterns)

    def _extract_leading_company_name(self, text):
        lines = [re.sub(r"\s+", " ", line or "").strip(" -,:;") for line in str(text or "").replace("|", "\n").splitlines()]
        for line in [item for item in lines if item][:6]:
            normalized = self._normalize_layout_text(line)
            if not normalized:
                continue
            if any(
                token in normalized for token in (
                    "invoice",
                    "rechnung",
                    "bill number",
                    "bill date",
                    "vendor",
                    "supplier",
                    "lieferant",
                    "payment reference",
                    "telefon",
                    "phone",
                    "@",
                    "mandant",
                    "date",
                    "rechnungsnr",
                    "rechnungsdatum",
                )
            ):
                continue
            if sum(1 for character in line if character.isdigit()) > 4:
                continue
            cleaned = self._clean_party_candidate(line)
            if cleaned:
                return cleaned

        leading_segment = re.split(
            r"\b(?:Mandant|Telefon|Phone|Vendor|Supplier|Lieferant|Invoice|Rechnung|Bill Number|Bill Date|Payment Reference|Date|Rechnungsdatum|Rechnung-Nr\.?)\b",
            str(text or ""),
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        cleaned_segment = self._clean_party_candidate(leading_segment)
        if cleaned_segment:
            return cleaned_segment
        return False

    def _extract_currency(self, text):
        currency = self._search_first(text, [r"(?:Currency)\s*:?\s*([A-Z]{3})"])
        if currency:
            return str(currency).upper()
        currency = self._search_first(text, [r"\b(EUR|USD|GBP)\b"])
        if currency:
            return str(currency).upper()
        for symbol, code in {"$": "USD", "€": "EUR", "£": "GBP"}.items():
            if symbol in text:
                return code
        return False

    def _extract_amount_after_label(self, text, labels, skip_prefix_tokens=None, skip_line_tokens=None):
        for label in labels:
            pattern = (
                rf"(?<![A-Za-z])({re.escape(label)})(?![A-Za-z])"
                rf"(?:\s+[A-Za-z0-9%.\-]+){{0,3}}\s*"
                rf"(?:[:#-]\s*)?"
                rf"(?:[A-Z]{{3}}\s*)?"
                rf"[$€£]?\s*"
                rf"([0-9](?:[0-9.,]*[0-9])?)"
                rf"\s*(?:[$€£]|[A-Z]{{3}})?"
            )
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                label_start = match.start(1)
                prefix = (text[max(0, label_start - 12):label_start] or "").lower().strip()
                matched_line = (match.group(0) or "").lower()
                if skip_prefix_tokens and any(prefix.endswith(token.lower()) for token in skip_prefix_tokens):
                    continue
                if skip_line_tokens and any(token.lower() in matched_line for token in skip_line_tokens):
                    continue
                amount = match.group(2).strip()
                if amount not in (False, None, ""):
                    return amount
        return False

    def _extract_party_after_labels(self, text, labels, stop_labels):
        labels_pattern = "|".join(re.escape(label) for label in labels)
        stop_labels_pattern = "|".join(re.escape(label) for label in stop_labels)
        candidate = self._search_first(text, [
            rf"(?:{labels_pattern})\s*:?\s*(.+?)(?=\s+(?:{stop_labels_pattern})\b|$)",
        ])
        return self._clean_party_candidate(candidate)

    def _extract_party_before_title(self, text, labels):
        labels_pattern = "|".join(re.escape(label) for label in labels)
        match = re.search(rf"\b(?:{labels_pattern})\b", text, flags=re.IGNORECASE)
        if not match:
            return False
        prefix = re.sub(r"\bYour logo\b", " ", text[:match.start()], flags=re.IGNORECASE)
        prefix = re.sub(r"\s+", " ", prefix).strip(" -,:")
        candidates = re.findall(r"[A-Z][A-Za-z0-9&'.-]*(?:\s+[A-Z][A-Za-z0-9&'.-]*){0,5}", prefix)
        if not candidates:
            return False
        candidate = candidates[-1].strip()
        parts = candidate.split()
        if len(parts) > 4:
            candidate = " ".join(parts[-2:])
        return self._clean_party_candidate(candidate)

    def _clean_party_candidate(self, candidate):
        if not candidate:
            return False
        value = unicodedata.normalize("NFKD", str(candidate or ""))
        value = value.encode("ascii", "ignore").decode("ascii")
        value = re.sub(
            r"\b(?:VAT|USt-IdNr|Tax ID|Issue Date|Ausstellungsdatum|Customer|Kunde|Description|Artikel)\b.*$",
            "",
            value,
            flags=re.IGNORECASE,
        )
        value = re.sub(
            r"\b(?:Steuerberater(?:in)?|Rechtsanw[a-z]*|Fachanw[a-z]*|Wirtschaftspr[u-z]*)\b.*$",
            "",
            value,
            flags=re.IGNORECASE,
        )
        value = re.sub(r"\s+", " ", value).strip(" -,:;")
        company_match = re.search(
            r"(.+?\b(?:GmbH(?:\s*&\s*Co\.\s*KG)?|KG|AG|BV|B\.V\.|LLC|LTD|INC\.?|PLC|SARL|SAS|SRL|SA))\b",
            value,
            flags=re.IGNORECASE,
        )
        if company_match:
            value = company_match.group(1)
        else:
            value = re.sub(
                r"\s+[A-ZÄÖÜ][\wÄÖÜäöüß./-]*(?:\s+[A-ZÄÖÜ][\wÄÖÜäöüß./-]*)*\s+\d+[A-Za-z]?$",
                "",
                value,
            )
        return value.strip() or False

    def _sanitize_extracted_value(self, field_name, value):
        if not isinstance(value, str):
            return value
        cleaned = re.sub(r"\s+", " ", value).strip(" -,:;")
        if field_name in ("vendor_name", "customer_name", "partner_name"):
            return self._usable_party_candidate(cleaned)
        if field_name in ("payment_reference", "customer_reference", "source_document"):
            return self._usable_reference_candidate(cleaned)
        return cleaned or False

    def _usable_party_candidate(self, value):
        candidate = self._trim_after_stop_markers(value, self._party_stop_markers())
        candidate = self._clean_party_candidate(candidate)
        if not candidate:
            return False
        normalized = self._normalize_layout_text(candidate)
        if self._is_summary_like_line(normalized):
            return False
        if any(
            token in normalized
            for token in (
                "invoice number",
                "invoice date",
                "payment reference",
                "description",
                "beschreibung",
                "unit price",
                "einzelpreis",
                "rechnungsdatum",
                "subtotal",
                "amount due",
            )
        ):
            return False
        return candidate

    def _usable_reference_candidate(self, value):
        candidate = self._trim_after_stop_markers(value, self._reference_stop_markers())
        if not candidate:
            return False
        candidate = re.sub(r"\s+", " ", candidate).strip(" -,:;")
        if not candidate:
            return False
        if " " in candidate:
            token = self._search_first(candidate, [r"([A-Z0-9][A-Z0-9\/\-.]*)"])
            if token:
                return token
        return candidate

    def _trim_after_stop_markers(self, value, stop_markers):
        if not value:
            return False
        cleaned = re.sub(r"\s+", " ", str(value)).strip()
        if not cleaned:
            return False
        pattern = r"(?i)\b(?:%s)\b.*$" % "|".join(re.escape(marker) for marker in stop_markers)
        return re.sub(pattern, "", cleaned).strip(" -,:;") or False

    def _party_stop_markers(self):
        return [
            "Invoice Number",
            "Invoice Date",
            "Bill Number",
            "Bill Date",
            "Quotation Number",
            "Quotation Date",
            "Purchase Order",
            "Order Date",
            "Payment Reference",
            "Code",
            "Description",
            "Beschreibung",
            "UOM",
            "Qty",
            "Menge",
            "Unit Price",
            "Einzelpreis",
            "Subtotal",
            "Net Total",
            "Amount Due",
            "Total",
            "Nettobetrag",
            "Gesamtbetrag",
            "MwSt",
        ]

    def _reference_stop_markers(self):
        return [
            "Code",
            "Description",
            "Beschreibung",
            "UOM",
            "Qty",
            "Menge",
            "Unit Price",
            "Einzelpreis",
            "Subtotal",
            "Net Total",
            "Amount Due",
            "Total",
            "Nettobetrag",
            "Gesamtbetrag",
            "MwSt",
            "Tax",
            "Please reference",
            "when paying",
        ]

    def _summary_field_labels(self):
        return {
            "untaxed_amount": [
                "Untaxed Amount",
                "Subtotal",
                "Net Total",
                "Net Amount",
                "Nettobetrag",
                "Nettosumme",
                "Zwischensumme",
            ],
            "tax_amount": [
                "Tax",
                "Taxes",
                "VAT",
                "MwSt.",
                "MwSt",
                "USt.",
                "USt",
                "Steuer",
            ],
            "total_amount": [
                "Amount Due",
                "Grand Total",
                "Gesamtbetrag",
                "Bruttobetrag",
                "Bezahlt",
                "zu zahlender Betrag",
                "Zahlbetrag",
                "Total",
                "Gesamt",
            ],
        }

    def _extract_summary_amount(self, text, field_name, labels):
        skip_prefix_tokens = ()
        skip_line_tokens = ()
        if field_name == "total_amount":
            skip_prefix_tokens = ("net", "sub")
            skip_line_tokens = ("net total", "subtotal", "untaxed amount", "nettobetrag")
        elif field_name == "untaxed_amount":
            skip_line_tokens = ("amount due", "grand total", "gesamtbetrag", "zahlbetrag")
        elif field_name == "tax_amount":
            skip_line_tokens = (
                "description",
                "beschreibung",
                "qty",
                "menge",
                "unit price",
                "einzelpreis",
                "uom",
                "vat number",
                "vat no",
                "p.iva",
                "customer code",
            )
        return self._extract_amount_after_label(
            text,
            labels,
            skip_prefix_tokens=skip_prefix_tokens,
            skip_line_tokens=skip_line_tokens,
        )

    def _extract_email(self, text):
        return self._search_first(text, [r"([A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,})"])

    def _extract_phone(self, text):
        return self._search_first(text, [
            r"(?:Phone|Telefon|Tel\.?)\s*:?\s*([+()0-9][0-9\s().\/-]{5,})",
        ])

    def _extract_flat_line_items(self, text):
        section = self._extract_line_items_section(text)
        if not section:
            return []

        row_patterns = [
            re.compile(
                r"(?P<product_name>.+?)\s+"
                r"(?P<quantity>[0-9](?:[0-9.,]*[0-9])?)\s+"
                r"(?P<uom>[A-Za-z][A-Za-z0-9./ -]{0,20}?)\s+"
                r"(?P<unit_price>[0-9](?:[0-9.,]*[0-9])?)\s+"
                r"(?P<taxes>(?:\d+(?:[.,]\d+)?%|[A-Za-z]+(?:\s+\d+(?:[.,]\d+)?%)?))\s+"
                r"(?:[A-Z]{3}\s*)?(?:[$€£]\s*)?(?P<amount>[0-9](?:[0-9.,]*[0-9])?)\s*(?:[$€£]|EUR|USD|GBP)?"
            ),
            re.compile(
                r"(?P<product_name>.+?)"
                r"(?:\s*-\s*SKU:\s*(?P<product_code>[A-Z0-9-]+))?"
                r"\s+(?P<quantity>[0-9](?:[0-9.,]*[0-9])?)\s+"
                r"(?P<unit_price>[0-9](?:[0-9.,]*[0-9])?)\s+"
                r"(?P<taxes>\d+(?:[.,]\d+)?%)\s+"
                r"(?:[A-Z]{3}\s*)?(?:[$€£]\s*)?(?P<amount>[0-9](?:[0-9.,]*[0-9])?)\s*(?:[$€£]|EUR|USD|GBP)?"
            ),
        ]
        line_items = []
        for row_pattern in row_patterns:
            for match in row_pattern.finditer(section):
                line_payload = {
                    "product_name": match.group("product_name").strip(),
                    "name": match.group("product_name").strip(),
                    "quantity": self._to_float(match.group("quantity")),
                    "unit_price": self._to_float(match.group("unit_price")),
                    "taxes": match.group("taxes").strip(),
                    "amount": self._normalize_line_amount(
                        self._to_float(match.group("quantity")),
                        self._to_float(match.group("unit_price")),
                        self._to_float(match.group("amount")),
                        taxes=match.group("taxes").strip(),
                    ),
                }
                if match.groupdict().get("product_code"):
                    line_payload["product_code"] = match.group("product_code").strip()
                if match.groupdict().get("uom"):
                    line_payload["uom"] = match.group("uom").strip()
                    line_payload["uom_name"] = match.group("uom").strip()
                line_items.append(line_payload)
            if line_items:
                break
        return line_items

    def _extract_text_commercial_invoice_values(self, raw_text):
        text = str(raw_text or "")
        normalized = self._normalize_layout_text(text)
        if "commercial invoice" not in normalized and "fattura accompagnatoria" not in normalized:
            return {}

        payload = {}
        vendor_name = self._search_first(text, [r"\(([^()\n]+(?:Srl|GmbH|LLC|Ltd|Inc|AG|KG|BV))\)"])
        if vendor_name:
            payload["vendor_name"] = self._clean_party_candidate(vendor_name)

        vendor_vat = self._search_first(text, [r"VAT NUMBER\s*:\s*([A-Z]{2}[A-Z0-9]+)"])
        if vendor_vat:
            payload["vendor_vat"] = vendor_vat

        bill_number = self._search_first(text, [r"N[°º]\s*([A-Z0-9\/\-.]+)\s*DATA\\DATE"])
        if bill_number:
            payload["bill_number"] = bill_number

        bill_date = self._search_first(text, [r"DATA\\DATE\s*([0-9]{1,2}[./-][0-9]{1,2}[./-][0-9]{2,4})"])
        if bill_date:
            payload["bill_date"] = bill_date

        untaxed_amount = self._search_first(
            text,
            [
                r"TOTALE NETTO\s*/\s*NET AMOUNT\s*([0-9][0-9.,]*)",
                r"TOTALE MERCE\s*/\s*TOTAL AMOUNT\s*([0-9][0-9.,]*)",
            ],
        )
        if untaxed_amount:
            payload["untaxed_amount"] = untaxed_amount

        footer_match = re.search(
            r"TOTALE FATTURA\s*/\s*TOTAL INVOICE.*?(?:\n.*?){0,3}?([0-9][0-9.,]*)\s+EUR\s+([0-9][0-9.,]*)",
            text,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if footer_match:
            payload["tax_amount"] = footer_match.group(1)
            payload["total_amount"] = footer_match.group(2)
        elif untaxed_amount:
            payload["tax_amount"] = "0,00"
            payload["total_amount"] = untaxed_amount

        line_items = self._extract_text_commercial_invoice_line_items(text)
        if line_items:
            payload["line_items"] = line_items
        return payload

    def _extract_text_commercial_invoice_line_items(self, raw_text):
        lines = [re.sub(r"\s+", " ", line or "").strip() for line in str(raw_text or "").splitlines()]
        lines = [line for line in lines if line]
        header_index = False
        for index, line in enumerate(lines):
            normalized = self._normalize_layout_text(line)
            if (
                "code" in normalized
                and "description" in normalized
                and "qty" in normalized
                and "unit price" in normalized
            ):
                header_index = index
                break
        if header_index is False:
            return []

        items = []
        current_item = False
        footer_markers = (
            "total amount",
            "net amount",
            "total invoice",
            "gross weight",
            "delivery terms",
            "package",
            "colli",
            "v.a.t.",
            "vat exemption",
            "discount",
        )
        quantity_pattern = re.compile(
            r"^(?P<prefix>.*?)(?P<quantity>\d+[.,]\d+)\s+EUR\s+(?P<unit_price>\d+[.,]\d+)\s+EUR\s+(?P<amount>\d+[.,]\d+)\s+(?P<vat>[A-Z0-9.,%-]+)\s*$",
            flags=re.IGNORECASE,
        )
        for line in lines[header_index + 1:]:
            normalized = self._normalize_layout_text(line)
            if not normalized or "our ref" in normalized or "customer ref" in normalized:
                continue
            if any(marker in normalized for marker in footer_markers):
                if current_item:
                    items.append(current_item)
                break

            line = re.sub(r"([A-Za-z])(\d{1,3},\d{2}\s+EUR)", r"\1 \2", line)
            quantity_match = quantity_pattern.search(line)
            if quantity_match and current_item:
                prefix = (quantity_match.group("prefix") or "").strip(" -")
                if prefix and not prefix.upper().startswith("LOT:"):
                    current_item["name"] = "%s %s" % (current_item["name"], prefix)
                    current_item["product_name"] = current_item["name"]
                current_item["quantity"] = self._to_float(quantity_match.group("quantity"))
                current_item["unit_price"] = self._to_float(quantity_match.group("unit_price"))
                current_item["amount"] = self._normalize_line_amount(
                    current_item["quantity"],
                    current_item["unit_price"],
                    self._to_float(quantity_match.group("amount")),
                    taxes=quantity_match.group("vat"),
                )
                taxes = quantity_match.group("vat").strip()
                current_item["taxes"] = False if taxes in {"0", "0,00", "0.00", "UE0,00"} else taxes
                items.append(current_item)
                current_item = False
                continue

            start_match = re.match(r"^(?P<code>[A-Z0-9-]+(?:\s+[A-Z0-9-]+)?)\s+(?P<description>.+)$", line)
            if start_match:
                if current_item:
                    items.append(current_item)
                current_item = {
                    "product_code": start_match.group("code").strip(),
                    "product_name": start_match.group("description").strip(),
                    "name": start_match.group("description").strip(),
                    "quantity": 0.0,
                    "uom": False,
                    "uom_name": False,
                    "unit_price": 0.0,
                    "discount": 0.0,
                    "amount": 0.0,
                    "taxes": False,
                }
                if " 1 KG" in current_item["name"].upper():
                    current_item["uom"] = "KG"
                    current_item["uom_name"] = "KG"
                continue

            if current_item:
                current_item["name"] = "%s %s" % (current_item["name"], line)
                current_item["product_name"] = current_item["name"]

        finalized = []
        for item in items:
            item["name"] = re.sub(r"\s+", " ", item.get("name") or "").strip(" -")
            item["product_name"] = item["name"]
            if item.get("product_code") and item.get("name") and (
                item.get("quantity") or item.get("unit_price") or item.get("amount")
            ):
                finalized.append(item)
        return finalized

    def _extract_layout_line_items(self, document, document_type):
        layout = document.ocr_layout_json or {}
        pages = layout.get("pages", []) if isinstance(layout, dict) else []
        line_items = []
        for page in pages:
            page_items = self._extract_layout_line_items_from_page(page, document_type=document_type)
            if page_items:
                line_items.extend(page_items)
        return line_items

    def _extract_layout_line_items_from_page(self, page, document_type=None):
        line_items = self._extract_layout_tabular_line_items_from_page(page, document_type=document_type)
        if line_items:
            return line_items
        line_items = self._extract_layout_narrative_line_items_from_page(page, document_type=document_type)
        if line_items:
            return line_items
        return self._extract_layout_stacked_amount_line_items_from_page(page, document_type=document_type)

    def _extract_layout_tabular_line_items_from_page(self, page, document_type=None):
        lines = page.get("lines", []) if isinstance(page, dict) else []
        if not lines:
            return []
        lines = self._group_layout_lines(lines)

        header_index, header_line = self._find_layout_table_header(lines)
        if header_line is False:
            return []
        columns = self._infer_layout_columns(header_line)
        if not columns.get("description"):
            return []

        rows = []
        current_row = False
        for line in lines[header_index + 1:]:
            line_text = (line.get("text") or "").strip()
            if not line_text:
                continue
            normalized_line = self._normalize_layout_text(line_text)
            if self._is_layout_footer_line(normalized_line):
                break
            cells = self._split_layout_line_into_cells(line, columns)
            if self._is_layout_row_start(cells):
                if current_row:
                    finalized = self._finalize_layout_row(current_row)
                    if finalized:
                        rows.append(finalized)
                current_row = cells
                continue
            if current_row and cells.get("description"):
                current_row["description"] = "%s %s" % (current_row.get("description", ""), cells["description"])
            elif current_row and any(cells.get(key) for key in ("code", "uom")):
                current_row["description"] = "%s %s" % (
                    current_row.get("description", ""),
                    " ".join(filter(None, [cells.get("code"), cells.get("description"), cells.get("uom")])),
                )
        if current_row:
            finalized = self._finalize_layout_row(current_row)
            if finalized:
                rows.append(finalized)
        return rows

    def _extract_layout_narrative_line_items_from_page(self, page, document_type=None):
        lines = page.get("lines", []) if isinstance(page, dict) else []
        if not lines:
            return []

        header_index = self._find_layout_narrative_header(lines)
        if header_index is False:
            return []

        rows = []
        current_row = False
        for line in lines[header_index + 1:]:
            line_text = re.sub(r"\s+", " ", (line.get("text") or "")).strip()
            if not line_text:
                continue
            normalized_line = self._normalize_layout_text(line_text)
            if self._is_layout_narrative_header_line(normalized_line) or self._is_layout_narrative_context_line(normalized_line):
                continue
            if self._is_layout_footer_line(normalized_line) or self._is_layout_narrative_total_line(normalized_line):
                if current_row:
                    finalized = self._finalize_layout_narrative_row(current_row)
                    if finalized:
                        rows.append(finalized)
                break

            amount = self._extract_layout_narrative_amount(line_text)
            if amount is not False and current_row and current_row.get("description_parts"):
                current_row["unit_price"] = amount
                current_row["amount"] = amount
                finalized = self._finalize_layout_narrative_row(current_row)
                if finalized:
                    rows.append(finalized)
                current_row = False
                continue

            if not current_row:
                current_row = {
                    "description_parts": [],
                    "meta_parts": [],
                    "quantity": 1.0,
                }
            if self._is_layout_narrative_reference_line(normalized_line):
                current_row["meta_parts"].append(line_text)
            else:
                current_row["description_parts"].append(line_text)

        return rows

    def _extract_layout_stacked_amount_line_items_from_page(self, page, document_type=None):
        lines = page.get("lines", []) if isinstance(page, dict) else []
        if not lines:
            return []
        lines = self._group_layout_lines(lines)

        items = []
        for header_index, amount_index in self._find_layout_stacked_amount_sections(lines):
            section_items = self._build_layout_stacked_amount_section_items(lines, header_index, amount_index)
            if section_items:
                items.extend(section_items)
        return items

    def _find_layout_stacked_amount_sections(self, lines):
        sections = []
        for index, line in enumerate(lines):
            normalized = self._normalize_layout_text(line.get("text"))
            if normalized != "bezeichnung" and not normalized.startswith("bezeichnung "):
                continue
            amount_index = False
            for candidate in range(index + 1, min(len(lines), index + 18)):
                candidate_normalized = self._normalize_layout_text(lines[candidate].get("text"))
                if "betrag" in candidate_normalized and "eur" in candidate_normalized:
                    amount_index = candidate
                    break
                if self._is_layout_footer_line(candidate_normalized):
                    break
            if amount_index is not False:
                sections.append((index, amount_index))
        return sections

    def _build_layout_stacked_amount_section_items(self, lines, header_index, amount_index):
        labels = []
        for line in lines[header_index + 1:amount_index]:
            line_text = re.sub(r"\s+", " ", (line.get("text") or "")).strip()
            normalized = self._normalize_layout_text(line_text)
            if not self._is_layout_stacked_amount_label_line(normalized):
                continue
            if self._is_layout_stacked_summary_label(normalized):
                break
            labels.append(line_text)

        if not labels:
            return []

        amounts = []
        for line in lines[amount_index + 1:]:
            line_text = re.sub(r"\s+", " ", (line.get("text") or "")).strip()
            normalized = self._normalize_layout_text(line_text)
            if not normalized:
                continue
            if "bezeichnung" in normalized or self._is_layout_footer_line(normalized):
                break
            if any(marker in normalized for marker in ("sehr geehrte", "wir wunschen", "empfanger", "seite")):
                break
            amount_token = self._extract_last_amount_token(line_text)
            amount_value = self._safe_to_float(amount_token, default=False)
            if amount_token and amount_value is not False:
                amounts.append((amount_token, amount_value))
                if len(amounts) >= len(labels):
                    break

        if len(amounts) < len(labels):
            return []

        items = []
        for label, (_, amount_value) in zip(labels, amounts):
            clean_label = re.sub(r"\s+", " ", label).strip(" -|")
            if not clean_label:
                continue
            items.append({
                "product_code": False,
                "product_name": clean_label,
                "name": clean_label,
                "quantity": 1.0,
                "uom": False,
                "uom_name": False,
                "unit_price": amount_value,
                "discount": 0.0,
                "amount": amount_value,
                "taxes": False,
            })
        return items

    def _find_layout_table_header(self, lines):
        for index, line in enumerate(lines):
            normalized = self._normalize_layout_text(line.get("text"))
            if not normalized:
                continue
            if not any(token in normalized for token in ("description", "descrizione", "beschreibung")):
                continue
            if not any(token in normalized for token in ("price", "prezzo", "amount", "importo", "einzelpreis", "gesamt")):
                continue
            return index, line
        return False, False

    def _group_layout_lines(self, lines, threshold=10):
        source_lines = [line for line in (lines or []) if line]
        nonzero_tops = {int(line.get("top", 0)) for line in source_lines if int(line.get("top", 0))}
        if len(nonzero_tops) <= 1:
            return source_lines

        sorted_lines = sorted(
            source_lines,
            key=lambda line: (int(line.get("top", 0)), int(line.get("left", 0))),
        )
        grouped = []
        current_group = []
        current_top = False

        for line in sorted_lines:
            top = int(line.get("top", 0))
            if current_group and current_top is not False and abs(top - current_top) > threshold:
                grouped.append(self._merge_layout_line_group(current_group))
                current_group = []
            if not current_group:
                current_top = top
            current_group.append(line)

        if current_group:
            grouped.append(self._merge_layout_line_group(current_group))
        return grouped

    def _merge_layout_line_group(self, lines):
        words = []
        for line in sorted(lines, key=lambda item: int(item.get("left", 0))):
            line_words = line.get("words", []) or []
            if line_words:
                words.extend(line_words)
            else:
                words.append({
                    "text": line.get("text") or "",
                    "left": int(line.get("left", 0)),
                    "top": int(line.get("top", 0)),
                })
        words = sorted(words, key=lambda word: int(word.get("left", 0)))
        return {
            "text": " ".join((word.get("text") or "").strip() for word in words if (word.get("text") or "").strip()).strip(),
            "top": min(int(line.get("top", 0)) for line in lines),
            "left": min(int(line.get("left", 0)) for line in lines),
            "words": words,
        }

    def _get_grouped_layout_lines(self, document, page_index=0):
        layout = document.ocr_layout_json or {}
        pages = layout.get("pages", []) if isinstance(layout, dict) else []
        if len(pages) <= page_index:
            return []
        page = pages[page_index] or {}
        return self._group_layout_lines(page.get("lines", []) if isinstance(page, dict) else [])

    def _get_layout_page_width(self, lines):
        max_right = 0
        for line in lines or []:
            words = line.get("words", []) or []
            if words:
                for word in words:
                    left = int(word.get("left", 0))
                    width = int(word.get("width", 0) or max(len(str(word.get("text") or "")) * 8, 10))
                    max_right = max(max_right, left + width)
            else:
                left = int(line.get("left", 0))
                max_right = max(max_right, left + max(len(str(line.get("text") or "")) * 8, 10))
        return max_right or 1

    def _find_layout_narrative_header(self, lines):
        for index in range(len(lines)):
            window = " ".join(
                self._normalize_layout_text(lines[position].get("text"))
                for position in range(index, min(index + 4, len(lines)))
            ).strip()
            if not window:
                continue
            if (
                any(token in window for token in ("gebuhrentext", "gebiihrentext", "description"))
                and any(token in window for token in ("einheiten", "quantity", "qty"))
                and any(token in window for token in ("satz", "price", "amount", "euro"))
            ):
                header_end = min(index + 3, len(lines) - 1)
                while header_end + 1 < len(lines):
                    next_line = self._normalize_layout_text(lines[header_end + 1].get("text"))
                    if not self._is_layout_narrative_header_line(next_line):
                        break
                    header_end += 1
                return header_end
        return False

    def _infer_layout_columns(self, header_line):
        columns = {}
        header_words = header_line.get("words", []) or []
        for word in header_words:
            normalized = self._normalize_layout_text(word.get("text"))
            if not normalized:
                continue
            left = int(word.get("left", 0))
            if "codice" in normalized or normalized == "code":
                columns.setdefault("code", left)
            elif "descrizione" in normalized or "description" in normalized or "beschreibung" in normalized:
                columns.setdefault("description", left)
            elif normalized in ("um", "uom", "uoom") or "uom" in normalized:
                columns.setdefault("uom", left)
            elif any(token in normalized for token in ("qty", "qta", "quantity", "quantita", "menge")):
                columns.setdefault("quantity", left)
            elif any(token in normalized for token in ("price", "prezzo", "unit", "einzelpreis")):
                columns.setdefault("unit_price", left)
            elif "disc" in normalized:
                columns.setdefault("discount", left)
            elif "importo" in normalized or "amount" in normalized or "gesamt" in normalized:
                columns.setdefault("amount", left)
            elif normalized in ("vat", "iva", "mwst") or normalized.endswith("vat"):
                columns.setdefault("vat", left)

        if columns.get("uom") and columns.get("unit_price") and not columns.get("quantity"):
            columns["quantity"] = int((columns["uom"] + columns["unit_price"]) / 2)
        if columns.get("unit_price") and columns.get("vat") and not columns.get("amount"):
            columns["amount"] = int((columns["unit_price"] + columns["vat"]) / 2)
        if columns.get("description") and not columns.get("code"):
            columns["code"] = max(columns["description"] - 180, 0)
        return columns

    def _split_layout_line_into_cells(self, line, columns):
        words = sorted(line.get("words", []) or [], key=lambda word: int(word.get("left", 0)))
        if not words:
            return {}

        uom_x = columns.get("uom") or 0
        quantity_x = columns.get("quantity") or 0
        unit_price_x = columns.get("unit_price") or 0
        amount_x = columns.get("amount") or 0
        vat_x = columns.get("vat") or 999999

        text_words = [word for word in words if int(word.get("left", 0)) < max(uom_x - 20, 0) or not uom_x]
        code_words, description_words = self._split_code_and_description_words(text_words)

        uom_words = [
            word for word in words
            if uom_x and int(word.get("left", 0)) >= max(uom_x - 25, 0) and int(word.get("left", 0)) < max(quantity_x - 10, uom_x + 40)
        ]
        quantity_words = [
            word for word in words
            if quantity_x and self._is_numeric_word(word.get("text")) and int(word.get("left", 0)) >= max(quantity_x - 45, 0) and int(word.get("left", 0)) < max(unit_price_x - 25, quantity_x + 70)
        ]
        price_words = [
            word for word in words
            if unit_price_x and self._is_numeric_word(word.get("text")) and int(word.get("left", 0)) >= max(unit_price_x - 35, 0) and int(word.get("left", 0)) < max(amount_x - 10, unit_price_x + 140)
        ]
        vat_words = [
            word for word in words
            if self._is_vat_word(word.get("text")) and int(word.get("left", 0)) >= max(vat_x - 30, 0) and int(word.get("left", 0)) < vat_x + 120
        ]
        amount_words = [
            word for word in words
            if amount_x and self._is_numeric_word(word.get("text")) and int(word.get("left", 0)) >= max(amount_x - 30, 0) and int(word.get("left", 0)) < max(vat_x - 20, amount_x + 160)
        ]

        cells = {
            "code": " ".join(word.get("text") for word in code_words).strip(),
            "description": " ".join(word.get("text") for word in description_words).strip(),
            "uom": " ".join(word.get("text") for word in uom_words if not self._is_numeric_word(word.get("text"))).strip(),
            "quantity": " ".join(self._clean_numeric_token(word.get("text")) for word in quantity_words).strip(),
            "unit_price": " ".join(self._clean_numeric_token(word.get("text")) for word in price_words).strip(),
            "amount": " ".join(self._clean_numeric_token(word.get("text")) for word in amount_words).strip(),
            "vat": " ".join((word.get("text") or "").strip("{}[]() ") for word in vat_words).strip(),
        }
        return cells

    def _split_code_and_description_words(self, words):
        if not words:
            return [], []
        if len(words) == 1:
            return words, []
        split_index = False
        for index in range(1, len(words)):
            previous = words[index - 1]
            current = words[index]
            gap = int(current.get("left", 0)) - (
                int(previous.get("left", 0)) + max(len(str(previous.get("text") or "")) * 7, 15)
            )
            if gap >= 45:
                split_index = index
                break
        if split_index is False:
            return words[:2], words[2:]
        return words[:split_index], words[split_index:]

    def _is_layout_row_start(self, cells):
        amount_like = any(cells.get(key) for key in ("quantity", "unit_price", "amount"))
        text_like = cells.get("description") or cells.get("code")
        if not amount_like or not text_like:
            return False
        combined_text = self._normalize_layout_text(
            " ".join(filter(None, [cells.get("code"), cells.get("description"), cells.get("uom")]))
        )
        normalized_description = self._normalize_layout_text(cells.get("description"))
        if self._is_summary_like_line(combined_text) or self._is_summary_like_line(normalized_description):
            return False
        if any(
            token in combined_text or token in normalized_description
            for token in ("package", "pagkage", "colli", "golli", "gross weight", "discount", "invoice", "total amount", "totalamount", "delivery note", "please reference")
        ):
            return False
        return True

    def _finalize_layout_row(self, row):
        description = self._clean_layout_row_description(row)
        product_code = re.sub(r"\s+", " ", (row.get("code") or "")).strip(" -|")
        if not description and not product_code:
            return False
        payload = {
            "product_code": product_code or False,
            "product_name": description or product_code,
            "name": description or product_code,
            "quantity": self._safe_to_float(row.get("quantity"), default=1.0),
            "uom": (row.get("uom") or "").strip() or False,
            "uom_name": (row.get("uom") or "").strip() or False,
            "unit_price": self._safe_to_float(row.get("unit_price")),
            "discount": self._safe_to_float(row.get("discount")),
            "amount": self._safe_to_float(row.get("amount")),
            "taxes": (row.get("vat") or "").strip() or False,
        }
        payload["amount"] = self._normalize_line_amount(
            payload["quantity"],
            payload["unit_price"],
            payload["amount"],
            taxes=payload["taxes"],
        )
        if not payload["uom"] and description and re.search(r"\b(?:kg|pcs|pc|pz|unit|units)\b", description, flags=re.IGNORECASE):
            payload["uom"] = re.search(r"\b(?:kg|pcs|pc|pz|unit|units)\b", description, flags=re.IGNORECASE).group(0)
            payload["uom_name"] = payload["uom"]
        return payload

    def _clean_layout_row_description(self, row):
        description = re.sub(r"\s+", " ", (row.get("description") or "")).strip(" -|")
        if not description:
            return description
        uom = (row.get("uom") or "").strip()
        quantity = (row.get("quantity") or "").strip()
        unit_price = (row.get("unit_price") or "").strip()
        vat = (row.get("vat") or "").strip()
        trailing_tokens = [token for token in [uom, quantity, unit_price, vat] if token]
        if trailing_tokens:
            trailing_pattern = r"(?:\s+%s)+$" % "|".join(re.escape(token) for token in trailing_tokens)
            description = re.sub(trailing_pattern, "", description, flags=re.IGNORECASE).strip(" -|")
        description = re.sub(
            r"\b(?:pcs|pc|pz|units?|kg)\b\s+[0-9][0-9.,]*\s+[0-9][0-9.,]*(?:\s+\d+(?:[.,]\d+)?%)?$",
            "",
            description,
            flags=re.IGNORECASE,
        ).strip(" -|")
        return description

    def _normalize_layout_text(self, value):
        text = (value or "").strip().lower()
        text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
        text = text.replace("\\", " ").replace("/", " ").replace("|", " ").replace("_", " ")
        text = re.sub(r"[^a-z0-9%.,+\- ]+", " ", text)
        return re.sub(r"\s+", " ", text).strip()

    def _is_numeric_word(self, value):
        normalized = (value or "").strip()
        normalized = self._clean_numeric_token(normalized)
        return bool(re.fullmatch(r"[0-9]+(?:[.,][0-9]+)?", normalized))

    def _is_vat_word(self, value):
        normalized = (value or "").strip("{}[]() ")
        return bool(re.fullmatch(r"[0-9]+(?:[.,][0-9]+)?%", normalized))

    def _clean_numeric_token(self, value):
        normalized = (value or "").strip()
        normalized = normalized.replace("EUR", "").replace("USD", "").replace("GBP", "").replace("€", "")
        normalized = normalized.replace("_", "").replace("|", "")
        return normalized.strip("{}[]() ")

    def _is_layout_footer_line(self, normalized_line):
        return any(
            marker in normalized_line for marker in (
                "totale fattura",
                "total invoice",
                "total amount",
                "totalamount",
                "totale netto",
                "net amount",
                "net total",
                "subtotal",
                "amount due",
                "nettobetrag",
                "gesamtbetrag",
                "mwst",
                "colli",
                "golli",
                "package",
                "pagkage",
                "peso",
                "gross weight",
                "ship via",
                "delivery note",
                "please reference",
                "delivery terms",
                "imponibile",
                "summe gebiihren",
                "summe gebuhren",
                "summe auslagen",
                "zu zahlender betrag",
            )
        )

    def _extract_layout_summary_values(self, document, fields):
        summary = {}
        field_map = self._summary_field_labels()
        field_map["untaxed_amount"] = field_map["untaxed_amount"] + [
            "Summe Gebühren",
            "Summe Gebuhren",
            "Summe Gebiihren",
        ]
        for field_name, labels in field_map.items():
            if field_name not in fields:
                continue
            amount = self._extract_layout_amount_after_labels(document, labels, field_name=field_name)
            if amount is not False:
                summary[field_name] = amount
        return summary

    def _extract_layout_issuer_name(self, document):
        lines = self._get_grouped_layout_lines(document)
        if not lines:
            return False
        page_width = self._get_layout_page_width(lines)
        top_limit = max(int(max(int(line.get("top", 0)) for line in lines) * 0.28), 420)
        candidates = []
        for line in lines:
            top = int(line.get("top", 0))
            left = int(line.get("left", 0))
            if top > top_limit or left > int(page_width * 0.48):
                continue
            text = re.sub(r"\s+", " ", (line.get("text") or "")).strip(" -,:;()")
            normalized = self._normalize_layout_text(text)
            if not normalized:
                continue
            if any(
                token in normalized
                for token in (
                    "operational headquarters",
                    "registered office",
                    "vat number",
                    "email",
                    "website",
                    "telefon",
                    "phone",
                    "ship to",
                    "spettabile",
                    "commercial invoice",
                    "fattura",
                    "customer code",
                    "date",
                    "invoice",
                    "payment",
                )
            ):
                continue
            cleaned = self._clean_party_candidate(text.strip("()"))
            if not cleaned:
                continue
            score = 0
            if any(suffix in normalized for suffix in ("srl", "gmbh", "llc", "ltd", "inc", "ag", "kg", "bv")):
                score += 4
            if "(" in (line.get("text") or "") and ")" in (line.get("text") or ""):
                score += 1
            if top < 180:
                score += 2
            if left < int(page_width * 0.18):
                score += 1
            score -= len(cleaned) / 200.0
            candidates.append((score, top, cleaned))
        if not candidates:
            return False
        candidates.sort(key=lambda item: (-item[0], item[1]))
        return candidates[0][2]

    def _extract_layout_label_value(self, document, labels, value_pattern):
        lines = self._get_grouped_layout_lines(document)
        if not lines:
            return False
        normalized_labels = [self._normalize_layout_text(label) for label in labels]
        for line in lines:
            line_text = re.sub(r"\s+", " ", (line.get("text") or "")).strip()
            normalized_line = self._normalize_layout_text(line_text)
            if not normalized_line:
                continue
            if not any(self._contains_normalized_label(normalized_line, label) for label in normalized_labels):
                continue
            value = self._search_first(line_text, [value_pattern])
            if value:
                return value
        return False

    def _extract_layout_commercial_header_values(self, document):
        lines = self._get_grouped_layout_lines(document)
        bill_number = False
        bill_date = False
        for index, line in enumerate(lines):
            line_text = re.sub(r"\s+", " ", (line.get("text") or "")).strip()
            normalized_line = self._normalize_layout_text(line_text)
            if "data date" not in normalized_line and "data\\date" not in (line.get("text") or "").lower():
                continue
            header_window = " ".join(
                re.sub(r"\s+", " ", (lines[position].get("text") or "")).strip()
                for position in range(max(0, index - 1), min(len(lines), index + 2))
            )
            bill_number = bill_number or self._search_first(
                header_window,
                [
                    r"(?:N°|N|No\.?)\s*([A-Z0-9\/\-.]*\d[A-Z0-9\/\-.]*)",
                    r"\b([A-Z]{0,4}\d{2,}[A-Z0-9\/\-.]*)\b",
                ],
            )
            if bill_number and str(bill_number).upper() in {"DATA", "DATE"}:
                bill_number = False
            bill_date = bill_date or self._search_first(
                header_window,
                [
                    r"(\d{1,2}/\d{1,2}/\d{2,4})",
                    r"(\d{1,2}\.\d{1,2}\.\d{2,4})",
                ],
            )
            if bill_number and bill_date:
                break
        return bill_number, bill_date

    def _extract_layout_commercial_footer_values(self, document):
        lines = self._get_grouped_layout_lines(document)
        if not lines:
            return {}
        page_width = self._get_layout_page_width(lines)
        payload = {}
        untaxed = self._extract_rightmost_amount_for_labels(lines, ["Net Amount", "Totale Netto", "Total Amount", "Totale Merce"])
        if untaxed:
            payload["untaxed_amount"] = untaxed
        total = self._extract_amount_near_footer_label(lines, page_width, ["Total Invoice", "Totale Fattura"], x_min_ratio=0.82, x_max_ratio=1.01)
        if total:
            payload["total_amount"] = total
        tax = self._extract_amount_near_footer_label(lines, page_width, ["Total Invoice", "Totale Fattura"], x_min_ratio=0.52, x_max_ratio=0.78)
        if tax:
            payload["tax_amount"] = tax
        elif total and untaxed and self._safe_to_float(total, default=False) is not False and self._safe_to_float(untaxed, default=False) is not False:
            difference = round(self._safe_to_float(total) - self._safe_to_float(untaxed), 2)
            payload["tax_amount"] = ("%.2f" % difference).replace(".", ",") if "," in total else "%.2f" % difference
        return payload

    def _extract_rightmost_amount_for_labels(self, lines, labels):
        normalized_labels = [self._normalize_layout_text(label) for label in labels]
        for line in lines:
            line_text = re.sub(r"\s+", " ", (line.get("text") or "")).strip()
            normalized_line = self._normalize_layout_text(line_text)
            if not normalized_line:
                continue
            if not any(self._contains_normalized_label(normalized_line, label) for label in normalized_labels):
                continue
            amount = self._extract_last_amount_token(line_text)
            if amount is not False:
                return amount
        return False

    def _extract_amount_near_footer_label(self, lines, page_width, labels, x_min_ratio, x_max_ratio, window=4):
        normalized_labels = [self._normalize_layout_text(label) for label in labels]
        for index, line in enumerate(lines):
            normalized_line = self._normalize_layout_text(line.get("text"))
            if not normalized_line:
                continue
            if not any(self._contains_normalized_label(normalized_line, label) for label in normalized_labels):
                continue
            amount_words = []
            for candidate_line in lines[index:index + window]:
                for word in candidate_line.get("words", []) or []:
                    token = (word.get("text") or "").strip("{}[]() ")
                    if not self._is_numeric_word(token):
                        continue
                    cleaned_token = self._clean_numeric_token(token)
                    left = int(word.get("left", 0))
                    if left < int(page_width * x_min_ratio) or left > int(page_width * x_max_ratio):
                        continue
                    amount_words.append((left, int(candidate_line.get("top", 0)), cleaned_token))
            if amount_words:
                amount_words.sort(key=lambda item: (item[1], item[0]))
                return amount_words[-1][2]
        return False

    def _extract_layout_amount_after_labels(self, document, labels, field_name=None):
        normalized_labels = [self._normalize_layout_text(label) for label in labels]
        layout = document.ocr_layout_json or {}
        for page in layout.get("pages", []):
            lines = page.get("lines", []) if isinstance(page, dict) else []
            lines = self._group_layout_lines(lines)
            for index, line in enumerate(lines):
                line_text = re.sub(r"\s+", " ", (line.get("text") or "")).strip()
                normalized_line = self._normalize_layout_text(line_text)
                if not normalized_line:
                    continue
                if field_name == "tax_amount":
                    if "leistungsdatum" in normalized_line:
                        continue
                    if any(token in normalized_line for token in ("steuer nr", "steuernr", "ustid", "tax id", "vat id")):
                        continue
                    if any(token in normalized_line for token in ("summe", "auslagen", "gebuhren", "gebiihren")):
                        continue
                    if any(token in normalized_line for token in ("description", "beschreibung", "qty", "menge", "unit price", "einzelpreis", "uom")):
                        continue
                if field_name == "total_amount" and any(token in normalized_line for token in ("net total", "subtotal", "untaxed amount", "nettobetrag")):
                    continue
                if field_name == "untaxed_amount" and any(token in normalized_line for token in ("amount due", "grand total", "gesamtbetrag", "zahlbetrag")):
                    continue
                if not any(self._contains_normalized_label(normalized_line, label) for label in normalized_labels):
                    continue
                for next_index in range(index + 1, min(index + 3, len(lines))):
                    candidate_text = re.sub(r"\s+", " ", (lines[next_index].get("text") or "")).strip()
                    if self._looks_like_amount_line(candidate_text):
                        amount = self._extract_last_amount_token(candidate_text)
                        if amount is not False:
                            return amount
                amount = self._extract_last_amount_token(line_text)
                if amount is not False:
                    return amount
        return False

    def _extract_header_company_from_layout(self, document):
        if not document or not document.ocr_layout_json:
            return False
        pages = (document.ocr_layout_json or {}).get("pages", [])
        if not pages:
            return False
        for line in (pages[0].get("lines", []) or [])[:15]:
            text = re.sub(r"\s+", " ", (line.get("text") or "")).strip(" -,:;")
            text = re.sub(r"\s+[0-9][A-Za-z&.]{0,3}$", "", text).strip(" -,:;")
            normalized = self._normalize_layout_text(text)
            if not normalized:
                continue
            if any(token in normalized for token in ("rechnung", "invoice", "telefon", "@", "frau", "herr")):
                continue
            if sum(1 for char in text if char.isdigit()) > 2:
                continue
            if "&" in text or "partner" in normalized or "mbb" in normalized or "gmbh" in normalized:
                return self._clean_party_candidate(text)
        return False

    def _contains_normalized_label(self, normalized_text, normalized_label):
        text_compact = (normalized_text or "").replace(".", "")
        label_compact = (normalized_label or "").replace(".", "")
        if label_compact == "mwst":
            return bool(re.search(r"(?<![a-z])mws+t(?![a-z])", text_compact))
        return bool(
            re.search(
                r"(?<![a-z])%s(?![a-z])" % re.escape(normalized_label),
                normalized_text or "",
            )
        )

    def _is_layout_narrative_header_line(self, normalized_line):
        return normalized_line == "euro" or any(
            token in normalized_line for token in (
                "gegenstandswert",
                "gebuhrentext",
                "gebiihrentext",
                "einheiten",
                "satz",
                "tab",
                "euro euro",
            )
        )

    def _is_layout_narrative_context_line(self, normalized_line):
        return normalized_line.startswith("auftrag") or "leistungsdatum" in normalized_line

    def _is_layout_narrative_reference_line(self, normalized_line):
        return any(
            token in normalized_line for token in (
                "stbvv",
                " abs. ",
                " nr. ",
                "eur a",
                "§",
            )
        ) or bool(re.search(r"\b[0-9]{1,3}(?:\.[0-9]{3})*,[0-9]{2}\b", normalized_line))

    def _is_layout_narrative_total_line(self, normalized_line):
        return any(
            token in normalized_line for token in (
                "summe",
                "ust",
                "mwst",
                "zu zahlender betrag",
                "zahlbetrag",
            )
        )

    def _is_layout_stacked_amount_label_line(self, normalized_line):
        if not normalized_line:
            return False
        if any(character.isdigit() for character in normalized_line):
            return False
        if any(
            token in normalized_line for token in (
                "betrag",
                "eur",
                "%",
                "ust",
                "mwst",
                "netto",
                "brutto",
                "gesamtsumme",
                "summe",
                "bezeichnung",
                "telefon",
                "telefax",
                "fax",
                "datum",
                "seite",
                "kundennr",
                "kundennr.",
            )
        ):
            return False
        return sum(1 for character in normalized_line if character.isalpha()) >= 4

    def _is_layout_stacked_summary_label(self, normalized_line):
        return any(
            token in normalized_line for token in (
                "leasingrate",
                "erstmonat",
                "endmonat",
                "mehr km",
                "minder km",
                "gesamtsumme",
                "summe",
                "betrag",
                "zu zahlender betrag",
            )
        )

    def _is_summary_like_line(self, normalized_line):
        return any(
            token in (normalized_line or "")
            for token in (
                "subtotal",
                "net total",
                "untaxed amount",
                "tax",
                "mwst",
                "ust",
                "amount due",
                "grand total",
                "gesamtbetrag",
                "bruttobetrag",
                "zahlbetrag",
                "zu zahlender betrag",
                "nettobetrag",
            )
        )

    def _extract_layout_narrative_amount(self, line_text):
        match = re.search(
            r"(?:^|\s)(?:[0-9]+(?:[.,][0-9]+)?/\d+)\s+([0-9][0-9.,]*)\s*$",
            line_text,
            flags=re.IGNORECASE,
        )
        if match:
            return self._safe_to_float(match.group(1), default=False)
        return False

    def _finalize_layout_narrative_row(self, row):
        description_parts = row.get("description_parts") or []
        meta_parts = row.get("meta_parts") or []
        description = re.sub(r"\s+", " ", " ".join(description_parts + meta_parts)).strip(" -|")
        amount = row.get("amount")
        if not description or amount in (False, None, ""):
            return False
        payload = {
            "product_code": False,
            "product_name": description,
            "name": description,
            "quantity": row.get("quantity") or 1.0,
            "uom": False,
            "uom_name": False,
            "unit_price": amount,
            "discount": 0.0,
            "amount": amount,
            "taxes": False,
        }
        return payload

    def _looks_like_amount_line(self, text):
        normalized = re.sub(r"\s+", " ", (text or "")).strip()
        if not normalized:
            return False
        if re.fullmatch(r"[0-9][0-9.,]*", normalized):
            return True
        if re.fullmatch(r"(?:[A-Z]{3}\s+)?[0-9][0-9.,]*", normalized):
            return True
        return False

    def _extract_last_amount_token(self, text):
        matches = re.findall(r"[0-9](?:[0-9.]*[0-9])?(?:,[0-9]{2})?", text or "")
        for candidate in reversed(matches):
            if candidate.count(".") > 1 or "," in candidate:
                return candidate
        return matches[-1] if matches else False

    def _extract_line_items_section(self, text):
        headers = [
            "Description Quantity Unit Price Taxes Amount",
            "Description Qty Unit Price Taxes Amount",
            "Product Description Quantity Unit Price Taxes Amount",
            "Product Quantity Unit Price Taxes Amount",
            "Artikel Beschreibung Menge Einzelpreis MwSt. Gesamt",
            "Artikel Beschreibung Menge Einzelpreis MwSt Gesamt",
            "Artikel Menge Einzelpreis MwSt. Gesamt",
        ]
        start = -1
        matched_header = False
        lowered = text.lower()
        for header in headers:
            position = lowered.find(header.lower())
            if position >= 0:
                start = position + len(header)
                matched_header = True
                break
        if not matched_header:
            return False

        section = text[start:].strip()
        end_markers = [
            "Untaxed Amount",
            "Subtotal",
            "Grand Total",
            "Total",
            "Gesamt",
            "Bezahlt",
            "Page ",
        ]
        end_positions = [
            section.lower().find(marker.lower())
            for marker in end_markers
            if section.lower().find(marker.lower()) >= 0
        ]
        if end_positions:
            section = section[:min(end_positions)].strip()
        return section or False

    def _search_first(self, text, patterns):
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            if match.groupdict():
                value = next(iter(match.groupdict().values()), False)
            elif match.groups():
                value = match.group(1)
            else:
                value = match.group(0)
            if isinstance(value, str):
                value = value.strip(" \t\r\n:,-")
            if value not in (False, None, ""):
                return value
        return False

    def _to_float(self, value):
        if value in (False, None, ""):
            return 0.0
        cleaned = str(value).strip().replace(" ", "")
        if cleaned.count(",") == 1 and cleaned.count(".") == 0:
            cleaned = cleaned.replace(",", ".")
        elif cleaned.count(",") > 0 and cleaned.count(".") > 0:
            cleaned = cleaned.replace(".", "").replace(",", ".")
        return float(cleaned)

    def _safe_to_float(self, value, default=0.0):
        if value in (False, None, ""):
            return default
        try:
            return self._to_float(value)
        except Exception:
            return default

    def _get_rules(self, document, mapping=None):
        domain = [
            ("active", "=", True),
            ("document_type_id", "=", document.document_type_id.id),
            "|",
            ("company_id", "=", False),
            ("company_id", "=", document.company_id.id),
        ]
        rules = self.env["ob.ocr.extraction.rule"].search(domain, order="sequence, id")
        return rules.filtered(
            lambda rule: (not rule.mapping_id or rule.mapping_id == mapping)
            and (not rule.provider_id or rule.provider_id == document.ocr_provider_id)
        )

    def _merge_payloads(self, *payloads):
        merged = {}
        for payload in payloads:
            if not isinstance(payload, dict):
                continue
            for key, value in payload.items():
                if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
                    merged[key] = self._merge_payloads(merged[key], value)
                elif key in merged and isinstance(merged[key], list) and isinstance(value, list):
                    merged[key] = copy.deepcopy(merged[key]) + copy.deepcopy(value)
                elif value not in (False, None, "", [], {}):
                    merged[key] = copy.deepcopy(value)
                else:
                    merged.setdefault(key, copy.deepcopy(value))
        return merged

    def _choose_preferred_reference(self, *candidates):
        best_value = False
        best_score = float("-inf")
        for candidate in candidates:
            candidate = self._usable_reference_candidate(candidate)
            score = self._score_reference_candidate(candidate)
            if score > best_score:
                best_score = score
                best_value = candidate
        return best_value

    def _score_reference_candidate(self, value):
        candidate = (value or "").strip()
        if not candidate:
            return float("-inf")
        normalized = candidate.upper()
        if normalized in {"DATA", "DATE", "INVOICE", "RECHNUNG", "BILL"}:
            return -100.0
        score = 0.0
        if re.search(r"[A-Z]", candidate) and re.search(r"\d", candidate):
            score += 6.0
        elif re.search(r"\d", candidate):
            score += 2.0
        if re.search(r"[/-]", candidate):
            score += 1.0
        if re.fullmatch(r"\d+[.,]\d+", candidate):
            score -= 6.0
        if re.fullmatch(r"\d{6,}", candidate):
            score -= 4.0
        if len(candidate) < 3:
            score -= 2.0
        if len(candidate) > 24:
            score -= 3.0
        return score

    def _normalize_line_amount(self, quantity, unit_price, amount, taxes=False):
        expected_amount = round((quantity or 0.0) * (unit_price or 0.0), 2) if quantity and unit_price else 0.0
        if not amount:
            return expected_amount
        if not expected_amount:
            return amount
        if abs(amount - expected_amount) < 0.01:
            return amount
        ratio = amount / expected_amount if expected_amount else 0.0
        tax_text = str(taxes or "").strip()
        if ratio > 1.4 or ratio < 0.6:
            if not tax_text or not tax_text.endswith("%"):
                return expected_amount
        return amount

    def _parse_flags(self, flags):
        value = 0
        flags = flags or ""
        for flag in [item.strip().upper() for item in flags.split(",") if item.strip()]:
            value |= getattr(re, flag, 0)
        return value

    def _first_group(self, match):
        if match.groups():
            return match.group(1)
        return match.group(0)
