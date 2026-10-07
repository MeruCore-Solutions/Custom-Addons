import hashlib

from markupsafe import Markup, escape

from odoo import _, fields, models
from odoo.exceptions import UserError


class OBAIActionService(models.AbstractModel):
    _name = "ob.ai.action.service"
    _description = "AI Action Service"

    def create_reminder_from_prompt(self, conversation, route, prompt, source_message=False, bypass_approval=False):
        conversation.ensure_one()
        target_record = route.get("target_record")
        memory_state = self._get_memory_state_for_route(conversation, route)
        if not target_record and memory_state:
            return self.create_reminders_from_memory_state(
                conversation,
                route,
                prompt,
                memory_state=memory_state,
                source_message=source_message,
                bypass_approval=bypass_approval,
            )
        allowed_model = route.get("allowed_model") or (
            self.env["ob.ai.access.service"].get_allowed_model(target_record._name) if target_record else False
        )
        self._ensure_model_action_allowed(allowed_model, "reminder")
        due_datetime = route.get("due_datetime") or fields.Datetime.now()
        assigned_user = self._get_assigned_user(route, target_record)
        text = self._clean_action_text(prompt)
        idempotency_key = self._make_idempotency_key("reminder", target_record, prompt, due_datetime)
        existing = self.env["ob.ai.reminder"].search(
            [
                ("company_id", "=", conversation.company_id.id),
                ("idempotency_key", "=", idempotency_key),
            ],
            limit=1,
        )
        if existing:
            return {
                "action_performed": "reminder_existing",
                "summary_text": _("The reminder already exists and was not duplicated."),
                "idempotency_key": idempotency_key,
                "record": existing,
                "memory_state": memory_state,
            }
        values = {
            "name": text[:80],
            "company_id": conversation.company_id.id,
            "requesting_user_id": self.env.user.id,
            "assigned_user_id": assigned_user.id if assigned_user else False,
            "related_record_ref": "%s,%s" % (target_record._name, target_record.id) if target_record else False,
            "reminder_text": text,
            "due_datetime": due_datetime,
            "status": "pending",
            "source_conversation_id": conversation.id,
            "source_message_id": source_message.id if source_message else False,
            "created_by_ai": True,
            "idempotency_key": idempotency_key,
        }
        if route.get("requires_approval") and not bypass_approval:
            approval = self._create_approval(
                conversation,
                route,
                "reminder",
                _("Create reminder: %s", text),
                values,
                target_record=target_record,
                idempotency_key=idempotency_key,
            )
            return {
                "action_performed": "approval_requested",
                "summary_text": _("The reminder needs approval before it is created."),
                "approval": approval,
                "idempotency_key": idempotency_key,
                "memory_state": memory_state,
            }
        reminder = self.env["ob.ai.reminder"].create(values)
        return {
            "action_performed": "reminder_created",
            "summary_text": _(
                "Created reminder %(name)s for %(user)s due %(due)s.",
                name=reminder.display_name,
                user=reminder.assigned_user_id.display_name or self.env.user.display_name,
                due=fields.Datetime.to_string(reminder.due_datetime),
            ),
            "record": reminder,
            "idempotency_key": idempotency_key,
            "memory_state": memory_state,
        }

    def create_activity_from_prompt(self, conversation, route, prompt, source_message=False, bypass_approval=False):
        conversation.ensure_one()
        target_record = route.get("target_record") or conversation.related_record_ref
        memory_state = self._get_memory_state_for_route(conversation, route)
        if not target_record and memory_state:
            return self.create_activities_from_memory_state(
                conversation,
                route,
                prompt,
                memory_state=memory_state,
                source_message=source_message,
                bypass_approval=bypass_approval,
            )
        if not target_record:
            raise UserError(_("Select a related record before creating an AI follow-up activity."))
        allowed_model = route.get("allowed_model") or self.env["ob.ai.access.service"].get_allowed_model(target_record._name)
        self._ensure_model_action_allowed(allowed_model, "activity")
        assigned_user = self._get_assigned_user(route, target_record)
        due_datetime = route.get("due_datetime") or fields.Datetime.now()
        activity_payload = self._build_activity_payload(route, target_record, prompt, due_datetime, memory_state=memory_state)
        idempotency_key = self._make_idempotency_key(
            "activity",
            target_record,
            activity_payload.get("idempotency_text"),
            activity_payload.get("idempotency_marker"),
        )
        existing = self._find_existing_activity(target_record, assigned_user, idempotency_key)
        if existing:
            return {
                "action_performed": "activity_existing",
                "summary_text": _("A matching activity already exists and was not duplicated."),
                "idempotency_key": idempotency_key,
                "record": existing,
            }
        values = self._prepare_activity_values(
            target_record,
            assigned_user,
            due_datetime,
            idempotency_key,
            activity_payload=activity_payload,
        )
        if route.get("requires_approval") and not bypass_approval:
            approval = self._create_approval(
                conversation,
                route,
                "activity",
                _("Create activity on %s", target_record.display_name),
                values,
                target_record=target_record,
                idempotency_key=idempotency_key,
            )
            return {
                "action_performed": "approval_requested",
                "summary_text": _("The follow-up activity is pending approval."),
                "approval": approval,
                "idempotency_key": idempotency_key,
                "memory_state": memory_state,
            }
        activity = self.env["mail.activity"].create(values)
        return {
            "action_performed": "activity_created",
            "summary_text": _(
                "Created a follow-up activity for %(user)s on %(record)s.",
                user=activity.user_id.display_name,
                record=target_record.display_name,
            ),
            "record": activity,
            "idempotency_key": idempotency_key,
            "memory_state": memory_state,
        }

    def create_activities_for_records(self, conversation, route, records, prompt, source_message=False, bypass_approval=False, memory_state=False, reference_map=False):
        conversation.ensure_one()
        records = records.exists()
        if not records:
            return {
                "action_performed": "activity_skipped_no_records",
                "summary_text": _("No matching records were found, so no follow-up activities were created."),
                "records": self.env["mail.activity"],
                "approvals": self.env["ob.ai.approval"],
                "memory_state": memory_state,
            }
        allowed_model = route.get("allowed_model") or self.env["ob.ai.access.service"].get_allowed_model(records._name)
        self._ensure_model_action_allowed(allowed_model, "activity")
        created_activities = self.env["mail.activity"]
        approvals = self.env["ob.ai.approval"]
        existing_count = 0
        due_datetime = route.get("due_datetime") or fields.Datetime.now()
        access_service = self.env["ob.ai.access.service"]
        access_policy = access_service.get_model_access_policy(allowed_model)
        context_bundle = self._build_records_context_bundle(
            records,
            allowed_model,
            source="memory_action_result_set" if memory_state else "action_result_set",
            access_policy=access_policy,
        )
        for target_record in records:
            assigned_user = self._get_assigned_user(route, target_record)
            activity_payload = self._build_activity_payload(
                route,
                target_record,
                prompt,
                due_datetime,
                memory_state=memory_state,
                reference_map=reference_map,
            )
            idempotency_key = self._make_idempotency_key(
                "activity",
                target_record,
                activity_payload.get("idempotency_text"),
                activity_payload.get("idempotency_marker"),
            )
            existing = self._find_existing_activity(target_record, assigned_user, idempotency_key)
            if existing:
                existing_count += 1
                continue
            values = self._prepare_activity_values(
                target_record,
                assigned_user,
                due_datetime,
                idempotency_key,
                activity_payload=activity_payload,
            )
            if route.get("requires_approval") and not bypass_approval:
                approvals |= self._create_approval(
                    conversation,
                    route,
                    "activity",
                    _("Create activity on %s", target_record.display_name),
                    values,
                    target_record=target_record,
                    idempotency_key=idempotency_key,
                )
                continue
            created_activities |= self.env["mail.activity"].create(values)
        if approvals and not created_activities:
            return {
                "action_performed": "activities_pending_approval",
                "summary_text": self._memory_or_default_activity_summary(
                    route,
                    approvals_count=len(approvals),
                    existing_count=existing_count,
                    memory_state=memory_state,
                    created_count=0,
                ),
                "records": created_activities,
                "approvals": approvals,
                "approval": approvals[:1],
                "existing_count": existing_count,
                "context_bundle": context_bundle,
                "memory_state": memory_state,
            }
        if created_activities:
            summary_text = self._memory_or_default_activity_summary(
                route,
                created_count=len(created_activities),
                approvals_count=len(approvals),
                existing_count=existing_count,
                memory_state=memory_state,
            )
            return {
                "action_performed": "activities_created",
                "summary_text": summary_text,
                "records": created_activities,
                "approvals": approvals,
                "approval": approvals[:1],
                "existing_count": existing_count,
                "context_bundle": context_bundle,
                "memory_state": memory_state,
            }
        return {
            "action_performed": "activity_existing",
            "summary_text": self._memory_or_default_activity_summary(
                route,
                created_count=0,
                approvals_count=0,
                existing_count=existing_count or len(records),
                memory_state=memory_state,
            ),
            "records": created_activities,
            "approvals": approvals,
            "approval": approvals[:1],
            "existing_count": existing_count or len(records),
            "context_bundle": context_bundle,
            "memory_state": memory_state,
        }

    def create_activities_from_memory_state(self, conversation, route, prompt, memory_state=False, source_message=False, bypass_approval=False):
        conversation.ensure_one()
        memory_state = memory_state or self._get_memory_state_for_route(conversation, route)
        if not memory_state:
            raise UserError(_("I could not find a reusable AI result set for this follow-up action."))
        groups, warnings = self.env["ob.ai.memory.service"].get_actionable_result_groups(
            memory_state,
            user=conversation.user_id,
            company=conversation.company_id,
        )
        if not groups:
            raise UserError(_("The last AI result set does not contain any still-accessible records that can receive activities."))
        created_activities = self.env["mail.activity"]
        approvals = self.env["ob.ai.approval"]
        existing_count = 0
        combined_context = self.env["ob.ai.access.service"]._empty_context()
        for group in groups:
            group_policy = self.env["ob.ai.access.service"].get_model_access_policy(group["allowed_model"], user=conversation.user_id)
            group_route = dict(route)
            group_route.update({
                "allowed_model": group["allowed_model"],
                "target_model_name": group["model_name"],
                "requires_approval": route.get("requires_approval") or bool(group_policy.get("require_human_approval")),
                "approval_scope": group_policy.get("sensitivity_level") or route.get("approval_scope") or "general",
            })
            group_result = self.create_activities_for_records(
                conversation,
                group_route,
                group["records"],
                prompt,
                source_message=source_message,
                bypass_approval=bypass_approval,
                memory_state=memory_state,
                reference_map=group["reference_map"],
            )
            created_activities |= group_result.get("records") or self.env["mail.activity"]
            approvals |= group_result.get("approvals") or self.env["ob.ai.approval"]
            existing_count += group_result.get("existing_count") or 0
            self._merge_context_bundle(combined_context, group_result.get("context_bundle"))
        acted_record_count = sum(len(group["records"]) for group in groups)
        summary_lines = []
        if created_activities:
            summary_lines.append(
                _("Created %(count)s follow-up activities from the last AI result set across %(records)s visible records.", count=len(created_activities), records=acted_record_count)
            )
        if approvals:
            summary_lines.append(
                _("Prepared %(count)s follow-up activities for approval from the last AI result set.", count=len(approvals))
            )
        if existing_count:
            summary_lines.append(_("%s matching activities already existed and were not duplicated.", existing_count))
        if warnings:
            summary_lines.extend("- %s" % warning for warning in warnings)
        if not summary_lines:
            summary_lines.append(_("No new follow-up activities were created from the last AI result set."))
        action_performed = "activity_existing"
        if created_activities and approvals:
            action_performed = "activities_created + activities_pending_approval"
        elif created_activities:
            action_performed = "activities_created"
        elif approvals:
            action_performed = "activities_pending_approval"
        return {
            "action_performed": action_performed,
            "summary_text": "\n\n".join(summary_lines),
            "records": created_activities,
            "approvals": approvals,
            "approval": approvals[:1],
            "existing_count": existing_count,
            "context_bundle": combined_context,
            "memory_state": memory_state,
            "related_record_refs": memory_state.result_record_refs or [],
        }

    def post_chatter_from_prompt(self, conversation, route, body, bypass_approval=False):
        conversation.ensure_one()
        target_record = route.get("target_record") or conversation.related_record_ref
        memory_state = self._get_memory_state_for_route(conversation, route)
        if not target_record and memory_state:
            return self.post_chatter_from_memory_state(
                conversation,
                route,
                body,
                memory_state=memory_state,
                bypass_approval=bypass_approval,
            )
        if not target_record:
            raise UserError(_("Select a related record before posting an AI chatter note."))
        allowed_model = route.get("allowed_model") or self.env["ob.ai.access.service"].get_allowed_model(target_record._name)
        self._ensure_model_action_allowed(allowed_model, "chatter")
        if not hasattr(target_record, "message_post"):
            raise UserError(_("Model %s does not support chatter posting.") % target_record._name)
        clean_body = self._clean_action_text(body)
        idempotency_key = self._make_idempotency_key("chatter", target_record, clean_body, fields.Date.context_today(self))
        existing = self.env["mail.message"].search([
            ("model", "=", target_record._name),
            ("res_id", "=", target_record.id),
            ("body", "ilike", idempotency_key),
        ], limit=1)
        if existing:
            return {
                "action_performed": "chatter_existing",
                "summary_text": _("A matching chatter note already exists and was not duplicated."),
                "idempotency_key": idempotency_key,
                "record": existing,
                "memory_state": memory_state,
            }
        payload = {
            "body": "%s\n\nAI Idempotency: %s" % (clean_body, idempotency_key),
        }
        if route.get("requires_approval") and not bypass_approval:
            approval = self._create_approval(
                conversation,
                route,
                "chatter",
                _("Post chatter note on %s", target_record.display_name),
                payload,
                target_record=target_record,
                idempotency_key=idempotency_key,
            )
            return {
                "action_performed": "approval_requested",
                "summary_text": _("The chatter message is pending approval."),
                "approval": approval,
                "idempotency_key": idempotency_key,
                "memory_state": memory_state,
            }
        message = target_record.message_post(body=payload["body"], message_type="comment", subtype_xmlid="mail.mt_note")
        return {
            "action_performed": "chatter_posted",
            "summary_text": _("Posted an internal chatter note on %s.", target_record.display_name),
            "record": message,
            "idempotency_key": idempotency_key,
            "memory_state": memory_state,
        }

    def create_reminders_from_memory_state(self, conversation, route, prompt, memory_state=False, source_message=False, bypass_approval=False):
        conversation.ensure_one()
        memory_state = memory_state or self._get_memory_state_for_route(conversation, route)
        if not memory_state:
            raise UserError(_("I could not find a reusable AI result set for this reminder action."))
        groups, warnings = self.env["ob.ai.memory.service"].get_actionable_result_groups(
            memory_state,
            user=conversation.user_id,
            company=conversation.company_id,
        )
        if not groups:
            raise UserError(_("The last AI result set does not contain any still-accessible records that can receive reminders."))
        created_reminders = self.env["ob.ai.reminder"]
        approvals = self.env["ob.ai.approval"]
        existing_count = 0
        due_datetime = route.get("due_datetime") or fields.Datetime.now()
        combined_context = self.env["ob.ai.access.service"]._empty_context()
        for group in groups:
            group_policy = self.env["ob.ai.access.service"].get_model_access_policy(group["allowed_model"], user=conversation.user_id)
            combined_context = self._merge_records_context_bundle(
                combined_context,
                group["records"],
                group["allowed_model"],
                source="memory_action_result_set",
                access_policy=group_policy,
            )
            for target_record in group["records"]:
                assigned_user = self._get_assigned_user(route, target_record)
                text = self._build_memory_reminder_text(target_record, prompt, memory_state, reference_map=group["reference_map"])
                idempotency_key = self._make_idempotency_key("reminder", target_record, text, due_datetime)
                existing = self.env["ob.ai.reminder"].search(
                    [
                        ("company_id", "=", conversation.company_id.id),
                        ("idempotency_key", "=", idempotency_key),
                    ],
                    limit=1,
                )
                if existing:
                    existing_count += 1
                    continue
                values = {
                    "name": text[:80],
                    "company_id": conversation.company_id.id,
                    "requesting_user_id": self.env.user.id,
                    "assigned_user_id": assigned_user.id if assigned_user else False,
                    "related_record_ref": "%s,%s" % (target_record._name, target_record.id),
                    "reminder_text": text,
                    "due_datetime": due_datetime,
                    "status": "pending",
                    "source_conversation_id": conversation.id,
                    "source_message_id": source_message.id if source_message else False,
                    "created_by_ai": True,
                    "idempotency_key": idempotency_key,
                }
                requires_approval = route.get("requires_approval") or bool(group_policy.get("require_human_approval"))
                approval_scope = group_policy.get("sensitivity_level") or route.get("approval_scope") or "general"
                if requires_approval and not bypass_approval:
                    approvals |= self._create_approval(
                        conversation,
                        {"approval_scope": approval_scope},
                        "reminder",
                        _("Create reminder: %s", text),
                        values,
                        target_record=target_record,
                        idempotency_key=idempotency_key,
                    )
                    continue
                created_reminders |= self.env["ob.ai.reminder"].create(values)
        acted_record_count = sum(len(group["records"]) for group in groups)
        summary_lines = []
        if created_reminders:
            summary_lines.append(
                _("Created %(count)s reminders from the last AI result set across %(records)s visible records.", count=len(created_reminders), records=acted_record_count)
            )
        if approvals:
            summary_lines.append(
                _("Prepared %(count)s reminders for approval from the last AI result set.", count=len(approvals))
            )
        if existing_count:
            summary_lines.append(_("%s matching reminders already existed and were not duplicated.", existing_count))
        if warnings:
            summary_lines.extend("- %s" % warning for warning in warnings)
        if not summary_lines:
            summary_lines.append(_("No new reminders were created from the last AI result set."))
        action_performed = "reminder_existing"
        if created_reminders and approvals:
            action_performed = "reminders_created + reminders_pending_approval"
        elif created_reminders:
            action_performed = "reminders_created"
        elif approvals:
            action_performed = "reminders_pending_approval"
        return {
            "action_performed": action_performed,
            "summary_text": "\n\n".join(summary_lines),
            "record": created_reminders[:1],
            "records": created_reminders,
            "approvals": approvals,
            "approval": approvals[:1],
            "existing_count": existing_count,
            "context_bundle": combined_context,
            "memory_state": memory_state,
            "related_record_refs": memory_state.result_record_refs or [],
        }

    def post_chatter_from_memory_state(self, conversation, route, body, memory_state=False, bypass_approval=False):
        conversation.ensure_one()
        memory_state = memory_state or self._get_memory_state_for_route(conversation, route)
        if not memory_state:
            raise UserError(_("I could not find a reusable AI result set for this chatter action."))
        groups, warnings = self.env["ob.ai.memory.service"].get_actionable_result_groups(
            memory_state,
            user=conversation.user_id,
            company=conversation.company_id,
        )
        if not groups:
            raise UserError(_("The last AI result set does not contain any still-accessible records that can receive chatter notes."))
        posted_messages = self.env["mail.message"]
        approvals = self.env["ob.ai.approval"]
        existing_count = 0
        combined_context = self.env["ob.ai.access.service"]._empty_context()
        for group in groups:
            group_policy = self.env["ob.ai.access.service"].get_model_access_policy(group["allowed_model"], user=conversation.user_id)
            combined_context = self._merge_records_context_bundle(
                combined_context,
                group["records"],
                group["allowed_model"],
                source="memory_action_result_set",
                access_policy=group_policy,
            )
            for target_record in group["records"]:
                if not hasattr(target_record, "message_post"):
                    warnings.append(_("Model %s does not support chatter posting.") % target_record._name)
                    continue
                clean_body = self._build_memory_chatter_body(target_record, body, memory_state, reference_map=group["reference_map"])
                idempotency_key = self._make_idempotency_key("chatter", target_record, clean_body, fields.Date.context_today(self))
                existing = self.env["mail.message"].search([
                    ("model", "=", target_record._name),
                    ("res_id", "=", target_record.id),
                    ("body", "ilike", idempotency_key),
                ], limit=1)
                if existing:
                    existing_count += 1
                    continue
                payload = {
                    "body": "%s\n\nAI Idempotency: %s" % (clean_body, idempotency_key),
                }
                requires_approval = route.get("requires_approval") or bool(group_policy.get("require_human_approval"))
                approval_scope = group_policy.get("sensitivity_level") or route.get("approval_scope") or "general"
                if requires_approval and not bypass_approval:
                    approvals |= self._create_approval(
                        conversation,
                        {"approval_scope": approval_scope},
                        "chatter",
                        _("Post chatter note on %s", target_record.display_name),
                        payload,
                        target_record=target_record,
                        idempotency_key=idempotency_key,
                    )
                    continue
                posted_messages |= target_record.message_post(body=payload["body"], message_type="comment", subtype_xmlid="mail.mt_note")
        acted_record_count = sum(len(group["records"]) for group in groups)
        summary_lines = []
        if posted_messages:
            summary_lines.append(
                _("Posted %(count)s chatter notes from the last AI result set across %(records)s visible records.", count=len(posted_messages), records=acted_record_count)
            )
        if approvals:
            summary_lines.append(
                _("Prepared %(count)s chatter notes for approval from the last AI result set.", count=len(approvals))
            )
        if existing_count:
            summary_lines.append(_("%s matching chatter notes already existed and were not duplicated.", existing_count))
        if warnings:
            summary_lines.extend("- %s" % warning for warning in warnings)
        if not summary_lines:
            summary_lines.append(_("No new chatter notes were created from the last AI result set."))
        action_performed = "chatter_existing"
        if posted_messages and approvals:
            action_performed = "chatter_posted + chatter_pending_approval"
        elif posted_messages:
            action_performed = "chatter_posted"
        elif approvals:
            action_performed = "chatter_pending_approval"
        return {
            "action_performed": action_performed,
            "summary_text": "\n\n".join(summary_lines),
            "record": posted_messages[:1],
            "records": posted_messages,
            "approvals": approvals,
            "approval": approvals[:1],
            "existing_count": existing_count,
            "context_bundle": combined_context,
            "memory_state": memory_state,
            "related_record_refs": memory_state.result_record_refs or [],
        }

    def apply_approved_action(self, approval):
        approval.ensure_one()
        payload = approval.payload_json or {}
        target_record = approval.related_record_ref
        if approval.action_type == "reminder":
            reminder = self.env["ob.ai.reminder"].create(payload)
            return {"summary_text": _("Approved reminder %(name)s was created.", name=reminder.display_name), "record": reminder}
        if approval.action_type == "activity":
            activity = self.env["mail.activity"].create(payload)
            return {"summary_text": _("Approved activity was created."), "record": activity}
        if approval.action_type == "chatter":
            if not target_record:
                raise UserError(_("The approved chatter action has no target record."))
            message = target_record.message_post(body=payload.get("body"), message_type="comment", subtype_xmlid="mail.mt_note")
            return {"summary_text": _("Approved chatter note was posted."), "record": message}
        if approval.action_type == "validation":
            results = self.env["ob.ai.validation.result"].browse(payload.get("validation_result_ids", []))
            results.write({"review_status": "applied", "reviewer_id": self.env.user.id})
            return {"summary_text": _("Approved validation results were marked as applied."), "record": results}
        return {"summary_text": _("The approved action did not require an extra apply step.")}

    def _notify_due_reminder(self, reminder):
        reminder.ensure_one()
        if reminder.notification_sent or reminder.status in ("done", "cancelled"):
            return reminder
        reminder.message_post(body=_("Reminder is now due: %s", reminder.reminder_text))
        if reminder.related_record_ref and self._get_bool_param("ob_ai_assistant.allow_activity_creation", False) and not reminder.activity_id:
            assigned_user = reminder.assigned_user_id or reminder.requesting_user_id or self.env.user
            idempotency_key = reminder.idempotency_key or self._make_idempotency_key(
                "reminder-activity",
                reminder.related_record_ref,
                reminder.reminder_text,
                reminder.due_datetime,
            )
            existing = self._find_existing_activity(reminder.related_record_ref, assigned_user, idempotency_key)
            if existing:
                reminder.activity_id = existing.id
            else:
                activity = self.env["mail.activity"].create(
                    self._prepare_activity_values(
                        reminder.related_record_ref,
                        assigned_user,
                        reminder.due_datetime,
                        idempotency_key,
                        activity_payload={
                            "summary": self._clean_action_text(reminder.reminder_text)[:96],
                            "note": self._clean_action_text(reminder.reminder_text),
                            "source_text": self._clean_action_text(reminder.reminder_text),
                        },
                    )
                )
                reminder.activity_id = activity.id
        reminder.write({
            "status": "due",
            "notification_sent": True,
        })
        return reminder

    def _create_approval(self, conversation, route, action_type, summary, payload, target_record=False, idempotency_key=False):
        if idempotency_key:
            existing = self.env["ob.ai.approval"].search([
                ("company_id", "=", conversation.company_id.id),
                ("action_type", "=", action_type),
                ("idempotency_key", "=", idempotency_key),
                ("review_status", "in", ["pending_review", "approved", "applied"]),
            ], limit=1)
            if existing:
                return existing
        return self.env["ob.ai.approval"].create({
            "name": _("AI Approval: %s", action_type.title()),
            "company_id": conversation.company_id.id,
            "requested_by_id": self.env.user.id,
            "source_conversation_id": conversation.id,
            "related_record_ref": "%s,%s" % (target_record._name, target_record.id) if target_record else False,
            "action_type": action_type,
            "review_status": "pending_review",
            "approval_scope": route.get("approval_scope") or "general",
            "action_summary": summary,
            "payload_json": payload,
            "idempotency_key": idempotency_key,
        })

    def _ensure_model_action_allowed(self, allowed_model, action_type):
        global_flags = {
            "reminder": self._get_bool_param("ob_ai_assistant.allow_reminder_creation", False),
            "activity": self._get_bool_param("ob_ai_assistant.allow_activity_creation", False),
            "chatter": self._get_bool_param("ob_ai_assistant.allow_chatter_posting", False),
        }
        if not global_flags.get(action_type):
            raise UserError(_("The AI assistant is not allowed to create %s actions in Settings.") % action_type)
        if not allowed_model:
            return
        self.env["ob.ai.access.service"].ensure_model_capability(allowed_model, action_type)

    def _prepare_activity_values(self, target_record, assigned_user, due_datetime, idempotency_key, activity_payload=False):
        activity_type = self.env.ref("mail.mail_activity_data_todo", raise_if_not_found=False)
        model_id = self.env["ir.model"]._get_id(target_record._name)
        activity_payload = activity_payload or {}
        summary = self._clean_action_text(activity_payload.get("summary") or activity_payload.get("source_text"))
        note = activity_payload.get("note") or self._clean_action_text(activity_payload.get("source_text"))
        deadline_date = activity_payload.get("deadline_date")
        if not deadline_date:
            deadline_date = fields.Datetime.to_datetime(due_datetime).date()
        return {
            "activity_type_id": activity_type.id if activity_type else False,
            "res_model_id": model_id,
            "res_id": target_record.id,
            "summary": summary[:96],
            "note": note,
            "user_id": assigned_user.id if assigned_user else self.env.user.id,
            "date_deadline": deadline_date,
            "ob_ai_generated": True,
            "ob_ai_idempotency_key": idempotency_key,
        }

    def _find_existing_activity(self, target_record, assigned_user, idempotency_key):
        return self.env["mail.activity"].search([
            ("res_model", "=", target_record._name),
            ("res_id", "=", target_record.id),
            ("user_id", "=", assigned_user.id if assigned_user else self.env.user.id),
            "|",
            ("ob_ai_idempotency_key", "=", idempotency_key),
            ("note", "ilike", idempotency_key),
        ], limit=1)

    def _clean_action_text(self, text):
        return (text or "").strip().rstrip(".")

    def _build_activity_payload(self, route, target_record, prompt, due_datetime, memory_state=False, reference_map=False):
        clean_prompt = self._clean_action_text(prompt)
        if route.get("intent_code") == "delivery_worklist" and target_record and target_record._name == "stock.picking":
            return self._build_delivery_activity_payload(target_record, due_datetime)
        if memory_state:
            return self._build_memory_activity_payload(target_record, clean_prompt, due_datetime, memory_state, reference_map=reference_map)
        return {
            "summary": clean_prompt[:96],
            "note": clean_prompt,
            "source_text": clean_prompt,
            "idempotency_text": clean_prompt,
            "idempotency_marker": due_datetime,
        }

    def _build_memory_activity_payload(self, target_record, clean_prompt, due_datetime, memory_state, reference_map=False):
        record_ref = "%s,%s" % (target_record._name, target_record.id)
        reference_data = (reference_map or {}).get(record_ref, {})
        display_name = reference_data.get("display_name") or target_record.display_name
        due_date = fields.Datetime.to_datetime(due_datetime).date()
        requested_action = clean_prompt or _("Review this record")
        summary = _("Follow up on %(name)s", name=display_name)
        if "today" in requested_action.lower():
            summary = _("Follow up on %(name)s today", name=display_name)
        note_items = [
            (_("Record"), display_name),
            (_("Model"), target_record._description or target_record._name),
            (_("Requested action"), requested_action),
        ]
        if reference_data.get("summary_line"):
            note_items.append((_("AI result context"), reference_data["summary_line"]))
        if memory_state.last_prompt:
            note_items.append((_("Source request"), memory_state.last_prompt))
        return {
            "summary": summary,
            "note": self._build_activity_note_html(
                _("This follow-up was created from the latest AI result set."),
                note_items,
            ),
            "source_text": requested_action,
            "idempotency_text": "%s|%s" % (record_ref, requested_action),
            "idempotency_marker": due_date,
            "deadline_date": due_date,
        }

    def _build_memory_reminder_text(self, target_record, prompt, memory_state, reference_map=False):
        record_ref = "%s,%s" % (target_record._name, target_record.id)
        reference_data = (reference_map or {}).get(record_ref, {})
        display_name = reference_data.get("display_name") or target_record.display_name
        clean_prompt = self._clean_action_text(prompt)
        detail = _("Review %(record)s based on the last AI result set.", record=display_name)
        if clean_prompt:
            detail = _("%(prompt)s for %(record)s. Requested from the last AI result set.", prompt=clean_prompt, record=display_name)
        if reference_data.get("summary_line"):
            detail += "\n" + _("AI result context: %s", reference_data["summary_line"])
        if memory_state.last_prompt:
            detail += "\n" + _("Source request: %s", memory_state.last_prompt)
        return detail

    def _build_memory_chatter_body(self, target_record, body, memory_state, reference_map=False):
        record_ref = "%s,%s" % (target_record._name, target_record.id)
        reference_data = (reference_map or {}).get(record_ref, {})
        clean_body = self._clean_action_text(body)
        intro = clean_body or _("Follow-up from the last AI result set")
        note_items = [
            (_("Record"), reference_data.get("display_name") or target_record.display_name),
            (_("Requested note"), intro),
        ]
        if reference_data.get("summary_line"):
            note_items.append((_("AI result context"), reference_data["summary_line"]))
        if memory_state.last_prompt:
            note_items.append((_("Source request"), memory_state.last_prompt))
        return str(self._build_activity_note_html(
            _("This note was posted from the latest AI result set."),
            note_items,
        ))

    def _build_delivery_activity_payload(self, target_record, due_datetime):
        due_date = fields.Datetime.to_datetime(due_datetime).date()
        note_items = [
            (_("Delivery order"), target_record.display_name),
            (_("Current status"), self._get_selection_label(target_record, "state") or target_record.state or _("Unknown")),
        ]
        if "scheduled_date" in target_record._fields and target_record.scheduled_date:
            note_items.append((_("Scheduled date"), fields.Datetime.to_string(target_record.scheduled_date)))
        if "partner_id" in target_record._fields and target_record.partner_id:
            note_items.append((_("Customer"), target_record.partner_id.display_name))
        if "origin" in target_record._fields and target_record.origin:
            note_items.append((_("Source document"), target_record.origin))
        summary = _("Process delivery %(name)s today", name=target_record.display_name)
        return {
            "summary": summary,
            "note": self._build_activity_note_html(
                _("You need to process this delivery today."),
                note_items,
            ),
            "source_text": summary,
            "idempotency_text": summary,
            "idempotency_marker": due_date,
            "deadline_date": fields.Date.context_today(self),
        }

    def _get_assigned_user(self, route, target_record):
        assigned_user = route.get("assigned_user")
        if assigned_user:
            return assigned_user
        for field_name in ("user_id", "activity_user_id", "responsible_id"):
            if target_record and field_name in target_record._fields and target_record[field_name]:
                candidate = target_record[field_name]
                if candidate._name == "res.users":
                    return candidate
                if "user_id" in candidate._fields and candidate.user_id:
                    return candidate.user_id
        relational_candidates = (
            ("sale_id", "user_id"),
            ("order_id", "user_id"),
            ("picking_id", "user_id"),
        )
        for relation_field, user_field in relational_candidates:
            if target_record and relation_field in target_record._fields and target_record[relation_field]:
                related = target_record[relation_field]
                if user_field in related._fields and related[user_field]:
                    return related[user_field]
        fallback_user = self._get_fallback_assigned_user()
        return fallback_user or self.env.user

    def _get_fallback_assigned_user(self):
        params = self.env["ir.config_parameter"].sudo()
        service_user_id = int(params.get_param("ob_ai_assistant.service_user_id", default="0") or 0)
        if service_user_id:
            service_user = self.env["res.users"].browse(service_user_id).exists()
            if service_user:
                return service_user
        admin_candidate = self.env["res.users"].search([("name", "ilike", "Mitchell Admin")], limit=1)
        if admin_candidate:
            return admin_candidate
        login_admin = self.env["res.users"].search([("login", "=", "admin")], limit=1)
        if login_admin:
            return login_admin
        return False

    def _get_selection_label(self, record, field_name):
        field = record._fields.get(field_name)
        if not field or not field.selection:
            return False
        selection = field.selection(record.env) if callable(field.selection) else field.selection
        return dict(selection).get(record[field_name], record[field_name])

    def _build_activity_note_html(self, intro_text, detail_items):
        list_items = []
        for label, value in detail_items:
            if not value:
                continue
            list_items.append(
                Markup("<li><strong>%s:</strong> %s</li>") % (escape(label), escape(value))
            )
        note = Markup("<p>%s</p>") % escape(intro_text)
        if list_items:
            note += Markup("<ul>%s</ul>") % Markup("").join(list_items)
        return note

    def _make_idempotency_key(self, action_type, target_record, text, date_marker):
        record_ref = "%s,%s" % (target_record._name, target_record.id) if target_record else "no-record"
        payload = "%s|%s|%s|%s" % (action_type, record_ref, text or "", date_marker or "")
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]

    def _get_memory_state_for_route(self, conversation, route):
        memory_service = self.env["ob.ai.memory.service"]
        memory_state_id = route.get("generic_memory_state_id")
        memory_state = self.env["ob.ai.memory.state"].browse(memory_state_id).exists() if memory_state_id else self.env["ob.ai.memory.state"]
        if not memory_state:
            memory_state = memory_service.get_valid_memory_state(conversation, touch=True)
        elif memory_state.status == "valid":
            memory_state.sudo().write({"last_used_at": fields.Datetime.now()})
        else:
            memory_state = self.env["ob.ai.memory.state"]
        return memory_state

    def _build_records_context_bundle(self, records, allowed_model, source, access_policy=False):
        records = records.exists()
        if not records:
            return self.env["ob.ai.access.service"]._empty_context()
        access_service = self.env["ob.ai.access.service"]
        access_policy = access_policy or access_service.get_model_access_policy(allowed_model)
        return access_service._build_context_from_records(records, allowed_model, source=source, access_policy=access_policy)

    def _merge_records_context_bundle(self, target_bundle, records, allowed_model, source, access_policy=False):
        return self._merge_context_bundle(
            target_bundle,
            self._build_records_context_bundle(records, allowed_model, source=source, access_policy=access_policy),
        )

    def _merge_context_bundle(self, target, source):
        if not source:
            return target
        for model_name in source.get("accessed_models", []):
            if model_name not in target["accessed_models"]:
                target["accessed_models"].append(model_name)
        for model_name, record_ids in (source.get("accessed_record_ids") or {}).items():
            existing_ids = target["accessed_record_ids"].setdefault(model_name, [])
            for record_id in record_ids:
                if record_id not in existing_ids:
                    existing_ids.append(record_id)
        for model_name, field_names in (source.get("accessed_fields") or {}).items():
            existing_fields = target["accessed_fields"].setdefault(model_name, [])
            for field_name in field_names:
                if field_name not in existing_fields:
                    existing_fields.append(field_name)
        for model_name, blocked_fields in (source.get("blocked_fields") or {}).items():
            existing_blocked = target["blocked_fields"].setdefault(model_name, [])
            for field_name in blocked_fields:
                if field_name not in existing_blocked:
                    existing_blocked.append(field_name)
        target["records"].extend(source.get("records") or [])
        target["hidden_record_count"] += source.get("hidden_record_count") or 0
        target["source"] = source.get("source") or target.get("source") or "action_result_set"
        return target

    def _memory_or_default_activity_summary(self, route, created_count=0, approvals_count=0, existing_count=0, memory_state=False):
        if memory_state:
            lines = []
            if created_count:
                lines.append(_("Created %(count)s follow-up activities from the last AI result set.", count=created_count))
            if approvals_count:
                lines.append(_("Prepared %(count)s follow-up activities for approval from the last AI result set.", count=approvals_count))
            if existing_count:
                lines.append(_("%s matching activities already existed and were not duplicated.", existing_count))
            return "\n\n".join(lines) if lines else _("No new follow-up activities were created from the last AI result set.")
        if approvals_count and not created_count:
            return _("Prepared %(count)s follow-up activities for approval.", count=approvals_count)
        if created_count:
            summary_text = _(
                "Created %(count)s follow-up activities for the delivery worklist. Assigned users come from each record when available, otherwise the request owner was used.",
                count=created_count,
            )
            if existing_count:
                summary_text += "\n\n" + _("%s matching activities already existed and were not duplicated.", existing_count)
            return summary_text
        if existing_count:
            return _("Matching follow-up activities already existed for all selected records.")
        return _("No new follow-up activities were created.")

    def _get_bool_param(self, key, default=False):
        value = self.env["ir.config_parameter"].sudo().get_param(key, default=str(default))
        return value == "True"
