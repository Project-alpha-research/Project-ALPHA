"""Explicit, redacted provider verification receipts.

The registry may describe local package and credential presence. Only this module performs a
bounded, operator-requested check and only its immutable receipt can describe verification.
"""

from __future__ import annotations

import hashlib
import json
import re
import urllib.error
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Final, Literal
from zoneinfo import ZoneInfo

from alpha_core import DataError
from alpha_core.atomic import write_text
from alpha_data.adapters.alpaca_adapter import AlpacaAdapter
from alpha_data.adapters.tiingo_adapter import TiingoAdapter
from alpha_data.crypto.providers.coingecko import coingecko_demo_request, fetch_coingecko_demo

type VerificationState = Literal[
    "verified",
    "unverified",
    "authentication_failed",
    "entitlement_denied",
    "rate_limited",
    "connectivity_failed",
    "schema_drift",
    "optional_disabled",
]

_STATES: Final = frozenset(
    {
        "verified",
        "unverified",
        "authentication_failed",
        "entitlement_denied",
        "rate_limited",
        "connectivity_failed",
        "schema_drift",
        "optional_disabled",
    }
)
_DETAIL_KEYS: Final = frozenset(
    {
        "interface",
        "symbol",
        "row_count",
        "schema_version",
        "docker_cli",
        "docker_daemon",
        "image_digest_reviewed",
        "signed_local_app_reviewed",
        "account_alias",
        "gateway_reachable",
        "host",
        "port",
        "permissions",
        "market_data",
        "coin_id",
    }
)
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def _canonical(value: Mapping[str, object]) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def _timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise DataError("provider check timestamp must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def record_check_receipt(
    data_dir: Path,
    *,
    provider_id: str,
    verification_state: VerificationState,
    granted_capabilities: Sequence[str],
    checked_at: datetime,
    recovery_action: str,
    details: Mapping[str, object],
) -> dict[str, object]:
    """Persist one immutable receipt after removing everything outside the public schema."""
    provider = provider_id.strip().lower()
    if not provider or not re.fullmatch(r"[a-z0-9_-]+", provider):
        raise DataError("provider id is invalid")
    if verification_state not in _STATES:
        raise DataError("provider verification state is invalid")
    safe_details = {key: details[key] for key in sorted(details) if key in _DETAIL_KEYS}
    body: dict[str, object] = {
        "schema_version": 1,
        "provider_id": provider,
        "verification_state": verification_state,
        "checked_at": _timestamp(checked_at),
        "granted_capabilities": sorted(set(granted_capabilities)),
        "recovery_action": recovery_action.strip()[:500],
        "details": safe_details,
    }
    digest = hashlib.sha256(_canonical(body)).hexdigest()
    receipt = {**body, "receipt_id": digest, "content_sha256": digest}
    path = Path(data_dir) / "provider-checks" / provider / f"{digest}.json"
    rendered = json.dumps(receipt, sort_keys=True, indent=2, allow_nan=False) + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") != rendered:
            raise DataError("provider receipt identity collision")
    else:
        write_text(path, rendered)
    return receipt


def _verify_receipt(raw: object, provider_id: str) -> dict[str, object] | None:
    if not isinstance(raw, dict):
        return None
    digest = raw.get("content_sha256")
    if not isinstance(digest, str) or _SHA256.fullmatch(digest) is None:
        return None
    body = {key: value for key, value in raw.items() if key not in {"receipt_id", "content_sha256"}}
    if hashlib.sha256(_canonical(body)).hexdigest() != digest:
        return None
    if raw.get("receipt_id") != digest or raw.get("provider_id") != provider_id:
        return None
    return raw


def last_check_status(data_dir: Path, provider_id: str) -> dict[str, object]:
    root = Path(data_dir) / "provider-checks" / provider_id
    if not root.exists():
        return {
            "verification_state": "unverified",
            "verified_at": None,
            "last_receipt_id": None,
            "granted_capabilities": [],
            "recovery_action": "Run an explicit provider check from the Readiness Center.",
        }
    valid: list[dict[str, object]] = []
    tampered = False
    for path in root.glob("*.json"):
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            tampered = True
            continue
        receipt = _verify_receipt(raw, provider_id)
        if receipt is None:
            tampered = True
        else:
            valid.append(receipt)
    if tampered:
        return {
            "verification_state": "schema_drift",
            "verified_at": None,
            "last_receipt_id": None,
            "granted_capabilities": [],
            "recovery_action": (
                "A provider receipt failed integrity verification; inspect locally and rerun "
                "the check."
            ),
        }
    if not valid:
        return last_check_status(Path(data_dir) / "__missing__", provider_id)
    latest = max(valid, key=lambda row: (str(row["checked_at"]), str(row["receipt_id"])))
    verified = latest["verification_state"] == "verified"
    return {
        "verification_state": latest["verification_state"],
        "verified_at": latest["checked_at"] if verified else None,
        "last_receipt_id": latest["receipt_id"],
        "granted_capabilities": latest["granted_capabilities"] if verified else [],
        "recovery_action": latest["recovery_action"],
    }


def classify_failure(status_code: int | None, detail: str) -> VerificationState:
    if status_code == 401:
        return "authentication_failed"
    if status_code == 403:
        return "entitlement_denied"
    if status_code == 429:
        return "rate_limited"
    lowered = detail.lower()
    if status_code is None and any(
        token in lowered for token in ("timeout", "transport", "connect")
    ):
        return "connectivity_failed"
    return "schema_drift"


def _failure_from_exception(exc: Exception) -> VerificationState:
    match = re.search(r"(?:http|error)\s*(401|403|429)", str(exc), re.IGNORECASE)
    code = int(match.group(1)) if match else None
    return classify_failure(code, str(exc))


def _tiingo_check() -> tuple[tuple[str, ...], dict[str, object]]:
    end = date.today()
    result = TiingoAdapter(canonical_symbol="SPY", asset_class="etf").fetch(
        "SPY", end - timedelta(days=14), end
    )
    return ("historical_bars", "corporate_actions"), {
        "interface": "rest",
        "symbol": "SPY",
        "row_count": result.bars.height,
    }


def _alpaca_check() -> tuple[tuple[str, ...], dict[str, object]]:
    end = datetime.now(ZoneInfo("America/New_York")).date() - timedelta(days=1)
    result = AlpacaAdapter(asset_class="etf").fetch("SPY", end - timedelta(days=14), end)
    return ("historical_bars", "corporate_actions"), {
        "interface": "rest",
        "symbol": "SPY",
        "row_count": result.bars.height,
    }


def _coingecko_check() -> tuple[tuple[str, ...], dict[str, object]]:
    import os

    api_key = os.environ.get("ALPHA_COINGECKO_API_KEY", "")
    payload = fetch_coingecko_demo(coingecko_demo_request("ping", {}, api_key=api_key))
    try:
        raw = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DataError("CoinGecko Demo ping response is malformed") from exc
    if not isinstance(raw, dict) or not isinstance(raw.get("gecko_says"), str):
        raise DataError("CoinGecko Demo ping schema drifted")
    return ("asset_metadata", "market_reference"), {
        "interface": "rest_demo",
        "coin_id": "ping",
        "schema_version": 1,
    }


def _defillama_check() -> tuple[tuple[str, ...], dict[str, object]]:
    from alpha_data.crypto.providers.defillama import (
        check_chain_tvl,
        defillama_url,
        fetch_defillama,
    )

    chain = "ethereum"
    summary = check_chain_tvl(fetch_defillama(defillama_url("chain_tvl", chain=chain)), chain=chain)
    return ("defi_tvl",), {
        "interface": "rest_public",
        "chain": chain,
        "rows": summary["rows"],
        "last_observed_at": str(summary["last_observed_at"]),
        "schema_version": 1,
    }


class ProviderCheckFailure(Exception):
    def __init__(self, state: VerificationState, details: Mapping[str, object]) -> None:
        super().__init__(state)
        self.state = state
        self.details = details


_CHECKERS: dict[str, Callable[[], tuple[tuple[str, ...], dict[str, object]]]] = {
    "tiingo": _tiingo_check,
    "alpaca": _alpaca_check,
    "coingecko": _coingecko_check,
    "defillama": _defillama_check,
}


def run_explicit_check(data_dir: Path, provider_id: str) -> dict[str, object]:
    """Perform exactly one bounded provider check requested by an owner click or CLI command."""
    provider = provider_id.strip().lower()
    checker = _CHECKERS.get(provider)
    if checker is None:
        raise DataError("explicit checks are available only for supported providers")
    try:
        capabilities, details = checker()
    except ProviderCheckFailure as exc:
        state = exc.state
        capabilities = ()
        details = dict(exc.details)
    except (OSError, urllib.error.URLError, DataError, json.JSONDecodeError) as exc:
        state = _failure_from_exception(exc)
        capabilities = ()
        details = {"interface": "rest"}
    else:
        state = "verified"
    recovery = {
        "verified": "No action required.",
        "unverified": (
            "Run the separately checkpointed paper what-if preview to verify broker callbacks."
        ),
        "authentication_failed": (
            "Rotate the credential, reinject it into the process, and run one new explicit check."
        ),
        "entitlement_denied": (
            "Review the provider subscription and requested capability before retrying."
        ),
        "rate_limited": (
            "Wait for the provider limit to reset before running one new explicit check."
        ),
        "connectivity_failed": (
            "Check local network or gateway state, then run one new explicit check."
        ),
        "schema_drift": (
            "Review the provider adapter against the current official schema before retrying."
        ),
    }[state]
    return record_check_receipt(
        data_dir,
        provider_id=provider,
        verification_state=state,
        granted_capabilities=capabilities,
        checked_at=datetime.now(UTC),
        recovery_action=recovery,
        details=details,
    )


__all__ = [
    "classify_failure",
    "last_check_status",
    "record_check_receipt",
    "run_explicit_check",
]
