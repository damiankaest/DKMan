"""Bounded text-only logs. Patterns cannot recognize arbitrary free-form secrets."""

import re
import unicodedata


def redact_logs(value: str) -> str:
    value = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", value)
    value = "".join(c for c in value if c in "\n\t" or not unicodedata.category(c).startswith("C"))
    value = re.sub(r"(?i)(authorization\s*[:=]\s*(?:bearer\s+)?)[^\s]+", r"\1[REDACTED]", value)
    value = re.sub(
        r"(?i)((?:password|secret|token|api[_-]?key)[\"']?\s*[:=]\s*)"
        r"(\"[^\"]*\"|'[^']*'|[^\s]+)",
        r"\1[REDACTED]",
        value,
    )
    value = re.sub(r"([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^@\s/]+@", r"\1[REDACTED]@", value)
    value = re.sub(
        r"[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}", "[REDACTED]", value
    )
    return (
        "\n".join(value.splitlines()[-100:]).encode("utf-8")[:8192].decode("utf-8", errors="ignore")
    )
