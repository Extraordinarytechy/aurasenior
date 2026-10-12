from botocore.exceptions import ClientError

from aurasenior.channels.errors import to_result


def _denied(message: str) -> ClientError:
    return ClientError({"Error": {"Code": "AccessDeniedException", "Message": message},
                        "ResponseMetadata": {"HTTPStatusCode": 403}}, "SendEmail")


def test_failed_send_keeps_the_masked_error_message():
    r = to_result(_denied("not authorized to perform ses:SendEmail on resource "
                          "arn:aws:ses:us-east-1:123456789012:identity/person@example.com"))
    assert r.code == "AccessDeniedException" and not r.retryable
    assert "ses:SendEmail" in r.message and "identity/" in r.message
    assert "person@example.com" not in r.message and "123456789012" not in r.message


def test_error_message_is_truncated():
    assert len(to_result(_denied("x" * 1000)).message) == 300
