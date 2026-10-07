from odoo import _, api, fields, models


INTENT_SELECTION = [
    ("general_query", "General Query"),
    ("generic_investigation", "Generic Investigation"),
    ("explain_record_status", "Explain Record Status"),
    ("summarize_document", "Summarize Document"),
    ("summarize_conversation", "Summarize Conversation"),
    ("delivery_status", "Delivery Status"),
    ("invoice_status", "Invoice Status"),
    ("payment_due", "Payment Due"),
    ("employee_availability", "Employee Availability"),
    ("stock_availability", "Stock Availability"),
    ("business_overview", "Business Overview"),
    ("customer_behavior_briefing", "Customer Behavior Briefing"),
    ("crm_briefing", "CRM Briefing"),
    ("sales_overview", "Sales Overview"),
    ("sales_order_margin_list", "Sales Order Margin List"),
    ("product_sales_ranking", "Product Sales Ranking"),
    ("delivery_worklist", "Delivery Worklist"),
    ("create_reminder", "Create Reminder"),
    ("create_activity", "Create Activity"),
    ("post_chatter", "Post Chatter"),
    ("generate_dashboard", "Generate Dashboard"),
    ("validate_record", "Validate Record"),
    ("overdue_items", "List Overdue Items"),
    ("today_priorities", "Today's Priorities"),
]


class OBAIPromptTemplate(models.Model):
    _name = "ob.ai.prompt.template"
    _description = "AI Prompt Template"
    _order = "code, version desc, id desc"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    description = fields.Text()
    active = fields.Boolean(default=True)
    company_id = fields.Many2one("res.company", string="Company")
    version = fields.Integer(default=1, required=True)
    intent_type = fields.Selection(INTENT_SELECTION, required=True, default="general_query")
    allowed_model_id = fields.Many2one("ob.ai.allowed.model", string="Allowed Model")
    keyword_pattern = fields.Char(
        string="Keyword Pattern",
        help="Comma-separated keywords or phrases used by the router to match this template.",
    )
    prompt_text = fields.Text(
        required=True,
        default="Answer from the supplied Odoo data, explain the current status, and recommend safe next steps.",
    )
    system_instruction = fields.Text()
    run_in_cron = fields.Boolean(string="Can Run in Cron")
    cron_interval_number = fields.Integer(default=1)
    cron_interval_type = fields.Selection(
        [
            ("minutes", "Minutes"),
            ("hours", "Hours"),
            ("days", "Days"),
            ("weeks", "Weeks"),
            ("months", "Months"),
        ],
        default="days",
    )
    requires_approval = fields.Boolean()
    store_input = fields.Boolean()
    store_output = fields.Boolean()
    retention_days = fields.Integer(default=30)
    allow_activity_creation = fields.Boolean()
    allow_chatter_post = fields.Boolean()
    allow_reminder_creation = fields.Boolean()
    allow_dashboard_generation = fields.Boolean()
    allow_validation = fields.Boolean()
    allow_document_context = fields.Boolean(default=True)
    read_only = fields.Boolean(default=True)
    note = fields.Text()

    _company_code_version_unique = models.Constraint(
        "UNIQUE(company_id, code, version)",
        "The prompt template code and version must be unique per company.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for values in vals_list:
            if not values.get("name") and values.get("code"):
                values["name"] = values["code"].replace("_", " ").title()
            if values.get("code") and not values.get("version"):
                domain = [("code", "=", values["code"])]
                if values.get("company_id"):
                    domain.append(("company_id", "=", values["company_id"]))
                else:
                    domain.append(("company_id", "=", False))
                latest = self.search(domain, order="version desc, id desc", limit=1)
                values["version"] = (latest.version or 0) + 1 if latest else 1
        return super().create(vals_list)

    def action_duplicate_new_version(self):
        self.ensure_one()
        new_version = self.copy({
            "name": _("%s v%s", self.name, self.version + 1),
            "version": self.version + 1,
            "active": True,
        })
        return {
            "type": "ir.actions.act_window",
            "name": _("Prompt Template"),
            "res_model": "ob.ai.prompt.template",
            "res_id": new_version.id,
            "view_mode": "form",
        }
