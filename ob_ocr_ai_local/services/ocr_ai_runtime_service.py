import importlib
import platform
import sys
import warnings

from odoo import _, models


class OCRAIRuntimeService(models.AbstractModel):
    _name = "ob.ocr.ai.runtime.service"
    _description = "OCR Local AI Runtime Diagnostics Service"

    STATUS_READY = "ready"
    STATUS_PARTIAL = "partial"
    STATUS_MISSING = "missing_dependencies"
    STATUS_UNSUPPORTED = "unsupported_platform"

    def get_provider_runtime_status(self, provider):
        issues = []
        recommendations = []
        status = self.STATUS_READY
        paddle_status = self.STATUS_READY
        text_status = self.STATUS_READY

        if (provider.provider_key or "").strip().lower() != "local_ai":
            return {
                "status": self.STATUS_READY,
                "message": _("This provider does not use the local AI runtime."),
            }

        if provider.ai_ocr_backend == "paddleocr":
            paddle_status, paddle_issue, paddle_recommendation = self._check_paddleocr_runtime()
            status = self._merge_status(status, paddle_status)
            if paddle_issue:
                issues.append(paddle_issue)
            if paddle_recommendation:
                recommendations.append(paddle_recommendation)

        if provider.ai_backend == "transformers_text":
            text_status, text_issue, text_recommendation = self._check_transformers_runtime()
            status = self._merge_status(status, text_status)
            if text_issue:
                issues.append(text_issue)
            if text_recommendation:
                recommendations.append(text_recommendation)

        if (
            provider.ai_ocr_backend == "paddleocr"
            and paddle_status == self.STATUS_READY
            and provider.ai_backend == "transformers_text"
            and text_status == self.STATUS_PARTIAL
        ):
            parts = [
                _("PaddleOCR text extraction is ready."),
                _("Optional local AI JSON extraction is not available in this environment, so the provider will use the built-in fallback extraction path:"),
            ]
            parts.extend("- %s" % issue for issue in issues)
            if recommendations:
                parts.append("")
                parts.append(_("Recommended next step:"))
                parts.extend("- %s" % recommendation for recommendation in recommendations)
            return {
                "status": self.STATUS_READY,
                "message": "\n".join(parts),
            }

        if not issues:
            if provider.ai_ocr_backend == "paddleocr" and provider.ai_backend == "transformers_text":
                message = _(
                    "PaddleOCR text extraction and the local Transformers JSON extraction stack are ready."
                )
            elif provider.ai_ocr_backend == "paddleocr":
                message = _("PaddleOCR text extraction is ready.")
            elif provider.ai_backend == "transformers_text":
                message = _("The local Transformers JSON extraction stack is ready.")
            else:
                message = _("The local AI provider is ready.")
            return {"status": status, "message": message}

        parts = [_("Issues detected:")]
        parts.extend("- %s" % issue for issue in issues)
        if recommendations:
            parts.append("")
            parts.append(_("Recommended next step:"))
            parts.extend("- %s" % recommendation for recommendation in recommendations)
        return {
            "status": status,
            "message": "\n".join(parts),
        }

    def _check_paddleocr_runtime(self):
        system_name = platform.system()
        machine = platform.machine().lower()
        python_version = sys.version_info[:2]

        if python_version < (3, 9) or python_version > (3, 13):
            return (
                self.STATUS_UNSUPPORTED,
                _(
                    "PaddleOCR is configured, but the current Python version is outside PaddlePaddle's documented support range of Python 3.9 to 3.13."
                ),
                _(
                    "Use a Python 3.9 to 3.13 environment for the PaddleOCR runtime."
                ),
            )
        if system_name == "Darwin" and machine == "x86_64":
            return (
                self.STATUS_UNSUPPORTED,
                _(
                    "PaddleOCR is configured, but PaddlePaddle's current macOS pip packages are documented for Apple Silicon arm64 CPU environments, not macOS x86_64."
                ),
                _(
                    "Use an Apple Silicon Python environment, or run PaddleOCR on a Linux worker/container."
                ),
            )

        missing = self._missing_modules(["numpy", "paddleocr", "paddle"])
        if missing:
            return (
                self.STATUS_MISSING,
                _("Missing PaddleOCR dependencies: %s.") % ", ".join(missing),
                _(
                    "Install the PaddleOCR stack in a supported environment, including paddle, paddleocr, and numpy."
                ),
            )
        if system_name == "Darwin":
            return (
                self.STATUS_READY,
                False,
                _("PaddleOCR is available. PaddlePaddle's current macOS guidance supports CPU inference on Apple Silicon."),
            )
        return self.STATUS_READY, False, False

    def _check_transformers_runtime(self):
        python_version = sys.version_info[:2]
        if platform.system() == "Darwin" and python_version > (3, 12):
            version_string = ".".join(str(part) for part in sys.version_info[:3])
            return (
                self.STATUS_PARTIAL,
                _(
                    "The optional local AI JSON extraction stack is disabled because this macOS environment is running Python %s, while PyTorch's current macOS guidance recommends Python 3.9 to 3.12."
                ) % version_string,
                _(
                    "Use a Python 3.12 environment and install torch and transformers if you want schema-based local AI JSON extraction on this machine."
                ),
            )
        missing = self._missing_modules(["torch", "transformers"])
        if missing:
            return (
                self.STATUS_PARTIAL,
                _("Missing local AI text extraction dependencies: %s.") % ", ".join(missing),
                _(
                    "Install torch and transformers if you want schema-based local AI JSON extraction in this environment."
                ),
            )
        return self.STATUS_READY, False, False

    def _missing_modules(self, module_names):
        missing = []
        for module_name in module_names:
            try:
                with warnings.catch_warnings():
                    warnings.filterwarnings(
                        "ignore",
                        message=r"No ccache found\..*",
                        category=UserWarning,
                    )
                    importlib.import_module(module_name)
            except Exception:
                missing.append(module_name)
        return missing

    def _merge_status(self, current_status, new_status):
        ranking = {
            self.STATUS_READY: 0,
            self.STATUS_PARTIAL: 1,
            self.STATUS_MISSING: 2,
            self.STATUS_UNSUPPORTED: 3,
        }
        return new_status if ranking.get(new_status, 0) > ranking.get(current_status, 0) else current_status

    def get_environment_summary(self):
        version = ".".join(str(part) for part in sys.version_info[:3])
        return {
            "python_version": version,
            "system": platform.system(),
            "machine": platform.machine(),
        }
