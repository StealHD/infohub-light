"""Current source privacy is rechecked at each model and delivery boundary."""

def eligible(item):
    return item.get('analysis_mode') != 'personal_only' and not item.get('truncated') and bool(item.get('text'))



def apply_current_privacy(store, user_id, inputs):
    subscriptions = store.list_user_subscriptions(user_id)
    private_sources = {row['source_id'] for row in subscriptions if row['analysis_mode'] == 'personal_only'}
    for item in inputs:
        if private_sources.intersection(item.get('source_ids', [])):
            item['analysis_mode'] = 'personal_only'
    return inputs
