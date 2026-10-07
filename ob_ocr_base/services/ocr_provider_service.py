import base64
import io
import json
import logging
import re

from odoo import _, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class OCRProviderService(models.AbstractModel):
    _name = "ob.ocr.provider.service"
    _description = "OCR Provider Service"

    DEFAULT_IMAGE_MIMETYPES = {
        "image/png",
        "image/jpeg",
        "image/jpg",
        "image/tiff",
        "image/webp",
    }
    DEFAULT_PDF_MIMETYPES = {"application/pdf"}
    DEFAULT_ALLOWED_MIMETYPES = DEFAULT_IMAGE_MIMETYPES | DEFAULT_PDF_MIMETYPES
    SCRIPT_LANGUAGE_MAP = {
        "Arabic": "ara",
        "Cyrillic": "rus",
        "Greek": "ell",
        "Han": "chi_sim",
        "Hangul": "kor",
        "Hebrew": "heb",
        "Japanese": "jpn",
        "Latin": "eng",
    }

    def extract_text(self, provider, document):
        provider_key = (provider.provider_key or "tesseract").strip().lower()
        if provider_key == "stub":
            return self._extract_text_stub(provider, document)
        if provider_key == "tesseract":
            return self._extract_text_tesseract(provider, document)
        raise UserError(_("Unsupported OCR provider key: %s") % provider.provider_key)

    def extract_json(self, provider, document, schema):
        provider_key = (provider.provider_key or "tesseract").strip().lower()
        if provider_key == "stub":
            return self._extract_json_stub(document, schema)
        if provider_key == "tesseract":
            return {}
        return {}

    def detect_language(self, provider, document):
        provider_key = (provider.provider_key or "tesseract").strip().lower()
        if provider_key == "stub":
            return document.language or self._get_param("default_language") or "eng"
        if provider_key != "tesseract":
            return document.language or self._get_param("default_language") or False
        try:
            pytesseract, _, _ = self._load_tesseract_dependencies()
            images = self._prepare_images(document)
            if not images:
                return self._get_default_tesseract_language(document=document)
            osd = pytesseract.image_to_osd(images[0])
            match = re.search(r"Script:\s*(?P<script>[^\n]+)", osd or "")
            if match:
                detected = self.SCRIPT_LANGUAGE_MAP.get(match.group("script").strip())
                return self._resolve_tesseract_language(detected, document=document)
        except Exception as exc:  # pragma: no cover - best effort only
            _logger.debug("Language detection failed for %s: %s", document.display_name, exc)
        return self._resolve_tesseract_language(
            document.language or self._get_param("default_language") or "eng",
            document=document,
        )

    def supports_handwriting(self, provider):
        return bool(provider.handwriting_supported)

    def supports_file_type(self, provider, mimetype):
        mimetype = (mimetype or "").strip().lower()
        allowed = {
            item.strip().lower()
            for item in (provider.allowed_mimetypes or "").split(",")
            if item.strip()
        }
        if not allowed:
            allowed = set(self.DEFAULT_ALLOWED_MIMETYPES)
            if (provider.provider_key or "").strip().lower() == "stub":
                allowed.add("text/plain")
        return mimetype in allowed

    def _extract_text_stub(self, provider, document):
        file_bytes = self._get_file_bytes(document)
        text = ""
        if document.mimetype == "text/plain":
            text = file_bytes.decode("utf-8", errors="ignore")
        else:
            text = "Stub OCR text for %s" % (document.filename or document.name)
        return {
            "text": text,
            "confidence": 99.0,
            "page_count": 1,
            "detected_language": document.language or self._get_param("default_language") or "eng",
        }

    def _extract_json_stub(self, document, schema):
        raw_text = document.raw_text or ""
        try:
            parsed = json.loads(raw_text)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass
        payload = {}
        if isinstance(schema, dict):
            for key in schema.get("fields", []):
                payload[key] = False
        return payload

    def _extract_text_tesseract(self, provider, document):
        pytesseract, Image, Output = self._load_tesseract_dependencies()
        images = self._prepare_images(document)
        native_pdf_text = False
        if document.mimetype in self.DEFAULT_PDF_MIMETYPES:
            native_pdf_text = self._extract_native_pdf_text(document)
        requested_language = document.language or document.detected_language or self._get_param("default_language") or "eng"
        language = self._resolve_tesseract_language(requested_language, document=document)
        extracted_pages = []
        confidences = []
        layout_pages = []
        attachment_model = self.env["ir.attachment"].sudo()
        preprocess_service = self.env["ob.ocr.image.preprocess.service"]

        for index, image in enumerate(images, start=1):
            processed_image = preprocess_service.preprocess_image(image, document=document)
            data = self._image_to_data_with_fallback(
                pytesseract,
                processed_image,
                language,
                Output,
                document=document,
            )
            words = []
            layout_pages.append(self._build_tesseract_layout_page(data, page_number=index))
            for text_value, confidence in zip(data.get("text", []), data.get("conf", [])):
                text_value = (text_value or "").strip()
                if not text_value:
                    continue
                words.append(text_value)
                try:
                    confidence_float = float(confidence)
                except (TypeError, ValueError):
                    confidence_float = -1.0
                if confidence_float >= 0:
                    confidences.append(confidence_float)
            extracted_pages.append("\n".join([" ".join(words)]))
            if provider.store_processed_images:
                attachment_model.create({
                    "name": "%s-page-%s.png" % (document.name, index),
                    "datas": base64.b64encode(preprocess_service.image_to_png_bytes(processed_image)),
                    "mimetype": "image/png",
                    "res_model": document._name,
                    "res_id": document.id,
                    "ocr_document_id": document.id,
                    "is_ocr_processed": True,
                })

        ocr_text = "\n\n".join(filter(None, extracted_pages)).strip()
        return {
            "text": self._merge_text_sources(native_pdf_text, ocr_text),
            "confidence": sum(confidences) / len(confidences) if confidences else 0.0,
            "page_count": len(images),
            "detected_language": language,
            "layout_json": {"source": "tesseract", "pages": layout_pages},
        }

    def _extract_native_pdf_text(self, document):
        page_texts = self._extract_native_pdf_pages(document)
        return "\n\n".join(filter(None, page_texts)).strip() if page_texts else False

    def _extract_native_pdf_pages(self, document):
        if document.mimetype not in self.DEFAULT_PDF_MIMETYPES:
            return []
        file_bytes = self._get_file_bytes(document)
        reader_classes = []
        try:
            from pypdf import PdfReader

            reader_classes.append(PdfReader)
        except ImportError:
            pass
        try:
            from PyPDF2 import PdfReader

            reader_classes.append(PdfReader)
        except ImportError:
            pass

        for reader_class in reader_classes:
            try:
                reader = reader_class(io.BytesIO(file_bytes))
                pages = [(page.extract_text() or "").strip() for page in reader.pages]
                if any(pages):
                    return pages
            except Exception as exc:  # pragma: no cover - dependency and file specific
                _logger.debug("Native PDF text extraction failed for %s: %s", document.display_name, exc)
        return []

    def _merge_text_sources(self, primary_text, secondary_text):
        primary_text = (primary_text or "").strip()
        secondary_text = (secondary_text or "").strip()
        if not primary_text:
            return secondary_text
        if not secondary_text:
            return primary_text

        normalized_primary = re.sub(r"\s+", " ", primary_text).strip()
        normalized_secondary = re.sub(r"\s+", " ", secondary_text).strip()
        if normalized_primary == normalized_secondary:
            return primary_text
        if normalized_secondary in normalized_primary:
            return primary_text
        if normalized_primary in normalized_secondary:
            return secondary_text
        return "%s\n\n%s" % (primary_text, secondary_text)

    def _image_to_data_with_fallback(self, pytesseract, processed_image, language, output_type, document=None):
        try:
            return pytesseract.image_to_data(processed_image, lang=language, output_type=output_type.DICT)
        except Exception as exc:
            fallback_language = self._get_default_tesseract_language(document=document)
            if fallback_language and fallback_language != language and self._is_tesseract_language_error(exc):
                _logger.warning(
                    "Tesseract language '%s' is unavailable for %s. Falling back to '%s'.",
                    language,
                    document.display_name if document else "OCR document",
                    fallback_language,
                )
                if document and hasattr(document, "_log_event"):
                    document._log_event(
                        "warning",
                        "Requested OCR language is unavailable in Tesseract. Falling back to an installed language.",
                        {"requested_language": language, "fallback_language": fallback_language, "error": str(exc)},
                    )
                return pytesseract.image_to_data(processed_image, lang=fallback_language, output_type=output_type.DICT)
            raise

    def _prepare_images(self, document):
        _, Image, _ = self._load_tesseract_dependencies()
        if document.mimetype in self.DEFAULT_IMAGE_MIMETYPES:
            return [Image.open(io.BytesIO(self._get_file_bytes(document)))]
        if document.mimetype in self.DEFAULT_PDF_MIMETYPES:
            return self._convert_pdf_to_images(document)
        raise UserError(_("Unsupported file type for OCR: %s") % (document.mimetype or _("Unknown")))

    def _convert_pdf_to_images(self, document):
        file_bytes = self._get_file_bytes(document)
        try:
            import pypdfium2 as pdfium

            pdf = pdfium.PdfDocument(file_bytes)
            images = []
            for page_number in range(len(pdf)):
                page = pdf.get_page(page_number)
                bitmap = page.render(scale=2.0)
                images.append(bitmap.to_pil())
                page.close()
            return images
        except ImportError:
            try:
                from pdf2image import convert_from_bytes

                return convert_from_bytes(file_bytes, dpi=300)
            except ImportError as exc:
                raise UserError(_(
                    "PDF OCR requires either pypdfium2 or pdf2image to be installed."
                )) from exc

    def _load_tesseract_dependencies(self):
        try:
            import pytesseract
            from PIL import Image
            from pytesseract import Output
        except ImportError as exc:
            raise UserError(_(
                "The selected OCR provider needs pytesseract and Pillow. "
                "Install the Python packages and the Tesseract system binary."
            )) from exc
        return pytesseract, Image, Output

    def _build_tesseract_layout_page(self, data, page_number=1):
        words = []
        grouped_lines = {}
        total_words = len(data.get("text", []))
        for index in range(total_words):
            text_value = (data["text"][index] or "").strip()
            if not text_value:
                continue
            try:
                confidence = float(data["conf"][index])
            except (TypeError, ValueError):
                confidence = -1.0
            if confidence < 0:
                continue
            word_payload = {
                "text": text_value,
                "left": int(data["left"][index]),
                "top": int(data["top"][index]),
                "width": int(data["width"][index]),
                "height": int(data["height"][index]),
                "confidence": confidence,
                "block_num": int(data["block_num"][index]),
                "par_num": int(data["par_num"][index]),
                "line_num": int(data["line_num"][index]),
                "word_num": int(data["word_num"][index]),
                "page_num": page_number,
            }
            words.append(word_payload)
            line_key = (
                word_payload["block_num"],
                word_payload["par_num"],
                word_payload["line_num"],
            )
            grouped_lines.setdefault(line_key, []).append(word_payload)

        lines = []
        for line_words in grouped_lines.values():
            ordered = sorted(line_words, key=lambda item: (item["left"], item["top"]))
            lines.append({
                "text": " ".join(word["text"] for word in ordered),
                "top": min(word["top"] for word in ordered),
                "left": min(word["left"] for word in ordered),
                "right": max(word["left"] + word["width"] for word in ordered),
                "height": max(word["height"] for word in ordered),
                "page_num": page_number,
                "words": ordered,
            })
        lines.sort(key=lambda item: (item["top"], item["left"]))
        return {
            "page_num": page_number,
            "words": words,
            "lines": lines,
        }

    def _get_available_tesseract_languages(self):
        try:
            pytesseract, _, _ = self._load_tesseract_dependencies()
            languages = pytesseract.get_languages(config="")
            return {lang.strip() for lang in languages if lang and lang.strip()}
        except Exception as exc:  # pragma: no cover - depends on local binary
            _logger.debug("Unable to list installed Tesseract languages: %s", exc)
            return set()

    def _resolve_tesseract_language(self, requested_language, document=None):
        available = self._get_available_tesseract_languages()
        default_language = self._get_default_tesseract_language(document=document)
        candidates = self._expand_language_candidates(requested_language)
        if not available:
            return requested_language or default_language or "eng"

        matched = [candidate for candidate in candidates if candidate in available]
        if matched:
            return "+".join(matched)

        if requested_language and document and hasattr(document, "_log_event"):
            document._log_event(
                "warning",
                "Requested OCR language is not installed in Tesseract. Using a fallback language.",
                {
                    "requested_language": requested_language,
                    "fallback_language": default_language,
                    "available_languages": sorted(available),
                },
            )
        return default_language

    def _get_default_tesseract_language(self, document=None):
        default_language = self._get_param("default_language") or "eng"
        available = self._get_available_tesseract_languages()
        if not available:
            return default_language

        normalized_defaults = self._expand_language_candidates(default_language)
        matched_defaults = [candidate for candidate in normalized_defaults if candidate in available]
        if matched_defaults:
            return "+".join(matched_defaults)
        if "eng" in available:
            return "eng"
        if "osd" in available and len(available) > 1:
            non_osd = sorted(lang for lang in available if lang != "osd")
            if non_osd:
                return non_osd[0]
        return sorted(available)[0]

    def _expand_language_candidates(self, language_value):
        if not language_value:
            return []
        iso_map = {
            "ar": "ara",
            "de": "deu",
            "el": "ell",
            "en": "eng",
            "es": "spa",
            "fr": "fra",
            "he": "heb",
            "ja": "jpn",
            "ko": "kor",
            "ru": "rus",
            "uk": "ukr",
            "zh": "chi_sim",
        }
        candidates = []
        for part in str(language_value).split("+"):
            code = part.strip().lower()
            if not code:
                continue
            candidates.append(code)
            if code in iso_map:
                candidates.append(iso_map[code])
        unique_candidates = []
        for candidate in candidates:
            if candidate not in unique_candidates:
                unique_candidates.append(candidate)
        return unique_candidates

    def _is_tesseract_language_error(self, exc):
        message = str(exc or "").lower()
        return "failed loading language" in message or "could not initialize tesseract" in message

    def _get_file_bytes(self, document):
        if not document.file:
            raise UserError(_("The OCR document does not contain a file to process."))
        return base64.b64decode(document.file)

    def _get_param(self, key, default=False):
        return self.env["ir.config_parameter"].sudo().get_param(
            "ob_ocr_base.%s" % key,
            default=default,
        )
