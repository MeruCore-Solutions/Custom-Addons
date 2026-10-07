# OB Excel Importer

`ob_excel_importer` is a reusable Odoo 19 framework for importing `.xlsx` files into any Odoo model through configurable templates.

## Features

- Manual Excel upload with test import and real import flows
- Template-based imports for any target model
- Header or column-based field mapping
- Python hooks before mapping, row filtering, before write, and after import
- FTP and SFTP scheduled imports
- Import logs and row-level log lines
- Structured failed-line records with re-import support
- Responsible-user notifications and activity scheduling on blocking errors
- Record mapping table for source keys and re-import-safe updates
- Post-process queue for follow-up logic

## Workflow

1. Create an import template.
2. Select the target model.
3. Add field mappings manually or click `Generate Field Mappings`.
4. Upload an Excel file manually or configure FTP/SFTP settings.
5. Run `Test Import`.
6. Run the real import.
7. Review `Import Logs`.
8. Open `Not Imported Lines`.
9. Fix a failed row by editing `fixed_source_values`.
10. Click `Re-import Line`.
11. Confirm the line state changes to `Re-imported`.

## Example Templates

### Product Import

Excel columns:

- `Internal Reference`
- `Name`
- `Barcode`
- `Sales Price`
- `Cost`
- `Category`

Recommended mappings:

- `Internal Reference -> default_code`
- `Name -> name`
- `Barcode -> barcode`
- `Sales Price -> list_price`
- `Cost -> standard_price`
- `Category -> categ_id` using `many2one_name`

### Sale Order Import

Excel columns:

- `Order Reference`
- `Customer`
- `Product`
- `Quantity`
- `Unit Price`

Suggested approach:

- Use `Order Reference` as `external_key_column`.
- Set import mode to `Create or Update`.
- Use Python hooks or a `one2many_lines` mapping for `order_line`.

### Purchase Order Import

Excel columns:

- `PO Reference`
- `Vendor`
- `Product`
- `Quantity`
- `Unit Price`

Suggested approach:

- Use `PO Reference` as the external source key.
- Map vendor through `many2one_name`.
- Build order lines through Python logic or `one2many_lines`.

### Vendor Bill Import

Excel columns:

- `Bill Reference`
- `Vendor`
- `Bill Date`
- `Product`
- `Quantity`
- `Price`

Suggested approach:

- Map bill header fields directly.
- Use deferred or Python-driven line construction for invoice lines.

## Notes

- Only `.xlsx` files are supported.
- `openpyxl` is required.
- `paramiko` is optional and only needed for SFTP imports.
