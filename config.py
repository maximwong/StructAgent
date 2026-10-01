"""Load local DeepSeek settings without executing .env content or exposing secrets."""

from dataclasses import dataclass, field
import math
import os
from pathlib import Path


class ConfigurationError(ValueError):
    pass


@dataclass(frozen=True)
class DeepSeekSettings:
    api_key: str = field(repr=False)
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    timeout_seconds: float = 45

    def __post_init__(self):
        if (not isinstance(self.api_key, str) or not self.api_key.strip()
                or any(c.isspace() for c in self.api_key)):
            raise ConfigurationError("DEEPSEEK_API_KEY is missing or invalid.")
        # Credentials may only be sent to the official service; redirects are also disabled.
        if self.base_url not in ("https://api.deepseek.com", "https://api.deepseek.com/v1"):
            raise ConfigurationError("DEEPSEEK_BASE_URL must use the official HTTPS endpoint.")
        if self.model not in ("deepseek-flash", "deepseek-v4-pro"):
            raise ConfigurationError("Unsupported DEEPSEEK_MODEL; check the official API documentation.")
        if (isinstance(self.timeout_seconds, bool) or not isinstance(self.timeout_seconds, (int, float))
                or not math.isfinite(self.timeout_seconds) or not 1 <= self.timeout_seconds <= 60):
            raise ConfigurationError("DEEPSEEK_TIMEOUT_SECONDS must be between 1 and 60.")


def load_settings(path=None, *, environ=None):
    """Environment variables override an explicit repo-local .env, never the current directory."""
    path = Path(path) if path is not None else Path(__file__).resolve().with_name(".env")
    values = {}
    if path.exists():
        for line_number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            name, separator, value = line.partition("=")
            if not separator or name.strip() in values:
                raise ConfigurationError(f"Invalid or duplicate .env entry at line {line_number}.")
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values[name.strip()] = value
    environment = os.environ if environ is None else environ
    keys = ("DEEPSEEK_API_KEY", "DEEPSEEK_BASE_URL", "DEEPSEEK_MODEL", "DEEPSEEK_TIMEOUT_SECONDS")
    values.update({k: environment[k] for k in keys if k in environment})
    try:
        timeout = float(values.get("DEEPSEEK_TIMEOUT_SECONDS", "45"))
    except (TypeError, ValueError):
        raise ConfigurationError("Invalid DEEPSEEK_TIMEOUT_SECONDS.") from None
    return DeepSeekSettings(values.get("DEEPSEEK_API_KEY", ""),
                            values.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
                            values.get("DEEPSEEK_MODEL", "deepseek-flash"), timeout)
