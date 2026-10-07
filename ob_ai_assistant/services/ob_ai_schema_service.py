import hashlib
import json
from collections import defaultdict

from odoo import _, fields, models, release


ECOSYSTEM_DOMAIN_PREFIXES = {
    "sales": ["sale", "crm"],
    "finance": ["account", "l10n"],
    "inventory": ["stock", "mrp", "quality", "maintenance"],
    "procurement": ["purchase"],
    "hr": ["hr"],
    "project": ["project", "timesheet", "planning"],
    "support": ["helpdesk", "website_helpdesk"],
    "website": ["website", "portal", "ecommerce"],
}


class OBAISchemaService(models.AbstractModel):
    _name = "ob.ai.schema.service"
    _description = "AI Schema Service"

    def get_current_version(self):
        return self.env["ob.ai.schema.version"].sudo().search([("current", "=", True)], limit=1)

    def ensure_current_schema(self, trigger_source="auto"):
        current = self.get_current_version()
        auto_refresh_enabled = self._get_bool_param("ob_ai_assistant.schema_auto_refresh_enabled", True)
        if not current:
            return self.refresh_schema_registry(trigger_source=trigger_source or "auto")
        if not auto_refresh_enabled:
            return current
        live_checksum = self.compute_live_checksum()
        max_age_hours = max(self._get_int_param("ob_ai_assistant.schema_max_age_hours", 24), 1)
        refresh_deadline = current.completed_at or current.create_date or fields.Datetime.now()
        age_seconds = (fields.Datetime.now() - refresh_deadline).total_seconds()
        if current.checksum != live_checksum or age_seconds >= max_age_hours * 3600:
            return self.refresh_schema_registry(trigger_source=trigger_source or "auto")
        return current

    def refresh_schema_registry(self, trigger_source="manual"):
        version_model = self.env["ob.ai.schema.version"].sudo()
        module_model = self.env["ob.ai.schema.module"].sudo()
        schema_model_model = self.env["ob.ai.schema.model"].sudo()
        field_model = self.env["ob.ai.schema.field"].sudo()
        ir_model_model = self.env["ir.model"].sudo()
        ir_field_model = self.env["ir.model.fields"].sudo()
        installed_module_model = self.env["ir.module.module"].sudo()

        live_checksum = self.compute_live_checksum()
        current = self.get_current_version()
        if current and current.checksum == live_checksum and current.status == "ready":
            current.write({"current": True})
            return current

        version = version_model.create({
            "name": _("Schema Snapshot %s", fields.Datetime.now()),
            "status": "running",
            "trigger_source": trigger_source or "manual",
            "started_at": fields.Datetime.now(),
            "checksum": live_checksum,
            "odoo_version": release.version,
        })
        try:
            installed_modules = installed_module_model.search([("state", "=", "installed")], order="name")
            ir_models = ir_model_model.search([("transient", "=", False)], order="model")
            ir_fields = ir_field_model.search([("model_id", "in", ir_models.ids)], order="model, name")

            field_counts = defaultdict(int)
            relation_counts = defaultdict(int)
            for ir_field in ir_fields:
                field_counts[ir_field.model_id.id] += 1
                if ir_field.relation:
                    relation_counts[ir_field.model_id.id] += 1

            self._create_module_snapshots(version, installed_modules, module_model)
            schema_model_map = self._create_model_snapshots(version, ir_models, field_counts, relation_counts, schema_model_model)
            self._create_field_snapshots(version, ir_fields, schema_model_map, field_model)

            version.search([("current", "=", True), ("id", "!=", version.id)]).write({
                "current": False,
                "status": "archived",
            })
            version.write({
                "current": True,
                "status": "ready",
                "completed_at": fields.Datetime.now(),
                "module_count": len(installed_modules),
                "model_count": len(ir_models),
                "field_count": len(ir_fields),
                "last_error": False,
            })
            if self._get_bool_param("ob_ai_assistant.semantic_auto_sync_enabled", True):
                self.env["ob.ai.semantic.service"].sync_semantics(schema_version=version, force_update=False)
            self._cleanup_old_versions()
            return version
        except Exception as exc:  # noqa: BLE001
            version.write({
                "status": "error",
                "completed_at": fields.Datetime.now(),
                "last_error": str(exc),
            })
            raise

    def compute_live_checksum(self):
        installed_modules = self.env["ir.module.module"].sudo().search([("state", "=", "installed")], order="name")
        payload = {
            "odoo_version": release.version,
            "modules": [
                {
                    "name": module.name,
                    "installed_version": module.installed_version,
                    "latest_version": module.latest_version,
                    "state": module.state,
                }
                for module in installed_modules
            ],
            "model_count": self.env["ir.model"].sudo().search_count([("transient", "=", False)]),
            "field_count": self.env["ir.model.fields"].sudo().search_count([]),
        }
        raw = json.dumps(payload, sort_keys=True, default=str).encode()
        return hashlib.sha256(raw).hexdigest()

    def build_schema_context_for_route(self, conversation, route, schema_version=False):
        if not self._get_bool_param("ob_ai_assistant.generic_engine_enabled", True):
            return {}
        schema_version = schema_version or self.ensure_current_schema(trigger_source="conversation")
        model_names = self._route_model_names(conversation, route)
        if not model_names:
            return {}
        return {
            "version_id": schema_version.id,
            "checksum": schema_version.checksum,
            "odoo_version": schema_version.odoo_version,
            "models": self.get_model_schema_payload(model_names, user=conversation.user_id, schema_version=schema_version),
        }

    def build_ecosystem_context(self, schema_version=False, max_modules=20):
        schema_version = schema_version or self.get_current_version() or self.ensure_current_schema(trigger_source="auto")
        if not schema_version:
            return {}
        modules = schema_version.module_ids.sorted("technical_name")
        module_names = modules.mapped("technical_name")
        custom_modules = [
            module_name
            for module_name in module_names
            if module_name.startswith(("ob_", "x_", "custom_"))
        ]
        domains = []
        for code, prefixes in ECOSYSTEM_DOMAIN_PREFIXES.items():
            matched = [
                module_name
                for module_name in module_names
                if any(module_name == prefix or module_name.startswith("%s_" % prefix) for prefix in prefixes)
            ]
            if matched:
                domains.append({
                    "code": code,
                    "label": code.replace("_", " ").title(),
                    "module_count": len(matched),
                    "modules": matched[:max_modules],
                })
        application_modules = modules.filtered("application").mapped("technical_name")
        return {
            "schema_version_id": schema_version.id,
            "checksum": schema_version.checksum,
            "odoo_version": schema_version.odoo_version,
            "installed_module_count": len(modules),
            "application_modules": application_modules[:max_modules],
            "custom_modules": custom_modules[:max_modules],
            "business_domains": domains,
            "custom_model_count": len(schema_version.schema_model_ids.filtered(
                lambda model: any((module_name or "").startswith(("ob_", "x_", "custom_")) for module_name in (model.modules or "").split(","))
            )),
        }

    def get_model_schema_payload(self, model_names, user=False, schema_version=False):
        user = user or self.env.user
        schema_version = schema_version or self.get_current_version()
        if not schema_version or not model_names:
            return []
        access_service = self.env["ob.ai.access.service"].with_user(user).with_company(user.company_id)
        allowed_models = access_service.find_allowed_model_for_model_names(model_names, user=user)
        if not allowed_models:
            return []
        allowed_models_by_name = {allowed_model.model_id.model: allowed_model for allowed_model in allowed_models}
        schema_models = self.env["ob.ai.schema.model"].sudo().search([
            ("schema_version_id", "=", schema_version.id),
            ("model_name", "in", list(allowed_models_by_name)),
        ], order="model_name")
        payloads = []
        for schema_model in schema_models:
            allowed_model = allowed_models_by_name.get(schema_model.model_name)
            if not allowed_model:
                continue
            policy = access_service.get_model_access_policy(allowed_model, user=user)
            allowed_field_names = set(access_service.get_allowed_field_names(allowed_model, policy=policy))
            schema_fields = schema_model.field_ids.filtered(lambda field: field.name in allowed_field_names)[:24]
            payloads.append({
                "model": schema_model.model_name,
                "label": schema_model.display_name,
                "modules": schema_model.modules,
                "reference_fields": access_service._parse_field_names(policy.get("reference_field_names")),
                "name_fields": access_service._parse_field_names(policy.get("name_field_names")),
                "date_fields": access_service._parse_field_names(policy.get("date_field_names")),
                "allowed_actions": {
                    "dashboard": bool(policy.get("allow_dashboard_generation")),
                    "document_context": bool(policy.get("allow_document_context")),
                    "validation": bool(policy.get("allow_validation")),
                    "activity": bool(policy.get("allow_activity_creation")),
                    "reminder": bool(policy.get("allow_reminder_creation")),
                    "chatter": bool(policy.get("allow_chatter_posting")),
                },
                "fields": [
                    {
                        "name": field.name,
                        "label": field.field_description,
                        "type": field.ttype,
                        "relation": field.relation,
                        "required": field.required,
                        "readonly": field.readonly,
                        "store": field.store,
                    }
                    for field in schema_fields
                ],
            })
        return payloads

    def _route_model_names(self, conversation, route):
        model_names = []
        allowed_model = route.get("allowed_model")
        if allowed_model and allowed_model._name == "ob.ai.allowed.model" and allowed_model.id:
            model_names.append(allowed_model.model_id.model)
        target_record = route.get("target_record") or conversation.related_record_ref
        if target_record:
            model_names.append(target_record._name)
        target_model_name = route.get("target_model_name")
        if target_model_name and target_model_name not in {"multi_model", "False"}:
            model_names.append(target_model_name)
        if route.get("intent_code") == "business_overview":
            model_names.extend(["sale.order", "account.move", "stock.picking", "mail.activity", "sale.order.line"])
        unique_names = []
        for model_name in model_names:
            if model_name and model_name in self.env and model_name not in unique_names:
                unique_names.append(model_name)
        return unique_names

    def _create_module_snapshots(self, version, installed_modules, module_model):
        module_values = []
        for module in installed_modules:
            module_values.append({
                "schema_version_id": version.id,
                "technical_name": module.name,
                "display_name": module.shortdesc or module.display_name or module.name,
                "installed_version": module.installed_version,
                "latest_version": module.latest_version,
                "category_name": module.category_id.display_name if module.category_id else False,
                "summary": module.summary,
                "application": bool(module.application),
                "auto_install": bool(module.auto_install),
                "dependency_names": ", ".join(module.dependencies_id.mapped("name")),
            })
        self._create_in_batches(module_model, module_values)

    def _create_model_snapshots(self, version, ir_models, field_counts, relation_counts, schema_model_model):
        model_map = {}
        ir_model_list = list(ir_models)
        for offset in range(0, len(ir_model_list), 250):
            chunk = ir_model_list[offset:offset + 250]
            values = []
            for ir_model in chunk:
                values.append({
                    "schema_version_id": version.id,
                    "ir_model_id": ir_model.id,
                    "display_name": ir_model.name,
                    "model_name": ir_model.model,
                    "modules": ir_model.modules,
                    "info": ir_model.info,
                    "transient": bool(getattr(ir_model, "transient", False)),
                    "abstract": bool(getattr(ir_model, "abstract", False)),
                    "field_count": field_counts.get(ir_model.id, 0),
                    "relation_count": relation_counts.get(ir_model.id, 0),
                })
            created = schema_model_model.create(values)
            for ir_model, schema_model in zip(chunk, created):
                model_map[ir_model.id] = schema_model.id
        return model_map

    def _create_field_snapshots(self, version, ir_fields, schema_model_map, field_model):
        field_values = []
        for ir_field in ir_fields:
            schema_model_id = schema_model_map.get(ir_field.model_id.id)
            if not schema_model_id:
                continue
            field_values.append({
                "schema_version_id": version.id,
                "schema_model_id": schema_model_id,
                "ir_model_field_id": ir_field.id,
                "name": ir_field.name,
                "field_description": ir_field.field_description,
                "modules": ir_field.modules,
                "ttype": ir_field.ttype,
                "relation": ir_field.relation,
                "related": ir_field.related,
                "selection_json": self._selection_payload(ir_field),
                "required": bool(ir_field.required),
                "readonly": bool(ir_field.readonly),
                "store": bool(ir_field.store),
                "index": bool(ir_field.index),
                "copied": bool(ir_field.copied),
                "help_text": ir_field.help,
            })
            if len(field_values) >= 1000:
                field_model.create(field_values)
                field_values = []
        if field_values:
            field_model.create(field_values)

    def _selection_payload(self, ir_field):
        if ir_field.ttype != "selection" or not hasattr(ir_field, "selection_ids"):
            return False
        return [
            {"value": selection.value, "label": selection.name}
            for selection in ir_field.selection_ids
        ] or False

    def _cleanup_old_versions(self):
        max_keep = max(self._get_int_param("ob_ai_assistant.schema_snapshot_retention", 5), 1)
        versions = self.env["ob.ai.schema.version"].sudo().search([], order="create_date desc, id desc")
        stale_versions = versions[max_keep:]
        if stale_versions:
            stale_versions.unlink()

    def _create_in_batches(self, model, values_list, batch_size=500):
        for offset in range(0, len(values_list), batch_size):
            model.create(values_list[offset:offset + batch_size])

    def _get_bool_param(self, key, default=False):
        value = self.env["ir.config_parameter"].sudo().get_param(key, default=str(default))
        return value == "True"

    def _get_int_param(self, key, default=0):
        return int(self.env["ir.config_parameter"].sudo().get_param(key, default=str(default)) or default)
