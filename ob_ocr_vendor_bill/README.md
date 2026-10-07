# ob_ocr_vendor_bill

`ob_ocr_vendor_bill` extends `ob_ocr_base` to turn OCR vendor bills into draft `account.move` records with `move_type = 'in_invoice'`.

## Features

- Adds document type `vendor_bill`
- Matches vendors by VAT, email, phone, name, or address
- Creates draft vendor bills after review
- Optionally creates vendors or products through base OCR settings
- Attaches the original OCR file to the generated bill
- Adds smart buttons from vendor bill to OCR documents and uses the base OCR linked-record button in the other direction

## Notes

- The module intentionally keeps extraction lightweight and review-first.
- Header fields are extracted through default regex rules.
- Line extraction remains extendable through provider JSON, custom rules, or future AI-assisted services.
