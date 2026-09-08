"""Independently authorized personal reminder drafts; never enable or send."""
from typing import Any
from ..services.agent_change_proposal import AgentProposalError
from ..services.information_automations.rules import InformationRules, RuleConfig, RuleError
from ..services.notification_targets import NotificationTargetService
from ..services.notification_email_transport import WorkspaceEmailTransportService
from ..services.workspace_telegram_transport import WorkspaceTelegramTransportService
from ..storage.agent_delegation_scopes import INFORMATION_READ_SCOPE, INFORMATION_DRAFT_SCOPE
from .remote_tool_annotations import READ_ANNOTATIONS, PREPARE_ANNOTATIONS

TOOL_SCOPES = {'list_my_information_automations': INFORMATION_READ_SCOPE,
               'prepare_information_automation': INFORMATION_DRAFT_SCOPE}


class RemoteInformationService:
    def __init__(self, store, rules=None):
        self.store = store
        self.rules = rules or InformationRules(store, NotificationTargetService(store, data_dir=store.data_dir,
            email_transport=WorkspaceEmailTransportService(store, data_dir=store.data_dir),
            telegram_transport=WorkspaceTelegramTransportService(store, data_dir=store.data_dir)))

    def authorize(self, actor, scope):
        principal = self.store.get_active_agent_delegation_principal(actor.delegation_id)
        if not principal or principal['user_id'] != actor.user_id or principal['workspace_id'] != actor.workspace_id:
            raise AgentProposalError('unauthorized', 'Delegation is no longer authorized.', status_code=401)
        if scope not in principal['scopes']:
            raise AgentProposalError('reminder_scope_required', 'Explicit reminder delegation is required.', status_code=403)
        return principal['user_id']

    def list_rules(self, *, actor, offset=0):
        user_id = self.authorize(actor, INFORMATION_READ_SCOPE)
        try:
            return self.rules.list(user_id, offset=max(0, offset))
        except RuleError as exc:
            raise AgentProposalError(exc.code, str(exc), status_code=exc.status) from exc

    def prepare(self, *, actor, config):
        user_id = self.authorize(actor, INFORMATION_DRAFT_SCOPE)
        try:
            draft = self.rules.save(user_id, config)
        except RuleError as exc:
            raise AgentProposalError(exc.code, str(exc), status_code=exc.status) from exc
        return {'draft_ref': draft['id'], 'version': draft['version'],
                'confirmation_card': '[[information-automation:' + draft['id'] + ']]',
                'state': 'draft', 'message': '请展示确认卡，由用户编辑、测试并确认启用。当前不会发送通知。'}


def register_information_tools(server, context):
    service = context.information_service
    if service is None:
        return

    @server.tool(annotations=READ_ANNOTATIONS, structured_output=True)
    def list_my_information_automations(offset: int = 0) -> dict[str, Any]:
        """Read only the authenticated user's reminder rules, fifty per page."""
        return context.calls.run_tool('list_my_information_automations', service.list_rules,
                                      actor_operation=True, offset=offset)

    @server.tool(annotations=PREPARE_ANNOTATIONS, structured_output=True)
    def prepare_information_automation(config: RuleConfig) -> dict[str, Any]:
        """Save a v2 draft: one complete requirement, sources, trigger and optional explicit model.
        Keywords, meaning and exclusions belong together in requirement. Show confirmation_card verbatim;
        only the user can choose an authorized model and enable the draft in the web UI.
        """
        return context.calls.run_tool('prepare_information_automation', service.prepare,
                                      actor_operation=True, config=config)
