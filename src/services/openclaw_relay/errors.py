"""Classify upstream failures without forwarding their text or management details."""
import re

MESSAGES = {
    'MODEL_PARAMETER_UNSUPPORTED': '参数不兼容，请重新选择模型和推理强度。内容已保留。',
    'PERSONAL_TOOLS_UNAVAILABLE': '个人数据工具未就绪，请管理员修复 Agent 接入。',
    'MODEL_AUTH_FAILED': '模型认证失败，请管理员检查该模型的授权。',
    'MODEL_QUOTA_LIMITED': '模型额度受限，请稍后手动重试或检查额度。',
    'MODEL_CALL_TIMEOUT': '调用超时，结果可能尚未确认，请先检查运行状态。',
    'MODEL_UPSTREAM_UNAVAILABLE': '模型服务暂不可用，请稍后手动重试。',
    'MODEL_CONTEXT_LIMIT': '对话超出模型上下文限制，请新建对话或减少输入。',
    'MODEL_REFUSED': '模型未能处理本次请求，请调整内容后重试。',
    'RELAY_REQUEST_FAILED': 'OpenClaw 未能完成请求，请检查运行状态后手动重试。',
}


def safe_error(value):
    value = value if isinstance(value, dict) else {'message': value}
    raw = str(value.get('message', value.get('errorMessage', '')))[:8192].lower()
    code = str(value.get('code', '')).upper()
    kinds = {'rate_limit': 'MODEL_QUOTA_LIMITED', 'timeout': 'MODEL_CALL_TIMEOUT',
             'context_length': 'MODEL_CONTEXT_LIMIT', 'refusal': 'MODEL_REFUSED'}
    code = kinds.get(str(value.get('errorKind', '')), code)
    if code not in MESSAGES:
        if 'thinking level' in raw and ('not supported' in raw or 'unsupported' in raw):
            code = 'MODEL_PARAMETER_UNSUPPORTED'
        elif 'no callable tools' in raw or ('mcp' in raw and ('initialize' in raw or 'timed out' in raw)):
            code = 'PERSONAL_TOOLS_UNAVAILABLE'
        elif any(term in raw for term in ('no api key found', 'invalid api key', 'incorrect api key', 'authentication failed')) or re.search(r'\b(?:http|status|error)\s*\(?401\b', raw):
            code = 'MODEL_AUTH_FAILED'
        elif any(term in raw for term in ('rate limit', 'rate_limit', 'insufficient_quota', 'quota exceeded',
                                          'resource_exhausted', 'exceeded your current quota')) or re.search(r'\b(?:http|status|error)\s*\(?429\b', raw):
            code = 'MODEL_QUOTA_LIMITED'
        elif 'timed out' in raw or 'timeout' in raw:
            code = 'MODEL_CALL_TIMEOUT'
        elif re.search(r'\b(?:http|status|error)\s*\(?50[234]\b', raw) or 'service unavailable' in raw:
            code = 'MODEL_UPSTREAM_UNAVAILABLE'
        else:
            code = 'RELAY_REQUEST_FAILED'
    return {'code': code, 'message': MESSAGES[code]}


def safe_chat_failure(frame):
    payload = frame.get('payload', {})
    if frame.get('event') != 'chat' or payload.get('state') != 'error':
        return frame
    nested = payload.get('error')
    error_input = dict(nested) if isinstance(nested, dict) else {'message': nested or payload.get('errorMessage', '')}
    error_input['errorKind'] = payload.get('errorKind', error_input.get('errorKind'))
    error_input['code'] = payload.get('errorCode', error_input.get('code', ''))
    error = safe_error(error_input)
    safe = {'state': 'error', 'errorCode': error['code'], 'errorMessage': error['message']}
    for field in ('sessionKey', 'runId'):
        value = payload.get(field)
        if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9._:-]{1,512}', value):
            safe[field] = value
    seq = payload.get('seq')
    if type(seq) is int and 0 <= seq <= 9007199254740991:
        safe['seq'] = seq
    message = payload.get('message')
    if isinstance(message, dict):
        metadata = {'role': 'assistant', 'stopReason': 'error'}
        for field in ('id', 'provider', 'model'):
            value = message.get(field)
            if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._/-]{0,179}', value):
                metadata[field] = value
        if len(metadata) > 2:
            safe['message'] = metadata
    return {'type': 'event', 'event': 'chat', 'payload': safe}


def safe_history_failures(payload):
    """Keep useful reply content, project error metadata before it reaches browsers."""
    messages = payload.get('messages')
    if not isinstance(messages, list):
        return payload
    result = []
    for message in messages:
        if isinstance(message, dict) and message.get('role') == 'assistant' and message.get('stopReason') == 'error':
            error = safe_error({'message': message.get('errorMessage', ''), 'code': message.get('errorCode', ''),
                                'errorKind': message.get('errorKind')})
            message = {k: v for k, v in message.items() if k not in {'errorMessage', 'errorDetail', 'errorBody', 'errorType', 'errorKind', 'diagnostics', 'errorCode'}}
            if error['code'] != 'RELAY_REQUEST_FAILED':
                message['errorCode'] = error['code']
        result.append(message)
    return {**payload, 'messages': result}
