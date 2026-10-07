import copy
import json
import logging
import re

from odoo import models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class OCRAILocalService(models.AbstractModel):
    _name = "ob.ocr.ai.local.service"
    _description = "OCR Local AI Extraction Service"

    _MODEL_CACHE = {}
    _TOKENIZER_CACHE = {}

    DEFAULT_LINE_ITEM_KEYS = [
        "product_code",
        "barcode",
        "product_name",
        "name",
        "quantity",
        "uom",
        "uom_name",
        "unit_price",
        "discount",
        "taxes",
        "amount",
        "delivery_date",
        "note",
    ]

    def extract_json(self, provider, document, schema):
        examples = self.env["ob.ocr.ai.feedback.service"].find_examples(
            document,
            provider=provider if provider.ai_feedback_enabled else False,
            limit=provider.ai_example_limit if provider.ai_feedback_enabled else 0,
        )
        backend = provider.ai_backend or "transformers_text"
        if backend == "stub":
            payload = self._extract_with_stub(document, schema, examples)
        elif backend == "transformers_text":
            payload = self._extract_with_transformers_text(provider, document, schema, examples)
        else:  # pragma: no cover - guarded by selection field
            raise UserError(self.env._("Unsupported local AI backend: %s") % backend)

        self.env["ob.ocr.ai.feedback.service"].mark_examples_used(examples)
        return self._normalize_payload(payload, schema if isinstance(schema, dict) else {})

    def _extract_with_stub(self, document, schema, examples):
        raw_text = (document.raw_text or "").strip()
        if raw_text.startswith("{"):
            try:
                parsed = json.loads(raw_text)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
        if examples:
            return copy.deepcopy(examples[0].extracted_json or {})
        return self._seed_payload(schema)

    def _extract_with_transformers_text(self, provider, document, schema, examples):
        raw_text = (document.raw_text or "").strip()
        if not raw_text:
            return self._seed_payload(schema)

        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
        except ImportError as exc:
            _logger.warning("Local AI extraction dependencies are unavailable for %s: %s", document.display_name, exc)
            if hasattr(document, "_log_event"):
                document._log_event(
                    "warning",
                    "Local AI JSON extraction dependencies are unavailable. Falling back to example and rule-based extraction.",
                    {"error": str(exc)},
                )
            return self._extract_with_stub(document, schema, examples)

        device = self._resolve_device(provider, torch)
        tokenizer, model = self._load_text_model(provider, torch, AutoTokenizer, AutoModelForCausalLM, device)
        prompt = self._build_prompt(provider, document, schema, examples)

        if hasattr(tokenizer, "apply_chat_template"):
            prompt = tokenizer.apply_chat_template(
                [
                    {"role": "system", "content": self._system_prompt()},
                    {"role": "user", "content": prompt},
                ],
                tokenize=False,
                add_generation_prompt=True,
            )
        else:
            prompt = "%s\n\n%s" % (self._system_prompt(), prompt)

        inputs = tokenizer(
            prompt,
            return_tensors="pt",
            truncation=True,
            max_length=min(getattr(tokenizer, "model_max_length", 8192), 8192),
        )
        inputs = {key: value.to(device) for key, value in inputs.items()}
        prompt_length = inputs["input_ids"].shape[-1]

        generation_kwargs = {
            "max_new_tokens": provider.ai_max_new_tokens or 1024,
            "do_sample": bool((provider.ai_temperature or 0.0) > 0.0),
            "pad_token_id": tokenizer.eos_token_id,
            "eos_token_id": tokenizer.eos_token_id,
        }
        if generation_kwargs["do_sample"]:
            generation_kwargs["temperature"] = provider.ai_temperature

        with torch.no_grad():
            output = model.generate(**inputs, **generation_kwargs)
        generated = tokenizer.decode(output[0][prompt_length:], skip_special_tokens=True).strip()
        payload = self._parse_json_from_text(generated)
        if not isinstance(payload, dict):
            raise UserError(self.env._(
                "The local AI model did not return valid JSON. "
                "Review the provider instructions or try a more extraction-focused model."
            ))
        return payload

    def _load_text_model(self, provider, torch, auto_tokenizer, auto_model, device):
        model_name = provider.ai_model_name or "Qwen/Qwen2.5-1.5B-Instruct"
        cache_key = (model_name, device)
        cached = self._MODEL_CACHE.get(cache_key)
        tokenizer = self._TOKENIZER_CACHE.get(model_name)
        if cached and tokenizer:
            return tokenizer, cached

        tokenizer = auto_tokenizer.from_pretrained(model_name, trust_remote_code=True)
        model = auto_model.from_pretrained(
            model_name,
            trust_remote_code=True,
            torch_dtype="auto",
        )
        model.to(device)
        model.eval()
        self._TOKENIZER_CACHE[model_name] = tokenizer
        self._MODEL_CACHE[cache_key] = model
        return tokenizer, model

    def _build_prompt(self, provider, document, schema, examples):
        max_context_chars = provider.ai_context_chars or 12000
        raw_text = (document.raw_text or "")[-max_context_chars:]
        prompt_parts = [
            "Document type: %s" % (document.document_type or "generic_document"),
            "Return a single JSON object only.",
            "Use null for unknown scalar values and [] for unknown collections.",
            "Do not invent values that are not present in the OCR text.",
            "Schema template:",
            json.dumps(self._build_schema_template(schema), indent=2, ensure_ascii=True),
        ]
        if provider.ai_additional_instructions:
            prompt_parts.extend([
                "Additional instructions:",
                provider.ai_additional_instructions.strip(),
            ])
        if examples:
            prompt_parts.append("Approved examples:")
            for index, example in enumerate(examples, start=1):
                prompt_parts.extend([
                    "Example %s OCR text:" % index,
                    (example.raw_text or "")[-4000:],
                    "Example %s JSON:" % index,
                    json.dumps(example.extracted_json or {}, indent=2, ensure_ascii=True),
                ])
        prompt_parts.extend([
            "OCR text:",
            raw_text,
        ])
        return "\n\n".join(prompt_parts)

    def _build_schema_template(self, schema):
        template = self._seed_payload(schema)
        collections = schema.get("collections", []) if isinstance(schema, dict) else []
        for collection_name in collections:
            template[collection_name] = [{key: None for key in self.DEFAULT_LINE_ITEM_KEYS}]
        return template

    def _seed_payload(self, schema):
        payload = {}
        if not isinstance(schema, dict):
            return payload
        for field_name in schema.get("fields", []):
            payload[field_name] = None
        for collection_name in schema.get("collections", []):
            payload.setdefault(collection_name, [])
        return payload

    def _normalize_payload(self, payload, schema):
        normalized = self._seed_payload(schema)
        if not isinstance(payload, dict):
            return {
                key: (False if not isinstance(value, list) else [])
                for key, value in normalized.items()
            }

        normalized.update({
            key: value for key, value in payload.items()
            if key in normalized or key == "document_type"
        })

        for key, value in list(normalized.items()):
            if isinstance(value, list):
                normalized[key] = [item for item in value if isinstance(item, dict)]
            elif value in (None, ""):
                normalized[key] = False
        return normalized

    def _parse_json_from_text(self, text):
        if not text:
            return {}
        try:
            return json.loads(text)
        except Exception:
            pass

        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except Exception as exc:  # pragma: no cover - best effort
                _logger.debug("Failed to parse JSON from model response: %s", exc)
        return {}

    def _resolve_device(self, provider, torch):
        if provider.ai_device and provider.ai_device != "auto":
            return provider.ai_device
        if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
            return "mps"
        if torch.cuda.is_available():
            return "cuda"
        return "cpu"

    def _system_prompt(self):
        return (
            "You extract business documents into JSON. "
            "Output valid JSON only, preserve original values, and keep arrays concise."
        )
