# ob_ocr_purchase_order_to_sale

`ob_ocr_purchase_order_to_sale` turns OCR customer purchase orders into draft `sale.order` quotations or sale orders.

## Features

- Adds document type `customer_purchase_order`
- Matches customers by VAT, email, phone, name, or address
- Creates sale quotations with optional auto-confirmation after review
- Reuses the base OCR partner/product matchers, review workflow, and attachment logic
- Adds smart buttons from sale orders back to their OCR source documents

## Notes

- The module is intentionally review-driven and safe by default.
- Line extraction stays lightweight and extendable through the base provider and extraction services.
