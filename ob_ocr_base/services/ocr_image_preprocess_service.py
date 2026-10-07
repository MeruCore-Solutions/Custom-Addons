import io

from odoo import models


class OCRImagePreprocessService(models.AbstractModel):
    _name = "ob.ocr.image.preprocess.service"
    _description = "OCR Image Preprocess Service"

    def preprocess_image(self, image, document=None):
        """Apply a lightweight, dependency-safe preprocessing pipeline."""
        if image.mode not in ("L", "RGB"):
            image = image.convert("RGB")
        if image.mode == "RGB":
            image = image.convert("L")
        try:
            from PIL import ImageOps

            image = ImageOps.autocontrast(image)
        except ImportError:
            pass
        return image

    def image_to_png_bytes(self, image):
        """Serialize a PIL image to PNG bytes."""
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return buffer.getvalue()
