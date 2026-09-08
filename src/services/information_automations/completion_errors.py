"""Project completion failures to bounded codes without retaining upstream text."""
import httpx


def completion_error(error):
    if isinstance(error, httpx.TimeoutException):
        return 'analysis_timeout'
    if isinstance(error, httpx.HTTPStatusError):
        text = error.response.text[:8192]
        if 'LLM JSON did not match schema' in text or 'LLM returned invalid JSON' in text:
            return 'invalid_model_output'
        return 'analysis_call_failed'
    return 'invalid_model_output'
