"""Bounded evidence projections from existing user-owned content storage."""


def evidence_input(stored, remaining):
    item = stored.get('item') or {}
    title = str(item.get('title') or '')[:500]
    body = str(stored.get('body_text') or item.get('content') or item.get('summary') or '')
    full = title + '\n' + body
    text = full[:max(0, remaining)]
    sources = set(item.get('source_ids') or [])
    if stored.get('source_id'):
        sources.add(stored['source_id'])
    return {'article_id': stored['article_id'], 'title': title, 'text': text,
            'source_ids': sorted(sources), 'truncated': len(full) > len(text) or bool(stored.get('body_truncated')),
            'analysis_mode': item.get('analysis_mode', 'full'),
            'source_name': str(item.get('source_name') or ''), 'published_at': str(item.get('published_at') or ''),
            'url': str(item.get('url') or '')}


def original_url(value):
    from urllib.parse import urlsplit
    try:
        parsed = urlsplit(value or '')
        return value if parsed.scheme in {'http', 'https'} and parsed.hostname and not parsed.username and not parsed.password else ''
    except (ValueError, TypeError):
        return ''
