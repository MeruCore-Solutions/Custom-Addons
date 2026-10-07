from odoo import api, fields, models


DEFAULT_ALLOWED_MODEL_CONFIGS = {
    "mail.activity": {
        "name": "Activities",
        "sequence": 10,
        "alias_keywords": "activity,activities,task,tasks,todo,to-do,follow-up",
        "search_limit": 10,
        "max_record_count": 10,
        "default_order": "date_deadline asc, write_date desc, id desc",
        "reference_field_names": "summary,res_name,res_model",
        "name_field_names": "summary,res_name",
        "date_field_names": "date_deadline",
        "allow_activity_creation": True,
        "allow_reminder_creation": True,
        "allow_dashboard_generation": True,
        "allow_validation": True,
    },
    "ob.ai.validation.result": {
        "name": "Validation Results",
        "sequence": 12,
        "alias_keywords": "validation,validations,validation failure,validation failures,validation result,validation results",
        "search_limit": 20,
        "max_record_count": 12,
        "default_order": "create_date desc, id desc",
        "reference_field_names": "name,record_model,record_res_id",
        "name_field_names": "name,record_model",
        "date_field_names": "create_date,write_date",
        "allow_dashboard_generation": True,
        "allow_validation": True,
    },
    "sale.order": {
        "name": "Sales Orders",
        "sequence": 20,
        "alias_keywords": "sales,sale order,sales order,revenue,bookings,confirmed sales",
        "search_limit": 10,
        "max_record_count": 8,
        "default_order": "date_order desc, id desc",
        "reference_field_names": "name,client_order_ref",
        "name_field_names": "name,client_order_ref",
        "date_field_names": "date_order,commitment_date",
        "allow_document_context": True,
        "allow_chatter_posting": True,
        "allow_activity_creation": True,
        "allow_reminder_creation": True,
        "allow_dashboard_generation": True,
        "allow_validation": True,
    },
    "crm.lead": {
        "name": "CRM Pipeline",
        "sequence": 22,
        "alias_keywords": "crm,lead,leads,opportunity,opportunities,pipeline,deal,deals",
        "search_limit": 12,
        "max_record_count": 10,
        "default_order": "priority desc, id desc",
        "reference_field_names": "name,partner_name,contact_name,email_from",
        "name_field_names": "name,partner_name,contact_name,email_from",
        "date_field_names": "date_deadline,date_open,date_closed,create_date",
        "allow_document_context": True,
        "allow_chatter_posting": True,
        "allow_activity_creation": True,
        "allow_reminder_creation": True,
        "allow_dashboard_generation": True,
        "allow_validation": True,
    },
    "sale.order.line": {
        "name": "Sales Order Lines",
        "sequence": 25,
        "alias_keywords": "sales line,order line,top product,best seller,most selling product",
        "search_limit": 20,
        "max_record_count": 12,
        "default_order": "write_date desc, id desc",
        "reference_field_names": "order_id,product_id,name",
        "name_field_names": "product_id,name",
        "date_field_names": "create_date,write_date",
        "allow_dashboard_generation": True,
        "allow_validation": True,
    },
    "stock.picking": {
        "name": "Transfers and Deliveries",
        "sequence": 30,
        "alias_keywords": "delivery,deliveries,shipment,shipments,picking,pickings,delivered sales",
        "search_limit": 10,
        "max_record_count": 8,
        "default_order": "scheduled_date desc, id desc",
        "reference_field_names": "name,origin",
        "name_field_names": "name,origin",
        "date_field_names": "scheduled_date,date_done,date_deadline",
        "allow_document_context": True,
        "allow_chatter_posting": True,
        "allow_activity_creation": True,
        "allow_reminder_creation": True,
        "allow_dashboard_generation": True,
        "allow_validation": True,
    },
    "stock.move": {
        "name": "Stock Moves",
        "sequence": 35,
        "alias_keywords": "stock move,delivery line,shipped item,delivered product",
        "search_limit": 20,
        "max_record_count": 12,
        "default_order": "date desc, id desc",
        "reference_field_names": "product_id,picking_id",
        "name_field_names": "product_id",
        "date_field_names": "date,date_deadline",
        "allow_dashboard_generation": True,
        "allow_validation": True,
    },
    "account.move": {
        "name": "Invoices",
        "sequence": 40,
        "alias_keywords": "invoice,invoices,invoiced sales,payment due,receivable,bill,bills",
        "search_limit": 10,
        "max_record_count": 8,
        "default_order": "invoice_date desc, id desc",
        "reference_field_names": "name,ref,payment_reference",
        "name_field_names": "name,ref,payment_reference",
        "date_field_names": "invoice_date_due,invoice_date,date",
        "allow_document_context": True,
        "allow_chatter_posting": True,
        "allow_activity_creation": True,
        "allow_reminder_creation": True,
        "allow_dashboard_generation": True,
        "allow_validation": True,
        "sensitivity_level": "accounting",
    },
    "res.partner": {
        "name": "Customers and Contacts",
        "sequence": 50,
        "alias_keywords": "customer,customers,partner,partners,contact,contacts",
        "search_limit": 10,
        "max_record_count": 8,
        "default_order": "write_date desc, id desc",
        "reference_field_names": "name,email,phone",
        "name_field_names": "name,email",
        "date_field_names": "create_date,write_date",
        "allow_document_context": True,
        "allow_chatter_posting": True,
        "allow_activity_creation": True,
        "allow_reminder_creation": True,
        "allow_dashboard_generation": True,
        "allow_validation": True,
    },
    "product.product": {
        "name": "Products",
        "sequence": 60,
        "alias_keywords": "product,products,sku,item,inventory item",
        "search_limit": 10,
        "max_record_count": 8,
        "default_order": "write_date desc, id desc",
        "reference_field_names": "default_code,name",
        "name_field_names": "name,default_code",
        "date_field_names": "create_date,write_date",
        "allow_dashboard_generation": True,
        "allow_validation": True,
    },
    "purchase.order": {
        "name": "Purchase Orders",
        "sequence": 70,
        "alias_keywords": "purchase,purchase order,vendor order,po",
        "search_limit": 10,
        "max_record_count": 8,
        "default_order": "date_order desc, id desc",
        "reference_field_names": "name,partner_ref",
        "name_field_names": "name,partner_ref",
        "date_field_names": "date_order,date_approve",
        "allow_document_context": True,
        "allow_chatter_posting": True,
        "allow_activity_creation": True,
        "allow_reminder_creation": True,
        "allow_dashboard_generation": True,
        "allow_validation": True,
    },
    "hr.employee": {
        "name": "Employees",
        "sequence": 80,
        "alias_keywords": "employee,employees,staff,team member",
        "search_limit": 10,
        "max_record_count": 8,
        "default_order": "name asc, id desc",
        "reference_field_names": "name,work_email",
        "name_field_names": "name,work_email",
        "date_field_names": "create_date,write_date",
        "allow_document_context": True,
        "allow_dashboard_generation": True,
        "allow_validation": True,
        "sensitivity_level": "hr",
    },
    "hr.leave": {
        "name": "Time Off",
        "sequence": 90,
        "alias_keywords": "leave,leaves,time off,pto,availability",
        "search_limit": 10,
        "max_record_count": 8,
        "default_order": "request_date_from desc, id desc",
        "reference_field_names": "name,employee_id",
        "name_field_names": "employee_id",
        "date_field_names": "request_date_from,request_date_to",
        "allow_document_context": True,
        "allow_dashboard_generation": True,
        "allow_validation": True,
        "sensitivity_level": "hr",
    },
}

DEFAULT_ALLOWED_FIELD_NAMES = {
    "mail.activity": [
        "display_name",
        "summary",
        "activity_type_id",
        "res_model",
        "res_name",
        "user_id",
        "date_deadline",
    ],
    "ob.ai.validation.result": [
        "display_name",
        "name",
        "record_model",
        "record_res_id",
        "validation_status",
        "review_status",
        "rule_id",
        "confidence_score",
        "create_date",
    ],
    "sale.order": [
        "display_name",
        "name",
        "partner_id",
        "state",
        "date_order",
        "commitment_date",
        "amount_untaxed",
        "amount_tax",
        "amount_total",
        "currency_id",
        "invoice_status",
        "user_id",
        "client_order_ref",
    ],
    "crm.lead": [
        "display_name",
        "name",
        "partner_id",
        "partner_name",
        "contact_name",
        "email_from",
        "phone",
        "user_id",
        "team_id",
        "stage_id",
        "type",
        "priority",
        "expected_revenue",
        "probability",
        "date_deadline",
        "date_open",
        "date_closed",
        "create_date",
        "company_currency",
        "won_status",
    ],
    "sale.order.line": [
        "display_name",
        "name",
        "order_id",
        "product_id",
        "product_uom_qty",
        "qty_delivered",
        "price_subtotal",
        "price_total",
        "price_reduce_taxexcl",
        "currency_id",
    ],
    "stock.picking": [
        "display_name",
        "name",
        "origin",
        "partner_id",
        "state",
        "picking_type_id",
        "picking_type_code",
        "scheduled_date",
        "date_done",
        "sale_id",
    ],
    "stock.move": [
        "display_name",
        "picking_id",
        "sale_line_id",
        "product_id",
        "quantity",
        "product_uom_qty",
        "price_unit",
        "state",
        "date",
        "date_deadline",
    ],
    "account.move": [
        "display_name",
        "name",
        "ref",
        "partner_id",
        "state",
        "move_type",
        "invoice_date",
        "invoice_date_due",
        "payment_state",
        "amount_untaxed",
        "amount_total",
        "amount_residual",
        "currency_id",
    ],
    "res.partner": [
        "display_name",
        "name",
        "email",
        "phone",
        "mobile",
        "city",
        "country_id",
        "company_type",
        "user_id",
    ],
    "product.product": [
        "display_name",
        "name",
        "default_code",
        "categ_id",
        "uom_id",
        "qty_available",
        "virtual_available",
    ],
    "purchase.order": [
        "display_name",
        "name",
        "partner_id",
        "state",
        "date_order",
        "date_approve",
        "amount_untaxed",
        "amount_tax",
        "amount_total",
        "currency_id",
        "partner_ref",
    ],
    "hr.employee": [
        "display_name",
        "name",
        "work_email",
        "work_phone",
        "job_title",
        "department_id",
        "parent_id",
    ],
    "hr.leave": [
        "display_name",
        "name",
        "employee_id",
        "holiday_status_id",
        "state",
        "request_date_from",
        "request_date_to",
        "number_of_days",
    ],
}

OPTIONAL_DEFAULT_ALLOWED_FIELD_NAMES = {
    "sale.order": [
        "margin",
        "margin_percent",
    ],
    "sale.order.line": [
        "margin",
        "margin_percent",
        "purchase_price",
    ],
}


class OBAIAllowedModel(models.Model):
    _name = "ob.ai.allowed.model"
    _description = "AI Allowed Odoo Model"
    _order = "sequence, name, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", string="Company")
    model_id = fields.Many2one(
        "ir.model",
        string="Odoo Model",
        required=True,
        domain="[('transient', '=', False)]",
        ondelete="cascade",
    )
    alias_keywords = fields.Char(
        string="Alias Keywords",
        help="Comma-separated keywords that help users identify this model in the assistant UI.",
    )
    allowed_field_ids = fields.Many2many(
        "ir.model.fields",
        "ob_ai_allowed_model_field_rel",
        "allowed_model_id",
        "field_id",
        string="Allowed Fields",
        domain="[('model_id', '=', model_id)]",
    )
    blocked_field_ids = fields.Many2many(
        "ir.model.fields",
        "ob_ai_blocked_model_field_rel",
        "allowed_model_id",
        "field_id",
        string="Blocked Fields",
        domain="[('model_id', '=', model_id)]",
    )
    max_record_count = fields.Integer(
        string="Max Records in Context",
        default=5,
    )
    search_limit = fields.Integer(
        string="Search Limit",
        default=5,
        help="Maximum number of records returned for routed AI searches and KPI lists.",
    )
    default_order = fields.Char(
        string="Default Search Order",
        default="write_date desc, id desc",
    )
    reference_field_names = fields.Char(
        string="Reference Search Fields",
        help="Comma-separated technical fields used to resolve business references from user prompts.",
    )
    name_field_names = fields.Char(
        string="Name Search Fields",
        help="Comma-separated technical fields used to match people, products, or partners by name.",
    )
    date_field_names = fields.Char(
        string="Date Fields",
        help="Comma-separated fields that represent due dates, scheduling dates, or business dates.",
    )
    allow_document_context = fields.Boolean(default=True)
    allow_chatter_posting = fields.Boolean()
    allow_activity_creation = fields.Boolean()
    allow_reminder_creation = fields.Boolean()
    allow_dashboard_generation = fields.Boolean(default=True)
    allow_validation = fields.Boolean(default=True)
    require_human_approval = fields.Boolean()
    sensitivity_level = fields.Selection(
        [
            ("general", "General"),
            ("accounting", "Accounting"),
            ("hr", "HR"),
            ("healthcare", "Healthcare"),
        ],
        default="general",
        required=True,
    )
    summary_prompt_template = fields.Text(
        string="Summary Prompt Template",
        default="Summarize the business context, key risks, blockers, and recommended next actions.",
    )

    _company_model_unique = models.Constraint(
        "UNIQUE(company_id, model_id)",
        "Only one allowed-model configuration per company and model is supported.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        model_names = {}
        for values in vals_list:
            if values.get("model_id") and not values.get("name"):
                model_id = values["model_id"]
                if model_id not in model_names:
                    model_names[model_id] = self.env["ir.model"].browse(model_id).display_name
                values["name"] = model_names[model_id]
            if values.get("model_id"):
                model = self.env["ir.model"].browse(values["model_id"])
                values.setdefault("reference_field_names", self._default_reference_fields(model.model))
                values.setdefault("name_field_names", self._default_name_fields(model.model))
                values.setdefault("date_field_names", self._default_date_fields(model.model))
                values.setdefault("allowed_field_ids", self._default_allowed_field_commands(model))
        return super().create(vals_list)

    @api.model
    def ensure_default_models(self):
        default_model_names = [model_name for model_name in DEFAULT_ALLOWED_MODEL_CONFIGS if model_name in self.env]
        if not default_model_names:
            return self.search([("active", "=", True)], order="sequence, id")
        existing_records = self.sudo().search([("model_id.model", "in", default_model_names)])
        existing_model_names = set(existing_records.mapped("model_id.model"))
        values_list = []
        for model_name in default_model_names:
            if model_name in existing_model_names:
                continue
            ir_model = self.env["ir.model"].sudo()._get(model_name)
            if not ir_model:
                continue
            values = dict(DEFAULT_ALLOWED_MODEL_CONFIGS[model_name])
            values["model_id"] = ir_model.id
            values_list.append(values)
        if values_list:
            self.sudo().create(values_list)
        active_models = self.search([("active", "=", True)], order="sequence, id")
        self._sync_dynamic_default_allowed_fields(active_models.filtered(lambda record: record.model_id.model in default_model_names))
        return active_models

    @api.model
    def _default_allowed_field_names(self, model_name):
        field_names = list(DEFAULT_ALLOWED_FIELD_NAMES.get(model_name, []))
        if not field_names:
            field_names = [
                "display_name",
                "name",
                "state",
                "partner_id",
                "user_id",
                "date",
                "date_deadline",
                "create_date",
                "write_date",
            ]
        for field_name in self._dynamic_default_allowed_field_names(model_name):
            if field_name not in field_names:
                field_names.append(field_name)
        return field_names

    @api.model
    def _dynamic_default_allowed_field_names(self, model_name):
        if model_name not in OPTIONAL_DEFAULT_ALLOWED_FIELD_NAMES or model_name not in self.env:
            return []
        model = self.env[model_name]
        return [field_name for field_name in OPTIONAL_DEFAULT_ALLOWED_FIELD_NAMES[model_name] if field_name in model._fields]

    @api.model
    def _sync_dynamic_default_allowed_fields(self, allowed_models):
        allowed_models = allowed_models.exists().sudo()
        field_model = self.env["ir.model.fields"].sudo()
        for allowed_model in allowed_models:
            dynamic_field_names = self._dynamic_default_allowed_field_names(allowed_model.model_id.model)
            if not dynamic_field_names:
                continue
            dynamic_fields = field_model.search([
                ("model_id", "=", allowed_model.model_id.id),
                ("name", "in", dynamic_field_names),
                ("ttype", "!=", "binary"),
            ])
            missing_fields = dynamic_fields - allowed_model.allowed_field_ids
            if missing_fields:
                allowed_model.write({
                    "allowed_field_ids": [(4, field_id) for field_id in missing_fields.ids],
                })

    @api.model
    def _default_allowed_field_commands(self, model):
        field_names = self._default_allowed_field_names(model.model)
        field_ids = self.env["ir.model.fields"].sudo().search([
            ("model_id", "=", model.id),
            ("name", "in", field_names),
            ("ttype", "!=", "binary"),
        ]).ids
        return [(6, 0, field_ids)] if field_ids else False

    @api.model
    def _default_reference_fields(self, model_name):
        defaults = {
            "stock.picking": "name,origin",
            "stock.move": "product_id,picking_id",
            "account.move": "name,ref,payment_reference",
            "sale.order": "name,client_order_ref",
            "crm.lead": "name,partner_name,contact_name,email_from",
            "sale.order.line": "order_id,product_id,name",
            "purchase.order": "name,partner_ref",
            "product.product": "default_code,name",
            "res.partner": "name,email,phone",
            "hr.employee": "name",
            "hr.leave": "employee_id",
        }
        return defaults.get(model_name, "name,display_name")

    @api.model
    def _default_name_fields(self, model_name):
        defaults = {
            "product.product": "name,default_code",
            "crm.lead": "name,partner_name,contact_name,email_from",
            "sale.order.line": "product_id,name",
            "stock.move": "product_id",
            "res.partner": "name,email",
            "hr.employee": "name,work_email",
            "hr.leave": "employee_id",
        }
        return defaults.get(model_name, "name,display_name")

    @api.model
    def _default_date_fields(self, model_name):
        defaults = {
            "stock.picking": "scheduled_date,date_deadline",
            "stock.move": "date,date_deadline",
            "account.move": "invoice_date_due,invoice_date,date",
            "mail.activity": "date_deadline",
            "sale.order": "date_order",
            "crm.lead": "date_deadline,date_open,date_closed,create_date",
            "sale.order.line": "create_date,write_date",
            "purchase.order": "date_approve,date_order",
            "hr.leave": "request_date_from,request_date_to",
        }
        return defaults.get(model_name, "create_date,write_date")
