"""Bounded, explicitly supplied text for an isolated automation preview."""
import hashlib
import json

from .rules import RuleError


def prepare(value):
    if not isinstance(value, dict):
        raise RuleError('invalid_test_text', '请输入自定义测试文本。', 400)
    text = str(value.get('text') or '').strip()
    title = str(value.get('title') or '自定义测试文本').strip()
    if not text:
        raise RuleError('invalid_test_text', '请输入自定义测试文本。', 400)
    if len(title) > 500 or len(text) > 24000:
        raise RuleError('invalid_test_text', '自定义测试文本过长。', 400)
    digest = hashlib.sha256(json.dumps([title, text], ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
    return {
        'article_id': 'custom-test:' + digest[:32],
        'title': title,
        'text': title + '\n' + text,
        'source_ids': [],
        'truncated': False,
        'analysis_mode': 'full',
        'source_name': '自定义测试文本',
        'published_at': '',
        'url': '',
    }
