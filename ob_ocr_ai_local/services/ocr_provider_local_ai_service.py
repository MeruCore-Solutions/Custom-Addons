import base64
import logging
import re

from odoo import _
from odoo.exceptions import UserError

from odoo.addons.ob_ocr_base.services.ocr_provider_service import OCRProviderService

_logger = logging.getLogger(__name__)


class OCRProviderLocalAIService(OCRProviderService):
    _name = "ob.ocr.provider.local.ai.service"
    _inherit = "ob.ocr.provider.service"
    _description = "OCR Provider Local AI Service"

    PADDLEOCR_LANGUAGE_MAP = {
        "eng": "en",
        "en": "en",
        "latin": "latin",
        "deu": "de",
        "ger": "de",
        "de": "de",
        "fra": "fr",
        "fre": "fr",
        "fr": "fr",
        "ita": "it",
        "it": "it",
        "spa": "es",
        "es": "es",
        "por": "pt",
        "pt": "pt",
        "nld": "nl",
        "nl": "nl",
        "pol": "pl",
        "pl": "pl",
        "ces": "cs",
        "cze": "cs",
        "cs": "cs",
        "dan": "da",
        "da": "da",
        "est": "et",
        "et": "et",
        "fin": "fi",
        "fi": "fi",
        "ron": "ro",
        "rum": "ro",
        "ro": "ro",
        "slk": "sk",
        "slo": "sk",
        "sk": "sk",
        "slv": "sl",
        "sl": "sl",
        "swe": "sv",
        "sv": "sv",
        "tur": "tr",
        "tr": "tr",
        "rus": "ru",
        "ru": "ru",
        "bel": "be",
        "be": "be",
        "ukr": "uk",
        "uk": "uk",
        "ell": "el",
        "gre": "el",
        "el": "el",
        "ara": "ar",
        "ar": "ar",
        "fas": "fa",
        "per": "fa",
        "fa": "fa",
        "urd": "ur",
        "ur": "ur",
        "hin": "hi",
        "hi": "hi",
        "jpn": "japan",
        "ja": "japan",
        "japan": "japan",
        "kor": "korean",
        "ko": "korean",
        "korean": "korean",
        "chi_sim": "ch",
        "zh": "ch",
        "zh_cn": "ch",
        "ch": "ch",
        "chi_tra": "chinese_cht",
        "zh_tw": "chinese_cht",
        "chinese_cht": "chinese_cht",
        "tha": "th",
        "th": "th",
        "tam": "ta",
        "ta": "ta",
        "tel": "te",
        "te": "te",
    }

    def extract_text(self, provider, document):
        if provider.ai_ocr_backend == "paddleocr":
            try:
                return self._extract_text_paddleocr(provider, document)
            except Exception as exc:  # pragma: no cover - optional dependency and runtime behavior
                _logger.warning("PaddleOCR backend failed for %s: %s. Falling back to Tesseract.", document.display_name, exc)
                if hasattr(document, "_log_event"):
                    document._log_event(
                        "warning",
                        "PaddleOCR backend failed. Falling back to Tesseract.",
                        {"error": str(exc)},
                    )
        return self._extract_text_tesseract(provider, document)

    def extract_json(self, provider, document, schema):
        return self.env["ob.ocr.ai.local.service"].extract_json(provider, document, schema)

    def detect_language(self, provider, document):
        if document.language or document.detected_language:
            return document.language or document.detected_language
        return super().detect_language(provider, document)

    def _extract_text_paddleocr(self, provider, document):
        native_pdf_pages = []
        native_pdf_text = False
        if provider.ai_paddleocr_use_native_pdf_text and document.mimetype in self.DEFAULT_PDF_MIMETYPES:
            native_pdf_pages = self._extract_native_pdf_pages(document)
            native_pdf_text = "\n\n".join(filter(None, native_pdf_pages)).strip() if native_pdf_pages else False
            if self._should_use_native_pdf_text_only(native_pdf_text, native_pdf_pages):
                if hasattr(document, "_log_event"):
                    document._log_event(
                        "info",
                        "Using native PDF text instead of image OCR.",
                        {"page_count": len(native_pdf_pages)},
                    )
                return {
                    "text": native_pdf_text,
                    "confidence": 99.0,
                    "page_count": len(native_pdf_pages),
                    "detected_language": self._resolve_paddleocr_language(provider, document=document),
                    "layout_json": {
                        "source": "native_pdf_text",
                        "pages": self._build_native_pdf_layout_pages(native_pdf_pages),
                    },
                }
        try:
            import numpy as np
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise UserError(_(
                "The PaddleOCR backend requires the optional Python packages "
                "'paddleocr', 'paddle', and 'numpy'."
            )) from exc

        images = self._prepare_images(document)
        pipeline = self._build_paddleocr_pipeline(PaddleOCR, provider, document=document)

        extracted_pages = []
        confidences = []
        layout_pages = []
        attachment_model = self.env["ir.attachment"].sudo()
        preprocess_service = self.env["ob.ocr.image.preprocess.service"]

        for index, image in enumerate(images, start=1):
            processed_image = preprocess_service.preprocess_image(image, document=document)
            result = self._run_paddleocr_pipeline(pipeline, np.array(processed_image.convert("RGB")))
            texts, scores, layout_page = self._coerce_paddle_page_result(result, page_number=index)
            extracted_pages.append(" ".join(texts))
            confidences.extend(scores)
            layout_pages.append(layout_page)
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

        ocr_text = "\n\n".join(page for page in extracted_pages if page).strip()
        return {
            "text": self._merge_text_sources(native_pdf_text, ocr_text),
            "confidence": sum(confidences) / len(confidences) if confidences else 0.0,
            "page_count": len(images),
            "detected_language": self._resolve_paddleocr_language(provider, document=document),
            "layout_json": {"source": "paddleocr", "pages": layout_pages},
        }

    def _build_paddleocr_pipeline(self, paddleocr_class, provider, document=None):
        params = {
            "lang": self._resolve_paddleocr_language(provider, document=document),
            "ocr_version": provider.ai_paddleocr_version or "PP-OCRv5",
            "device": self._resolve_paddleocr_device(provider),
            "use_doc_orientation_classify": bool(provider.ai_paddleocr_use_doc_orientation_classify),
            "use_doc_unwarping": bool(provider.ai_paddleocr_use_doc_unwarping),
            "use_textline_orientation": bool(provider.ai_paddleocr_use_textline_orientation),
        }
        if provider.ai_paddleocr_detection_model_name:
            params["text_detection_model_name"] = provider.ai_paddleocr_detection_model_name
        if provider.ai_paddleocr_recognition_model_name:
            params["text_recognition_model_name"] = provider.ai_paddleocr_recognition_model_name
        try:
            return paddleocr_class(**params)
        except TypeError:
            return paddleocr_class(
                lang=params["lang"],
                use_angle_cls=bool(provider.ai_paddleocr_use_doc_orientation_classify),
            )

    def _run_paddleocr_pipeline(self, pipeline, image_array):
        if hasattr(pipeline, "predict"):
            return pipeline.predict(image_array)
        if hasattr(pipeline, "ocr"):
            return pipeline.ocr(image_array, cls=True)
        raise UserError(_("The installed PaddleOCR package does not expose a supported inference API."))

    def _coerce_paddle_page_result(self, result, page_number=1):
        if isinstance(result, list) and len(result) == 1:
            result = result[0]
        payload = self._extract_paddle_payload(result)
        if payload:
            texts = [str(text).strip() for text in (payload.get("rec_texts") or payload.get("texts") or []) if str(text).strip()]
            scores = [float(score) for score in (payload.get("rec_scores") or payload.get("scores") or []) if score is not None]
            polys = payload.get("dt_polys") or payload.get("polys") or payload.get("boxes") or []
            return texts, scores, self._build_paddle_layout_page(texts, scores, polys, page_number=page_number)
        old_style_lines = self._extract_old_style_paddle_lines(result)
        texts = [item["text"] for item in old_style_lines if item.get("text")]
        scores = [item["score"] for item in old_style_lines if item.get("score") is not None]
        polys = [item.get("poly") for item in old_style_lines]
        return texts, scores, self._build_paddle_layout_page(texts, scores, polys, page_number=page_number)

    def _extract_paddle_payload(self, result):
        candidates = [result]
        if hasattr(result, "result"):
            candidates.append(getattr(result, "result"))
        if hasattr(result, "res"):
            candidates.append(getattr(result, "res"))
        for candidate in candidates:
            if isinstance(candidate, dict) and (candidate.get("rec_texts") or candidate.get("texts")):
                return candidate
        return False

    def _build_paddle_layout_page(self, texts, scores, polys, page_number=1):
        lines = []
        words = []
        for index, text in enumerate(texts):
            if not text:
                continue
            poly = polys[index] if index < len(polys) else False
            left, top, right, bottom = self._coerce_poly_bounds(poly, fallback_index=index)
            score = float(scores[index]) if index < len(scores) else 0.0
            line_words = self._approximate_words_from_line_text(
                text,
                left=left,
                top=top,
                right=right,
                bottom=bottom,
                confidence=score,
                page_number=page_number,
                line_number=index + 1,
            )
            words.extend(line_words)
            lines.append({
                "text": text,
                "top": top,
                "left": left,
                "right": right,
                "height": max(bottom - top, 1),
                "page_num": page_number,
                "confidence": score,
                "poly": poly,
                "words": line_words,
            })
        lines.sort(key=lambda item: (item["top"], item["left"]))
        words.sort(key=lambda item: (item["top"], item["left"]))
        return {
            "page_num": page_number,
            "words": words,
            "lines": lines,
        }

    def _coerce_poly_bounds(self, poly, fallback_index=0):
        if poly is False or poly is None:
            top = fallback_index * 30
            return 0, top, 1000, top + 18
        points = []
        try:
            iterable = poly.tolist() if hasattr(poly, "tolist") else poly
            for point in iterable:
                if hasattr(point, "tolist"):
                    point = point.tolist()
                if isinstance(point, (list, tuple)) and len(point) >= 2:
                    points.append((float(point[0]), float(point[1])))
        except Exception:
            points = []
        if not points:
            top = fallback_index * 30
            return 0, top, 1000, top + 18
        xs = [int(round(point[0])) for point in points]
        ys = [int(round(point[1])) for point in points]
        return min(xs), min(ys), max(xs), max(ys)

    def _approximate_words_from_line_text(self, text, left, top, right, bottom, confidence, page_number, line_number):
        raw_text = str(text or "")
        token_matches = list(re.finditer(r"\S+", raw_text))
        tokens = [match.group(0) for match in token_matches] or [raw_text]
        width = max(int(right) - int(left), len(raw_text) * 8, len(tokens) * 24)
        text_length = max(len(raw_text), 1)
        words = []
        for word_index, token in enumerate(tokens, start=1):
            match = token_matches[word_index - 1] if word_index - 1 < len(token_matches) else False
            start_index = match.start() if match else 0
            end_index = match.end() if match else len(token)
            token_left = int(left + (width * (start_index / text_length)))
            token_right = int(left + (width * (end_index / text_length)))
            token_width = max(token_right - token_left, len(token) * 7)
            words.append({
                "text": token,
                "left": token_left,
                "top": int(top),
                "width": token_width,
                "height": max(int(bottom) - int(top), 1),
                "confidence": confidence,
                "block_num": 1,
                "par_num": 1,
                "line_num": line_number,
                "word_num": word_index,
                "page_num": page_number,
            })
        return words

    def _should_use_native_pdf_text_only(self, native_pdf_text, native_pdf_pages):
        text = (native_pdf_text or "").strip()
        if not text or not native_pdf_pages:
            return False
        normalized = re.sub(r"\s+", " ", text)
        non_empty_lines = sum(1 for line in text.splitlines() if line.strip())
        longest_page = max((len((page or "").strip()) for page in native_pdf_pages), default=0)
        alnum_ratio = float(sum(1 for char in normalized if char.isalnum())) / float(max(len(normalized), 1))
        if not (len(normalized) >= 300 and non_empty_lines >= 8 and longest_page >= 150 and alnum_ratio >= 0.45):
            return False
        return not self._native_pdf_text_is_suspicious(normalized)

    def _native_pdf_text_is_suspicious(self, normalized_text):
        text = str(normalized_text or "")
        if not text:
            return True
        suspicious_chars = set("!\"'[]{}<>;\\")
        suspicious_ratio = float(sum(1 for char in text if char in suspicious_chars)) / float(max(len(text), 1))
        punctuation_run_count = len(re.findall(r"[!\"'\[\]{}<>;\\]{3,}", text))
        weird_token_count = sum(
            1
            for token in re.findall(r"\S+", text)
            if len(token) >= 8 and re.search(r"[!\"'\[\]{}<>;\\]", token)
        )
        return suspicious_ratio >= 0.018 and (punctuation_run_count >= 1 or weird_token_count >= 4)

    def _build_native_pdf_layout_pages(self, page_texts, confidence=99.0):
        pages = []
        for page_number, page_text in enumerate(page_texts, start=1):
            pages.append(self._build_native_pdf_layout_page(page_text, page_number=page_number, confidence=confidence))
        return pages

    def _build_native_pdf_layout_page(self, page_text, page_number=1, confidence=99.0):
        lines = []
        words = []
        visible_line_number = 0
        for raw_line in (page_text or "").splitlines():
            if not raw_line.strip():
                continue
            visible_line_number += 1
            line_text = raw_line.rstrip("\n\r")
            leading_spaces = len(line_text) - len(line_text.lstrip(" "))
            top = 40 + ((visible_line_number - 1) * 18)
            left = 40 + min(leading_spaces * 6, 320)
            right = left + max(len(line_text) * 7, 80)
            line_words = self._approximate_words_from_line_text(
                line_text,
                left=left,
                top=top,
                right=right,
                bottom=top + 15,
                confidence=confidence,
                page_number=page_number,
                line_number=visible_line_number,
            )
            words.extend(line_words)
            lines.append({
                "text": line_text.strip(),
                "top": top,
                "left": left,
                "right": right,
                "height": 15,
                "page_num": page_number,
                "confidence": confidence,
                "words": line_words,
            })
        return {
            "page_num": page_number,
            "words": words,
            "lines": lines,
        }

    def _resolve_paddleocr_language(self, provider, document=None):
        for candidate in [
            document.language if document else False,
            document.detected_language if document else False,
            provider.ai_paddleocr_lang,
            "en",
        ]:
            resolved = self._map_paddleocr_language(candidate)
            if resolved:
                return resolved
        return "en"

    def _map_paddleocr_language(self, value):
        candidate = (value or "").strip().lower().replace("-", "_")
        if not candidate:
            return False
        if "+" in candidate:
            candidate = next((part for part in candidate.split("+") if part.strip()), candidate)
        if candidate == "latin":
            return "en"
        return self.PADDLEOCR_LANGUAGE_MAP.get(candidate, candidate)

    def _resolve_paddleocr_device(self, provider):
        requested = (provider.ai_device or "auto").strip().lower()
        if requested == "cpu":
            return "cpu"
        if requested == "cuda":
            return "gpu:0"
        if requested == "mps":
            return "cpu"
        try:
            import paddle

            if hasattr(paddle, "is_compiled_with_cuda") and paddle.is_compiled_with_cuda():
                return "gpu:0"
        except Exception:
            pass
        return "cpu"

    def _extract_old_style_paddle_lines(self, item):
        lines = []
        if isinstance(item, (list, tuple)):
            for element in item:
                if (
                    isinstance(element, (list, tuple))
                    and len(element) >= 2
                    and isinstance(element[1], (list, tuple))
                    and len(element[1]) >= 2
                ):
                    text = str(element[1][0]).strip()
                    score = float(element[1][1]) if element[1][1] is not None else 0.0
                    if text:
                        lines.append({
                            "text": text,
                            "score": score,
                            "poly": element[0],
                        })
                elif isinstance(element, (list, tuple)):
                    lines.extend(self._extract_old_style_paddle_lines(element))
        return lines
