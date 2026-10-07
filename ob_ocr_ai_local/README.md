# OCR Local AI Extraction

`ob_ocr_ai_local` extends `ob_ocr_base` with:

- local AI schema-based extraction
- reusable feedback memory from reviewed OCR documents
- PaddleOCR / PP-OCRv5 as the primary multilingual OCR backend
- optional hybrid OCR backend selection per provider
- no mandatory ML dependency at install time

## What it solves

The base framework can still use regex and provider rules, but real-world multilingual documents often require repeated source-code changes. This addon adds a provider that:

- uses OCR text as input for a local text-to-JSON model
- reuses approved examples from earlier reviewed documents
- falls back safely when optional AI dependencies are unavailable

## Recommended setup

Small local multilingual extraction:

- OCR backend: `paddleocr`
- AI backend: `Local Transformers (Text)`
- Recommended starter model: `Qwen/Qwen2.5-1.5B-Instruct`

If you prefer extraction-focused models, you can point the provider to a compatible Hugging Face model path instead.

## Optional Python dependencies

Text extraction with local AI:

- `transformers`
- `torch`

Optional OCR backend:

- `paddleocr`
- `paddle`
- `numpy`

Current official installation outline:

```bash
pip install transformers torch
python -m pip install paddleocr
python -m pip install paddlepaddle==3.3.0 -i https://www.paddlepaddle.org.cn/packages/stable/cpu/
```

## Deployment recommendation

- Local macOS Apple Silicon development: PaddleOCR CPU inference is now supported by the current PaddlePaddle macOS arm64 installation path.
- Linux worker or container: PaddleOCR is still the best choice when you want CPU/GPU isolation or a dedicated OCR node.
- Structured extraction: pair either OCR backend with the local AI JSON extraction layer when `torch` and `transformers` are available.

The provider form now shows runtime diagnostics so administrators can see whether the current machine is ready for:

- PaddleOCR / PP-OCRv5 text extraction
- local Transformers JSON extraction
- safe fallback-only operation

## How feedback memory works

When a user reviews an OCR document and approves it, this addon stores:

- raw OCR text
- corrected extracted JSON
- document type
- language
- partner / reference hints

Future AI extraction prompts can reuse the most relevant approved examples for the same document type.

## Safe behavior

- The addon installs even if AI packages are missing.
- The provider runtime check warns when the current machine is not a suitable PaddleOCR host, such as macOS x86_64 or an unsupported Python runtime.
- If the local AI backend is selected but dependencies are not installed, the framework raises a clear setup error and the base extraction fallback can still be used.
- No model weights are modified online. “Learning” means storing reviewed examples and reusing them in prompts.

## PaddleOCR notes

- Provider default OCR version: `PP-OCRv5`
- Provider default language fallback: `en`
- The OCR service keeps emitting `layout_json`, so the downstream invoice-line extraction in `ob_ocr_base` continues to work.
- For PDFs, the provider can merge embedded native PDF text with PaddleOCR output to improve invoice numbers, dates, and partner names.
