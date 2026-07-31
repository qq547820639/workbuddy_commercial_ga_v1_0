from __future__ import annotations
import hashlib
import hmac
import json
from datetime import datetime
from typing import Any
from workbuddy.services.common import canonical_json, naive_utc, utcnow
from workbuddy.settings import settings

class GateSigningError(ValueError):
    pass

def _signing_key() -> bytes:
    """HMAC signing key derived from the application secret.

    NOTE: this is a shared, code-scope key. A production deployment that needs
    per-owner accountability should source an independent ``owner_signing_key``
    here instead of reusing ``app_secret``. The previous ``if ...: pass`` branch
    only documented that intent without implementing it, so it has been removed.
    """
    return hashlib.sha256(settings.app_secret.encode()).digest()

def _normalize_timestamp(ts) -> str:
    """Normalize a timestamp to a consistent ISO format string for signing/verification."""
    if ts is None:
        ts = utcnow()
    if isinstance(ts, str):
        # Parse string back to datetime for consistent normalization.
        # Handles both 'T' and space separators (SQLite returns space).
        try:
            ts = datetime.fromisoformat(ts)
        except ValueError:
            try:
                ts = datetime.fromisoformat(ts.replace(" ", "T"))
            except ValueError:
                return ts  # Return as-is if not parseable
    if hasattr(ts, "isoformat"):
        return naive_utc(ts).isoformat()
    return str(ts)

def sign_attestation(*, role, decision, snapshot_hash, actor_id, timestamp=None) -> tuple[str, str]:
    """Sign an attestation with HMAC-SHA256. Returns (signature_hex, key_id)."""
    ts = _normalize_timestamp(timestamp)
    message = canonical_json({"role": role, "decision": decision, "snapshot_hash": snapshot_hash, "actor_id": actor_id, "timestamp": ts})
    key = _signing_key()
    signature = hmac.new(key, message.encode("utf-8"), hashlib.sha256).hexdigest()
    key_id = f"hmac-sha256:{settings.app_secret[:8]}..."
    return signature, key_id

def verify_attestation_signature(*, role, decision, snapshot_hash, actor_id, timestamp, signature, key_id=None) -> bool:
    """Verify an attestation signature."""
    ts = _normalize_timestamp(timestamp)
    message = canonical_json({"role": role, "decision": decision, "snapshot_hash": snapshot_hash, "actor_id": actor_id, "timestamp": ts})
    key = _signing_key()
    expected = hmac.new(key, message.encode("utf-8"), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)
