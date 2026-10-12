"""Map AWS client errors to retryable or not (throttling and 5xx retry, everything else falls back)."""
from __future__ import annotations

from botocore.exceptions import BotoCoreError, ClientError

from .. import log
from .base import SendResult

RETRYABLE = {"ThrottlingException", "Throttling", "TooManyRequestsException", "ServiceUnavailableException",
             "InternalServerException", "InternalFailure", "ServiceUnavailable", "RequestTimeout",
             "LimitExceededException"}


def to_result(e: Exception) -> SendResult:
    if isinstance(e, ClientError):
        code = e.response.get("Error", {}).get("Code", "Unknown")
        status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 400)
        return SendResult.failed(code, code in RETRYABLE or status >= 500, message=error_message(e))
    if isinstance(e, BotoCoreError):
        return SendResult.failed(type(e).__name__, True, message=error_message(e))
    raise e


def error_message(e: Exception, limit: int = 300) -> str:
    """The AWS error text names the denied action and resource; emails and numbers are masked before logging."""
    if isinstance(e, ClientError):
        text = e.response.get("Error", {}).get("Message", "") or str(e)
    else:
        text = str(e)
    return log.mask_text(text)[:limit]
