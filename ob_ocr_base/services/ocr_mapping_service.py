from odoo import models


class OCRMappingService(models.AbstractModel):
    _name = "ob.ocr.mapping.service"
    _description = "OCR Mapping Service"

    def prepare_target_payload(self, document, extracted_json=None):
        mapping = document._get_effective_mapping()
        data = extracted_json if extracted_json is not None else (document.extracted_json or {})
        values = {}
        if not mapping:
            return values
        for mapping_field in mapping.field_ids.sorted("sequence"):
            source_value = self._get_source_value(data, mapping_field.source_key)
            if source_value in (False, None, "") and mapping_field.regex_pattern and document.raw_text:
                source_value = self._extract_from_raw_text(document.raw_text, mapping_field.regex_pattern)
            if source_value in (False, None, ""):
                source_value = mapping_field.default_value or False
            source_value = self._convert_value(source_value, mapping_field.transform_type)
            if not mapping_field.target_field or source_value in (False, None, ""):
                continue
            values[mapping_field.target_field] = source_value
        return values

    def _get_source_value(self, data, source_key):
        if not source_key:
            return False
        value = data
        for part in source_key.split("."):
            if not isinstance(value, dict):
                return False
            value = value.get(part)
        return value

    def _extract_from_raw_text(self, raw_text, pattern):
        import re

        match = re.search(pattern, raw_text or "", re.IGNORECASE | re.MULTILINE)
        if not match:
            return False
        if match.groups():
            return match.group(1)
        return match.group(0)

    def _convert_value(self, value, transform_type):
        if value in (False, None, ""):
            return value
        transform_type = transform_type or "none"
        if transform_type == "strip":
            return str(value).strip()
        if transform_type == "upper":
            return str(value).upper()
        if transform_type == "lower":
            return str(value).lower()
        if transform_type == "title":
            return str(value).title()
        if transform_type == "float":
            return self._to_float(value)
        if transform_type == "int":
            return int(self._to_float(value))
        if transform_type == "bool":
            return str(value).strip().lower() in ("1", "true", "yes", "y")
        if transform_type == "date":
            try:
                from dateutil import parser as date_parser

                return date_parser.parse(str(value), dayfirst=True).date()
            except Exception:
                return value
        return value

    def _to_float(self, value):
        cleaned = str(value).strip().replace(" ", "")
        if cleaned.count(",") == 1 and cleaned.count(".") == 0:
            cleaned = cleaned.replace(",", ".")
        elif cleaned.count(",") > 0 and cleaned.count(".") > 0:
            cleaned = cleaned.replace(".", "").replace(",", ".")
        return float(cleaned)
