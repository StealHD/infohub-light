"""Classify upstream failures without forwarding their text or management details."""
import re

MESSAGES = {
    'MODEL_PARAMETER_UNSUPPORTED': '参数不兼容，请重新选择模型和推理强度。内容已保留。',
    'PERSONAL_TOOLS_UNAVAILABLE': '个人数据工具未就绪，请管理员修复 Agent 接入。',
    'MODEL_AUTH_FAILED': '模型认证失败，请管理员检查该模型的授权。',
    'MODEL_QUOTA_LIMITED': '模型额度受限，请稍后手动重试或检查额度。',
    'MODEL_CALL_TIMEOUT': '调用超时，结果可能尚未确认，请先检查运行状态。',
    'RELAY_REQUEST_FAILED': 'OpenClaw 未能完成请求，请检查运行状态后手动重试。',
}


def safe_error(value):
    value = value if isinstance(value, dict) else {'message': value}
    raw = str(value.get('message', ''))[:8192].lower()
    code = str(value.get('code', '')).upper()
    if code not in MESSAGES:
        if 'thinking level' in raw and ('not supported' in raw or 'unsupported' in raw):
            code = 'MODEL_PARAMETER_UNSUPPORTED'
        elif 'no callable tools' in raw or ('mcp' in raw and ('initialize' in raw or 'timed out' in raw)):
            code = 'PERSONAL_TOOLS_UNAVAILABLE'
        elif any(term in raw for term in ('no api key found', 'invalid api key', 'incorrect api key', 'authentication failed')):
            code = 'MODEL_AUTH_FAILED'
        elif any(term in raw for term in ('rate limit', 'rate_limit', 'insufficient_quota', 'quota exceeded')):
            code = 'MODEL_QUOTA_LIMITED'
        elif 'timed out' in raw or 'timeout' in raw:
            code = 'MODEL_CALL_TIMEOUT'
        else:
            code = 'RELAY_REQUEST_FAILED'
    return {'code': code, 'message': MESSAGES[code]}


def safe_chat_failure(frame):
    payload = frame.get('payload', {})
    if frame.get('event') != 'chat' or payload.get('state') != 'error':
        return frame
    error = safe_error(payload.get('error', payload.get('errorMessage', '')))
    safe = {'state': 'error', 'errorCode': error['code'], 'errorMessage': error['message']}
    for field in ('sessionKey', 'runId'):
        value = payload.get(field)
        if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9._:-]{1,512}', value):
            safe[field] = value
    return {'type': 'event', 'event': 'chat', 'payload': safe}
