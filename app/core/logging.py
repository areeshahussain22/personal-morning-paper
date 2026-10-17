from __future__ import annotations

import logging
import re
from typing import Any


_SENSITIVE_QUERY = re.compile(r"([?&](?:key|api_key|token|access_token)=)[^&\s]+", re.IGNORECASE)
_AUTHORIZATION = re.compile(r"(authorization\s*[:=]\s*bearer\s+)[^\s,]+", re.IGNORECASE)


def redact_log_value(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    value = _SENSITIVE_QUERY.sub(r"\1[REDACTED]", value)
    return _AUTHORIZATION.sub(r"\1[REDACTED]", value)


class SensitiveDataFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_log_value(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {key: redact_log_value(value) for key, value in record.args.items()}
            else:
                record.args = tuple(redact_log_value(value) for value in record.args)
        if record.exc_info:
            record.exc_info = None
        return True


def configure_http_logging() -> None:
    for name in ("httpx", "httpcore"):
        logger = logging.getLogger(name)
        logger.setLevel(logging.WARNING)
        logger.addFilter(SensitiveDataFilter())
