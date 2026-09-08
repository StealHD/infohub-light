"""Stable reminder mutation audit names; never log rules, evidence or credentials."""
MUTATION_OPERATION_ROUTES: dict[tuple[str, str], tuple[str, str]] = {
    ('POST', '/api/me/information-automations/models/refresh'): ('agent', 'information_models_refresh'),
    ('POST', '/api/connector/information-automations/capabilities'): ('agent', 'information_capabilities'),
    ('POST', '/api/me/information-automations'): ('agent', 'information_draft_create'),
    ('PUT', '/api/me/information-automations/{rule_id}'): ('agent', 'information_draft_update'),
    ('POST', '/api/me/information-automations/{rule_id}/transition'): ('agent', 'information_rule_transition'),
    ('POST', '/api/me/information-automations/{rule_id}/test'): ('agent', 'information_rule_test'),
    ('POST', '/api/connector/information-automations/claim'): ('agent', 'information_claim'),
    ('POST', '/api/connector/information-automations/claims/{claim_id}/result'): ('agent', 'information_result'),
}


def machine_audit(request, store, token):
    from ..services.information_automations.connector_auth import authenticate
    principal = authenticate(store, token)
    user = store.get_user(principal['user_id'])
    request.state.operation_workspace_id = user['workspace_id']
    request.state.operation_actor_user_id = user['id']
    request.state.operation_subject_user_id = user['id']
