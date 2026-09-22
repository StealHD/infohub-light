"""Project safe ActorOps result failures into the ordinary Job error fields."""
import re


def job_failure_fields(job, status, result):
    if status != 'failed' or job.get('job_type') not in {
        'actorops_v2_maintenance', 'actorops_v2_repair',
        'actorops_v2_replacement', 'actorops_v2_discovery',
    }:
        return {}
    code = result.get('error_code')
    if not isinstance(code, str) or not re.fullmatch(r'(?:actorops|apify)_[a-z0-9_]{1,90}', code):
        code = 'actorops_job_failed'
    messages = {
        'blocked': '自动修复受阻，将按记录的重试时间重新检查。',
        'recovery_required': '执行结果尚待确认，正在等待自动对账。',
    }
    return {'error_code': code,
            'error_message': messages.get(result.get('status'), 'ActorOps 执行失败，请查看具体错误码。')}
