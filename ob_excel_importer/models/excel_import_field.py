from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ExcelImportField(models.Model):
    _name = "ob.excel.import.field"
    _description = "Excel Import Field Mapping"
    _order = "sequence, id"

    template_id = fields.Many2one(
        "ob.excel.import.template",
        required=True,
        ondelete="cascade",
    )
    sequence = fields.Integer(default=10)
    excel_column = fields.Char(
        help="Excel column letter, for example A, B, AA.",
    )
    excel_header = fields.Char(
        help="Excel header name.",
    )
    target_field = fields.Char(required=True)
    target_field_type = fields.Char(
        compute="_compute_target_field_type",
        store=True,
    )
    required = fields.Boolean(default=False)
    transform = fields.Selection(
        [
            ("copy", "Copy"),
            ("char", "Char"),
            ("integer", "Integer"),
            ("float", "Float"),
            ("monetary", "Monetary"),
            ("boolean", "Boolean"),
            ("date", "Date"),
            ("datetime", "Datetime"),
            ("selection", "Selection"),
            ("many2one_name", "Many2one by Name"),
            ("many2one_ref", "Many2one by Reference"),
            ("many2many_names", "Many2many by Names"),
            ("one2many_lines", "One2many Lines"),
            ("python", "Python"),
            ("skip", "Skip"),
        ],
        default="copy",
        required=True,
    )
    python_expr = fields.Text()
    default_value = fields.Char()
    date_format = fields.Char()
    boolean_true_values = fields.Char(default="yes,true,1,y")
    boolean_false_values = fields.Char(default="no,false,0,n")
    m2o_search_field = fields.Char(default="name")
    missing_m2o_policy = fields.Selection(
        [
            ("skip", "Skip"),
            ("create", "Create"),
            ("error", "Error"),
        ],
        default="error",
    )
    x2many_separator = fields.Char(default=",")
    post_process = fields.Boolean(default=False)
    post_process_priority = fields.Integer(default=10)

    @api.depends("template_id.target_model", "target_field")
    def _compute_target_field_type(self):
        for mapping in self:
            field_type = False
            target_model = mapping.template_id.target_model
            if target_model and mapping.target_field and mapping.env.registry.get(target_model):
                field = mapping.env[target_model]._fields.get(mapping.target_field)
                if field:
                    field_type = field.type
            mapping.target_field_type = field_type

    @api.onchange("target_field")
    def _onchange_target_field(self):
        for mapping in self:
            target_model = mapping.template_id.target_model
            if not target_model or not mapping.target_field or not mapping.env.registry.get(target_model):
                continue
            field = mapping.env[target_model]._fields.get(mapping.target_field)
            if not field:
                continue
            transform_map = {
                "char": "char",
                "text": "char",
                "html": "char",
                "integer": "integer",
                "float": "float",
                "monetary": "monetary",
                "boolean": "boolean",
                "date": "date",
                "datetime": "datetime",
                "selection": "selection",
                "many2one": "many2one_name",
                "many2many": "many2many_names",
                "one2many": "one2many_lines",
            }
            detected = transform_map.get(field.type)
            if detected:
                mapping.transform = detected

    @api.constrains("transform", "python_expr")
    def _check_python_transform(self):
        for mapping in self:
            if mapping.transform == "python" and not mapping.python_expr:
                raise ValidationError(_("Python expression is required for Python transforms."))

    @api.constrains("excel_column")
    def _check_excel_column(self):
        for mapping in self:
            if mapping.excel_column and not mapping.excel_column.strip().isalpha():
                raise ValidationError(_("Excel column must contain letters only, for example A or AA."))
