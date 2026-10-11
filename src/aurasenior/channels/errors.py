"""Map AWS client errors to retryable or not (throttling and 5xx retry, everything else falls back)."""
from __future__ import annotations

from botocore.exceptions import BotoCoreError, ClientError

from .base import SendResult

RETRYABLE = {"ThrottlingException", "Throttling", "TooManyRequestsException", "ServiceUnavailableException",
             "InternalServerException", "InternalFailure", "ServiceUnavailable", "RequestTimeout",
             "LimitExceededException"}


def to_result(e: Exception) -> SendResult:
    if isinstance(e, ClientError):
        code = e.response.get("Error", {}).get("Code", "Unknown")
        status = e.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 400)
        return SendResult.failed(code, code in RETRYABLE or status >= 500)
    if isinstance(e, BotoCoreError):
        return SendResult.failed(type(e).__name__, True)
    raise e
