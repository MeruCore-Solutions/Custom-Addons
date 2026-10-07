# ob_ocr_delivery_slip

`ob_ocr_delivery_slip` extends `ob_ocr_base` to create or update `stock.picking` records from OCR delivery slips.

## Features

- Adds document type `delivery_slip`
- Matches existing pickings by source document or delivery reference
- Falls back to draft picking creation when no picking is found
- Updates delivered quantities through stock move lines
- Attaches the original OCR file to the target picking
- Adds smart buttons from pickings back to OCR documents
- Auto-validation stays disabled unless explicitly enabled in OCR settings

## Notes

- This module is deliberately conservative with transfer validation.
- Users can review the extracted JSON and line items before applying quantities to stock operations.
