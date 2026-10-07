# ob_ocr_quotation_to_purchase

`ob_ocr_quotation_to_purchase` converts OCR supplier quotations into draft `purchase.order` RFQs or purchase orders.

## Features

- Adds document type `supplier_quotation`
- Matches vendors by VAT, email, phone, name, or address
- Creates draft RFQs with optional auto-confirmation after review
- Reuses the base OCR review, mapping, attachment, partner, and product services
- Adds smart buttons from purchase orders back to their OCR source documents

## Notes

- The module is intentionally conservative and review-first.
- When OCR line extraction is partial, users can review the JSON and lines before creating the RFQ.
