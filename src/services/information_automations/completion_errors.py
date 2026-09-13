"""Project completion failures to bounded codes without retaining upstream text."""
import httpx


def confirmed_gateway_tool_failure(error):
    """Whether Gateway conclusively ended this exact tool invocation.

    A network timeout can happen after inference starts, so it remains fenced.
    The Gateway's documented HTTP tool endpoint, however, sends a final JSON
    error envelope after the invocation has completed unsuccessfully.
    """
    if not isinstance(error, httpx.HTTPStatusError) or error.response.status_code < 400:
        return False
    try:
        body = error.response.json()
    except (ValueError, TypeError):
        return False
    return isinstance(body, dict) and body.get('ok') is False and 'error' in body


def completion_error(error):
    if isinstance(error, httpx.TimeoutException):
        return 'analysis_timeout'
    if isinstance(error, httpx.HTTPStatusError):
        text = error.response.text[:8192]
        if 'LLM JSON did not match schema' in text or 'LLM returned invalid JSON' in text:
            return 'invalid_model_output'
        return 'analysis_call_failed'
    return 'invalid_model_output'
