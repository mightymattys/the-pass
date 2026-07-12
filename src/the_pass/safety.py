"""Shared fail-closed checks for credential-like configuration keys."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any


SENSITIVE_KEY_NAMES = {
    "api_key",
    "api_secret",
    "auth_token",
    "bearer_token",
    "client_secret",
    "credential",
    "credentials",
    "password",
    "private_key",
    "refresh_token",
    "secret",
    "seed_phrase",
    "session_token",
    "token",
    "wallet_key",
}


def normalize_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).casefold()).strip("_")


def is_sensitive_key(value: object) -> bool:
    key = normalize_key(value)
    if key in SENSITIVE_KEY_NAMES or key.endswith(("_password", "_secret", "_credential")):
        return True
    if key.endswith("_token") and not key.endswith(("_token_id", "_token_ids")):
        return True
    return key.endswith(("_api_key", "_private_key", "_wallet_key", "_seed_phrase"))


def contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(is_sensitive_key(key) or contains_sensitive_key(child) for key, child in value.items())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return any(contains_sensitive_key(child) for child in value)
    return False
