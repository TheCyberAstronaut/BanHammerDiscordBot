import os
from dataclasses import dataclass
from typing import List, Optional, Set


def _parse_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _parse_int(value: Optional[str], name: str) -> int:
    if value is None or not value.strip():
        raise ValueError(f"Missing required env var: {name}")
    return int(value)


def _parse_list(value: Optional[str]) -> Set[str]:
    if not value:
        return set()
    cleaned = []
    for item in value.split(","):
        stripped = item.strip()
        if stripped.startswith("\"") and stripped.endswith("\""):
            stripped = stripped[1:-1]
        if stripped.startswith("'") and stripped.endswith("'"):
            stripped = stripped[1:-1]
        if stripped:
            cleaned.append(stripped.lower())
    return set(cleaned)

def _parse_string(value: Optional[str], name: str) -> str:
    if value is None or not value.strip():
        raise ValueError(f"Missing required env var: {name}")
    value = value.strip("'\"")
    return value.strip()


def _parse_int_list(value: Optional[str]) -> List[int]:
    if not value:
        return []
    items = []
    for item in value.split(","):
        stripped = item.strip()
        if stripped.startswith("\"") and stripped.endswith("\""):
            stripped = stripped[1:-1]
        if stripped.startswith("'") and stripped.endswith("'"):
            stripped = stripped[1:-1]
        if stripped:
            items.append(int(stripped))
    return items


@dataclass(frozen=True)
class Config:
    discord_token: str
    email_verification_enabled: bool
    smtp_host: str
    smtp_port: int
    smtp_user: Optional[str]
    smtp_password: Optional[str]
    smtp_use_tls: bool
    email_from: str
    verification_domain_allowlist: Set[str]
    verification_domain_denylist: Set[str]
    verification_token_ttl_minutes: int
    admin_channel_id: int
    wall_of_shame_channel_id: int
    verified_role_id: int
    guild_id: int
    report_role_allowlist: List[int]
    db_path: str
    log_level: str

    @classmethod
    def from_env(cls) -> "Config":
        discord_token = os.getenv("DISCORD_TOKEN")
        if not discord_token:
            raise ValueError("Missing required env var: DISCORD_TOKEN")

        email_verification_enabled = _parse_bool(
            os.getenv("EMAIL_VERIFICATION_ENABLED"), True
        )
        smtp_host = _parse_string(os.getenv("SMTP_HOST", ""), "SMTP_HOST") if email_verification_enabled else ""
        email_from = _parse_string(os.getenv("EMAIL_FROM", ""), "EMAIL_FROM") if email_verification_enabled else ""
        smtp_password = _parse_string(os.getenv("SMTP_PASSWORD"), "SMTP_PASSWORD") if email_verification_enabled else ""
        if email_verification_enabled:
            if not smtp_host:
                raise ValueError("Missing required env var: SMTP_HOST")
            if not email_from.strip():
                raise ValueError("Missing required env var: EMAIL_FROM")

        return cls(
            discord_token=discord_token,
            email_verification_enabled=email_verification_enabled,
            smtp_host=smtp_host,
            smtp_port=_parse_int(os.getenv("SMTP_PORT", "587"), "SMTP_PORT"),
            smtp_user=os.getenv("SMTP_USER"),
            smtp_password=smtp_password,
            smtp_use_tls=_parse_bool(os.getenv("SMTP_USE_TLS"), True),
            email_from=email_from,
            verification_domain_allowlist=_parse_list(
                os.getenv("VERIFICATION_DOMAIN_ALLOWLIST")
            ),
            verification_domain_denylist=_parse_list(
                os.getenv("VERIFICATION_DOMAIN_DENYLIST")
            ),
            verification_token_ttl_minutes=_parse_int(
                os.getenv("VERIFICATION_TOKEN_TTL_MINUTES", "30"), "VERIFICATION_TOKEN_TTL_MINUTES"
            ),
            admin_channel_id=_parse_int(os.getenv("ADMIN_CHANNEL_ID"), "ADMIN_CHANNEL_ID"),
            wall_of_shame_channel_id=_parse_int(
                os.getenv("WALL_OF_SHAME_CHANNEL_ID"), "WALL_OF_SHAME_CHANNEL_ID"),
            verified_role_id=_parse_int(os.getenv("VERIFIED_ROLE_ID"), "VERIFIED_ROLE_ID"),
            guild_id=_parse_int(os.getenv("GUILD_ID"), "GUILD_ID"),
            report_role_allowlist=_parse_int_list(
                os.getenv("REPORT_ROLE_ALLOWLIST")
            ),
            db_path=os.getenv("DB_PATH", "data/bot.db"),
            log_level=os.getenv("LOG_LEVEL", "INFO"),
        )
