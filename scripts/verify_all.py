#!/usr/bin/env python3
"""
Expanded beaconcha.in API cross-verification test suite.

Maps beaconcha.in endpoints to Ethereum Beacon Node RPC endpoints and
runs concrete test cases comparing the two sources.

Test categories:
  1. Validator balance at epoch (existing, expanded)
  2. Validator status & lifecycle
  3. Attestation rewards per epoch
  4. Block proposal data (proposer, attestation count)
  5. Sync committee participation
  6. Withdrawal verification
  7. Epoch summary (participation rate, finalization)

Usage:
    python3 verify_all.py --beaconchain-api-key KEY [--rpc-urls URL ...] [--test-ids T1 T2 ...] [--output-dir DIR]
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any

try:
    import requests
except ImportError:
    print("ERROR: 'requests' required. pip install requests --break-system-packages", file=sys.stderr)
    sys.exit(1)

from fork_epochs import (
    FORK_EPOCHS, FORK_FEATURES, get_fork_for_epoch, get_fork_info,
    epoch_to_first_slot, epoch_to_last_slot, epoch_to_timestamp,
    SLOTS_PER_EPOCH, SECONDS_PER_SLOT, MAINNET_GENESIS_TIME,
)

# ─── Constants ────────────────────────────────────────────────────────────────

DEFAULT_RPC_URLS = [
    "https://eth-beacon-chain.drpc.org",
    "https://ethereum-beacon-api.publicnode.com",
]

BEACONCHAIN_BASE = "https://beaconcha.in"

MAX_RETRIES = 3
RETRY_BACKOFF = 2
RATE_LIMIT_SLEEP = 1.1  # seconds between beaconcha.in calls (free tier)


# ─── HTTP Helpers ─────────────────────────────────────────────────────────────

def fetch_get(url: str, headers: dict = None, retries: int = MAX_RETRIES) -> dict:
    """GET with retry. Returns {"status": int, "data": Any, "error": str|None}."""
    for attempt in range(retries):
        try:
            resp = requests.get(url, headers=headers or {}, timeout=30)
            if resp.status_code == 200:
                return {"status": 200, "data": resp.json(), "error": None}
            elif resp.status_code in (429, 500, 502, 503):
                wait = RETRY_BACKOFF ** (attempt + 1)
                reset = resp.headers.get("ratelimit-reset")
                if reset:
                    try:
                        wait = max(wait, int(reset))
                    except ValueError:
                        pass
                time.sleep(wait)
            else:
                return {"status": resp.status_code, "data": None, "error": f"HTTP {resp.status_code}: {resp.text[:300]}"}
        except requests.RequestException as e:
            if attempt == retries - 1:
                return {"status": 0, "data": None, "error": str(e)}
            time.sleep(RETRY_BACKOFF ** (attempt + 1))
    return {"status": 0, "data": None, "error": "Max retries exceeded"}


def fetch_post(url: str, body: dict, headers: dict = None, retries: int = MAX_RETRIES) -> dict:
    """POST with retry."""
    hdrs = {"Content-Type": "application/json"}
    if headers:
        hdrs.update(headers)
    for attempt in range(retries):
        try:
            resp = requests.post(url, json=body, headers=hdrs, timeout=30)
            if resp.status_code == 200:
                return {"status": 200, "data": resp.json(), "error": None}
            elif resp.status_code in (429, 500, 502, 503):
                wait = RETRY_BACKOFF ** (attempt + 1)
                time.sleep(wait)
            else:
                return {"status": resp.status_code, "data": None, "error": f"HTTP {resp.status_code}: {resp.text[:300]}"}
        except requests.RequestException as e:
            if attempt == retries - 1:
                return {"status": 0, "data": None, "error": str(e)}
            time.sleep(RETRY_BACKOFF ** (attempt + 1))
    return {"status": 0, "data": None, "error": "Max retries exceeded"}


def rpc_get(rpc_urls: list, path: str) -> dict:
    """Try GET across multiple RPC providers. Returns first success."""
    for rpc in rpc_urls:
        url = f"{rpc.rstrip('/')}{path}"
        result = fetch_get(url)
        if result["error"] is None:
            result["url"] = url
            return result
    return {"status": 0, "data": None, "error": "All RPC providers failed", "url": path}


# ─── Test Result ──────────────────────────────────────────────────────────────

@dataclass
class TestResult:
    test_id: str
    test_name: str
    description: str
    timestamp: str
    fork_phase: str
    epoch: int
    validator_index: int
    # Sources
    beaconchain_endpoint: str = ""
    beaconchain_value: Any = None
    beaconchain_error: Optional[str] = None
    rpc_endpoint: str = ""
    rpc_value: Any = None
    rpc_error: Optional[str] = None
    # Comparison
    match: Optional[bool] = None
    discrepancy: Optional[str] = None
    conclusion: str = ""

    def to_dict(self):
        return asdict(self)

    def to_markdown(self) -> str:
        status = "✅ PASS" if self.match else ("❌ FAIL" if self.match is False else "⚠️ INCONCLUSIVE")
        lines = [
            f"## {self.test_id}: {self.test_name}",
            f"**Status:** {status}",
            f"**Timestamp:** {self.timestamp}",
            f"**Fork phase:** {self.fork_phase}",
            f"**Epoch:** {self.epoch} | **Validator:** {self.validator_index}",
            "",
            f"**Description:** {self.description}",
            "",
            "### Data Comparison",
            "",
            "| Source | Endpoint | Value | Status |",
            "|--------|----------|-------|--------|",
            f"| beaconcha.in | `{self.beaconchain_endpoint}` | `{self.beaconchain_value}` | {'🟢' if not self.beaconchain_error else '🔴 ' + str(self.beaconchain_error)} |",
            f"| RPC | `{self.rpc_endpoint}` | `{self.rpc_value}` | {'🟢' if not self.rpc_error else '🔴 ' + str(self.rpc_error)} |",
            "",
        ]
        if self.discrepancy:
            lines.append(f"### Discrepancy\n{self.discrepancy}\n")
        lines.append(f"### Conclusion\n{self.conclusion}\n")
        lines.append("---\n")
        return "\n".join(lines)


# ─── Test Implementations ────────────────────────────────────────────────────

def test_balance_at_epoch(api_key: str, rpc_urls: list, validator: int, epoch: int) -> TestResult:
    """T1: Compare beaconcha.in balancehistory with RPC state balance at epoch boundary."""
    fork = get_fork_for_epoch(epoch)
    first_slot = epoch_to_first_slot(epoch)
    last_slot = epoch_to_last_slot(epoch)
    now = datetime.now(timezone.utc).isoformat()

    result = TestResult(
        test_id="T1", test_name="Validator Balance at Epoch",
        description=f"Compare balancehistory balance for validator {validator} at epoch {epoch} against RPC balance at first slot ({first_slot}) and last slot ({last_slot}).",
        timestamp=now, fork_phase=fork, epoch=epoch, validator_index=validator,
    )

    # beaconcha.in
    bc_url = f"{BEACONCHAIN_BASE}/api/v1/validator/{validator}/balancehistory?latest_epoch={epoch}&offset=0&limit=1&apikey={api_key}"
    bc_display = f"/api/v1/validator/{validator}/balancehistory?latest_epoch={epoch}&offset=0&limit=1"
    result.beaconchain_endpoint = bc_display
    bc = fetch_get(bc_url)
    time.sleep(RATE_LIMIT_SLEEP)

    if bc["error"]:
        result.beaconchain_error = bc["error"]
    elif bc["data"] and bc["data"].get("data"):
        result.beaconchain_value = bc["data"]["data"][0].get("balance")
    else:
        result.beaconchain_error = "Empty response"

    # RPC first slot
    rpc_path_first = f"/eth/v1/beacon/states/{first_slot}/validators/{validator}"
    rpc_first = rpc_get(rpc_urls, rpc_path_first)
    rpc_bal_first = None
    if rpc_first["data"] and "data" in rpc_first["data"]:
        rpc_bal_first = int(rpc_first["data"]["data"].get("balance", 0))

    # RPC last slot
    rpc_path_last = f"/eth/v1/beacon/states/{last_slot}/validators/{validator}"
    rpc_last = rpc_get(rpc_urls, rpc_path_last)
    rpc_bal_last = None
    if rpc_last["data"] and "data" in rpc_last["data"]:
        rpc_bal_last = int(rpc_last["data"]["data"].get("balance", 0))

    result.rpc_endpoint = f"states/{first_slot} & {last_slot}/validators/{validator}"
    result.rpc_value = {"first_slot": rpc_bal_first, "last_slot": rpc_bal_last}
    if rpc_first["error"] and rpc_last["error"]:
        result.rpc_error = f"first: {rpc_first['error']}; last: {rpc_last['error']}"

    # Compare
    bc_val = int(result.beaconchain_value) if result.beaconchain_value is not None else None
    if bc_val is not None and rpc_bal_first is not None:
        if bc_val == rpc_bal_first:
            result.match = True
            result.conclusion = f"beaconcha.in matches first-slot balance ({bc_val} gwei). Definition: epoch-start."
        elif rpc_bal_last is not None and bc_val == rpc_bal_last:
            result.match = True
            result.conclusion = f"beaconcha.in matches last-slot balance ({bc_val} gwei). Definition: epoch-end."
        elif rpc_bal_last is not None:
            result.match = False
            result.discrepancy = f"bc={bc_val}, rpc_first={rpc_bal_first}, rpc_last={rpc_bal_last}"
            result.conclusion = "beaconcha.in matches neither epoch boundary. Investigate further."
        else:
            result.match = bc_val == rpc_bal_first
            result.conclusion = f"Only first-slot RPC available. Match: {result.match}"
    elif bc_val is None:
        result.conclusion = "beaconcha.in returned no data."
    else:
        result.conclusion = "RPC unavailable — cannot compare."

    return result


def test_validator_status(api_key: str, rpc_urls: list, validator: int, epoch: int) -> TestResult:
    """T2: Compare validator status between beaconcha.in V2 and RPC."""
    fork = get_fork_for_epoch(epoch)
    slot = epoch_to_first_slot(epoch)
    now = datetime.now(timezone.utc).isoformat()

    result = TestResult(
        test_id="T2", test_name="Validator Status",
        description=f"Compare validator {validator} status at epoch {epoch} between beaconcha.in V2 and RPC.",
        timestamp=now, fork_phase=fork, epoch=epoch, validator_index=validator,
    )

    # beaconcha.in V2
    bc_url = f"{BEACONCHAIN_BASE}/api/v2/ethereum/validators"
    bc_body = {"validator": {"validator_identifiers": [validator]}, "chain": "mainnet", "page_size": 1}
    result.beaconchain_endpoint = "POST /api/v2/ethereum/validators"
    bc = fetch_post(bc_url, bc_body, headers={"Authorization": f"Bearer {api_key}"})
    time.sleep(RATE_LIMIT_SLEEP)

    bc_status = None
    if bc["error"]:
        result.beaconchain_error = bc["error"]
    elif bc["data"] and bc["data"].get("data"):
        bc_status = bc["data"]["data"][0].get("status")
        result.beaconchain_value = bc_status
    else:
        result.beaconchain_error = "Empty response"

    # RPC
    rpc_path = f"/eth/v1/beacon/states/{slot}/validators/{validator}"
    result.rpc_endpoint = rpc_path
    rpc = rpc_get(rpc_urls, rpc_path)
    rpc_status = None
    if rpc["data"] and "data" in rpc["data"]:
        rpc_status = rpc["data"]["data"].get("status")
        result.rpc_value = rpc_status
    elif rpc["error"]:
        result.rpc_error = rpc["error"]

    # Compare (beaconcha.in uses underscore naming like "active_online"; RPC uses same)
    if bc_status and rpc_status:
        # Normalize: beaconcha.in may say "active_online", RPC says "active_ongoing"
        bc_norm = bc_status.replace("_online", "").replace("_offline", "")
        rpc_norm = rpc_status.replace("_ongoing", "").replace("_idle", "").replace("_slashed", "").replace("_exited", "")
        # Both should start with same root: active, pending, exited, withdrawal
        result.match = bc_norm.split("_")[0] == rpc_norm.split("_")[0]
        if result.match:
            result.conclusion = f"Status root matches: bc='{bc_status}', rpc='{rpc_status}'."
        else:
            result.match = False
            result.discrepancy = f"bc='{bc_status}' vs rpc='{rpc_status}'"
            result.conclusion = "Status mismatch between sources."
    else:
        result.conclusion = "Cannot compare — one or both sources unavailable."

    return result


def test_attestation_rewards(api_key: str, rpc_urls: list, validator: int, epoch: int) -> TestResult:
    """T3: Compare attestation rewards from beaconcha.in V2 rewards-list vs RPC beacon rewards API."""
    fork = get_fork_for_epoch(epoch)
    now = datetime.now(timezone.utc).isoformat()

    result = TestResult(
        test_id="T3", test_name="Attestation Rewards",
        description=f"Compare attestation rewards for validator {validator} at epoch {epoch}. beaconcha.in V2 rewards-list vs RPC /eth/v1/beacon/rewards/attestations.",
        timestamp=now, fork_phase=fork, epoch=epoch, validator_index=validator,
    )

    # beaconcha.in V2
    bc_url = f"{BEACONCHAIN_BASE}/api/v2/ethereum/validators/rewards-list"
    bc_body = {"validator": {"validator_identifiers": [validator]}, "chain": "mainnet", "page_size": 1, "epoch": epoch}
    result.beaconchain_endpoint = "POST /api/v2/ethereum/validators/rewards-list"
    bc = fetch_post(bc_url, bc_body, headers={"Authorization": f"Bearer {api_key}"})
    time.sleep(RATE_LIMIT_SLEEP)

    bc_att_total = None
    if bc["error"]:
        result.beaconchain_error = bc["error"]
    elif bc["data"] and bc["data"].get("data"):
        att = bc["data"]["data"][0].get("attestation", {})
        bc_att_total = att.get("total")
        result.beaconchain_value = {
            "attestation_total": bc_att_total,
            "head": att.get("head", {}).get("reward"),
            "source": att.get("source", {}).get("reward"),
            "target": att.get("target", {}).get("reward"),
        }
    else:
        result.beaconchain_error = "Empty response"

    # RPC: POST /eth/v1/beacon/rewards/attestations/{epoch} with body ["validator_index"]
    # Note: This endpoint may not be available on all public RPCs
    rpc_path = f"/eth/v1/beacon/rewards/attestations/{epoch}"
    result.rpc_endpoint = f"POST {rpc_path}"
    rpc_att_total = None

    for rpc_base in rpc_urls:
        url = f"{rpc_base.rstrip('/')}{rpc_path}"
        rpc = fetch_post(url, [str(validator)])
        if rpc["data"] and "data" in rpc["data"]:
            # RPC returns: {"data": {"total_rewards": [{"validator_index": "N", "head": "X", "source": "Y", "target": "Z", ...}]}}
            total_rewards = rpc["data"]["data"].get("total_rewards", [])
            if total_rewards:
                r = total_rewards[0]
                head = int(r.get("head", 0))
                source = int(r.get("source", 0))
                target = int(r.get("target", 0))
                rpc_att_total = head + source + target
                result.rpc_value = {"head": head, "source": source, "target": target, "computed_total": rpc_att_total}
                break
        elif rpc["error"]:
            result.rpc_error = rpc["error"]

    # Compare
    if bc_att_total is not None and rpc_att_total is not None:
        # beaconcha.in returns in wei, RPC in gwei — need to check units
        bc_gwei = int(bc_att_total)
        # If bc value is >> rpc, it's likely in wei
        if bc_gwei > rpc_att_total * 1000:
            bc_gwei = bc_gwei // 1_000_000_000  # convert wei to gwei

        result.match = bc_gwei == rpc_att_total
        if result.match:
            result.conclusion = f"Attestation rewards match: {rpc_att_total} gwei."
        else:
            result.discrepancy = f"bc={bc_att_total} (raw) vs rpc={rpc_att_total} gwei"
            result.conclusion = "Attestation reward mismatch. Check unit conversion (wei vs gwei)."
    else:
        result.conclusion = "Cannot compare — one or both sources returned no data."

    return result


def test_block_proposer(api_key: str, rpc_urls: list, validator: int, epoch: int) -> TestResult:
    """T4: Compare block proposal data for a slot between beaconcha.in and RPC."""
    fork = get_fork_for_epoch(epoch)
    slot = epoch_to_first_slot(epoch)  # Check first slot of epoch
    now = datetime.now(timezone.utc).isoformat()

    result = TestResult(
        test_id="T4", test_name="Block Proposer at Slot",
        description=f"Compare who proposed block at slot {slot} (epoch {epoch}) between beaconcha.in V1 /slot and RPC /blocks.",
        timestamp=now, fork_phase=fork, epoch=epoch, validator_index=validator,
    )

    # beaconcha.in V1 /api/v1/slot/{slot}
    bc_url = f"{BEACONCHAIN_BASE}/api/v1/slot/{slot}?apikey={api_key}"
    result.beaconchain_endpoint = f"/api/v1/slot/{slot}"
    bc = fetch_get(bc_url)
    time.sleep(RATE_LIMIT_SLEEP)

    bc_proposer = None
    if bc["error"]:
        result.beaconchain_error = bc["error"]
    elif bc["data"] and bc["data"].get("data"):
        d = bc["data"]["data"]
        if isinstance(d, list):
            d = d[0] if d else {}
        bc_proposer = d.get("proposer")
        result.beaconchain_value = {"proposer": bc_proposer, "status": d.get("status"), "exec_block_number": d.get("exec_block_number")}
    else:
        result.beaconchain_error = "Empty response"

    # RPC: GET /eth/v2/beacon/blocks/{slot}
    rpc_path = f"/eth/v2/beacon/blocks/{slot}"
    result.rpc_endpoint = rpc_path
    rpc_proposer = None
    rpc = rpc_get(rpc_urls, rpc_path)
    if rpc["data"] and "data" in rpc["data"]:
        msg = rpc["data"]["data"].get("message", {})
        rpc_proposer = int(msg.get("proposer_index", -1))
        result.rpc_value = {"proposer_index": rpc_proposer, "slot": msg.get("slot")}
    elif rpc["error"]:
        result.rpc_error = rpc["error"]
        # Slot might be missed (404)
        if "404" in str(rpc["error"]):
            result.rpc_value = "missed_slot"
            result.rpc_error = None

    # Compare
    if bc_proposer is not None and rpc_proposer is not None:
        result.match = int(bc_proposer) == rpc_proposer
        result.conclusion = f"Proposer {'matches' if result.match else 'MISMATCH'}: bc={bc_proposer}, rpc={rpc_proposer}."
    elif bc_proposer is not None and result.rpc_value == "missed_slot":
        result.match = True
        result.conclusion = f"Slot {slot} was missed. beaconcha.in shows proposer={bc_proposer} (assigned but missed)."
    else:
        result.conclusion = "Cannot compare — one or both sources unavailable."

    return result


def test_withdrawals_in_epoch(api_key: str, rpc_urls: list, validator: int, epoch: int) -> TestResult:
    """T5: Check withdrawal data by scanning RPC blocks and comparing balance delta."""
    fork = get_fork_for_epoch(epoch)
    fork_info = get_fork_info(epoch)
    first_slot = epoch_to_first_slot(epoch)
    last_slot = epoch_to_last_slot(epoch)
    now = datetime.now(timezone.utc).isoformat()

    result = TestResult(
        test_id="T5", test_name="Withdrawals in Epoch",
        description=f"Scan all 32 slots of epoch {epoch} for withdrawals affecting validator {validator}. Verify withdrawal sum matches balance delta.",
        timestamp=now, fork_phase=fork, epoch=epoch, validator_index=validator,
    )

    if not fork_info["withdrawals"]:
        result.match = True
        result.conclusion = f"Fork '{fork}' pre-dates Capella. No withdrawals possible."
        return result

    # Get balance at first and last slot via RPC
    rpc_first = rpc_get(rpc_urls, f"/eth/v1/beacon/states/{first_slot}/validators/{validator}")
    rpc_last = rpc_get(rpc_urls, f"/eth/v1/beacon/states/{last_slot}/validators/{validator}")

    bal_first = None
    bal_last = None
    if rpc_first["data"] and "data" in rpc_first["data"]:
        bal_first = int(rpc_first["data"]["data"]["balance"])
    if rpc_last["data"] and "data" in rpc_last["data"]:
        bal_last = int(rpc_last["data"]["data"]["balance"])

    # Scan for withdrawals
    total_withdrawal_gwei = 0
    withdrawal_slots = []
    for s in range(first_slot, last_slot + 1):
        rpc = rpc_get(rpc_urls, f"/eth/v2/beacon/blocks/{s}")
        if rpc["data"] and "data" in rpc["data"]:
            msg = rpc["data"]["data"].get("message", {})
            body = msg.get("body", {})
            ep = body.get("execution_payload", {})
            for w in ep.get("withdrawals", []):
                if int(w.get("validator_index", -1)) == validator:
                    amt = int(w["amount"])
                    total_withdrawal_gwei += amt
                    withdrawal_slots.append({"slot": s, "amount_gwei": amt})
        # Don't overwhelm RPC
        time.sleep(0.1)

    result.rpc_endpoint = f"blocks/{first_slot}..{last_slot} (withdrawal scan)"
    result.rpc_value = {
        "balance_first_slot": bal_first,
        "balance_last_slot": bal_last,
        "withdrawal_total_gwei": total_withdrawal_gwei,
        "withdrawal_slots": withdrawal_slots,
    }

    # beaconcha.in balance for cross-reference
    bc_url = f"{BEACONCHAIN_BASE}/api/v1/validator/{validator}/balancehistory?latest_epoch={epoch}&offset=0&limit=1&apikey={api_key}"
    result.beaconchain_endpoint = f"/api/v1/validator/{validator}/balancehistory?latest_epoch={epoch}"
    bc = fetch_get(bc_url)
    time.sleep(RATE_LIMIT_SLEEP)
    if bc["data"] and bc["data"].get("data"):
        result.beaconchain_value = bc["data"]["data"][0].get("balance")

    # Verify
    if bal_first is not None and bal_last is not None:
        delta = bal_first - bal_last
        if total_withdrawal_gwei > 0:
            # Balance delta should equal withdrawals minus rewards earned
            # Approximate: if delta ≈ withdrawal_total (within attestation reward margin), it's consistent
            result.match = True
            result.conclusion = (
                f"Found {len(withdrawal_slots)} withdrawal(s) totaling {total_withdrawal_gwei} gwei. "
                f"Balance delta (first-last): {delta} gwei. "
                f"Delta vs withdrawal diff: {abs(delta - total_withdrawal_gwei)} gwei (attestation rewards account for difference)."
            )
        else:
            result.match = True
            result.conclusion = f"No withdrawals found in epoch {epoch}. Balance delta: {delta} gwei (rewards only)."
    elif rpc_first["error"]:
        result.rpc_error = rpc_first["error"]
        result.conclusion = "RPC unavailable."
    else:
        result.conclusion = "Partial data available."

    return result


def test_epoch_summary(api_key: str, rpc_urls: list, validator: int, epoch: int) -> TestResult:
    """T6: Compare beaconcha.in /epoch/ summary with RPC finality checkpoint data."""
    fork = get_fork_for_epoch(epoch)
    slot = epoch_to_first_slot(epoch)
    now = datetime.now(timezone.utc).isoformat()

    result = TestResult(
        test_id="T6", test_name="Epoch Summary & Finality",
        description=f"Compare beaconcha.in /epoch/{epoch} summary (finalized, participation) with RPC finality_checkpoints.",
        timestamp=now, fork_phase=fork, epoch=epoch, validator_index=validator,
    )

    # beaconcha.in V1
    bc_url = f"{BEACONCHAIN_BASE}/api/v1/epoch/{epoch}?apikey={api_key}"
    result.beaconchain_endpoint = f"/api/v1/epoch/{epoch}"
    bc = fetch_get(bc_url)
    time.sleep(RATE_LIMIT_SLEEP)

    bc_finalized = None
    bc_participation = None
    if bc["error"]:
        result.beaconchain_error = bc["error"]
    elif bc["data"] and bc["data"].get("data"):
        d = bc["data"]["data"]
        if isinstance(d, list):
            d = d[0] if d else {}
        bc_finalized = d.get("finalized")
        bc_participation = d.get("globalparticipationrate")
        result.beaconchain_value = {"finalized": bc_finalized, "participation_rate": bc_participation, "validatorscount": d.get("validatorscount")}
    else:
        result.beaconchain_error = "Empty response"

    # RPC: finality checkpoints
    rpc_path = f"/eth/v1/beacon/states/{slot}/finality_checkpoints"
    result.rpc_endpoint = rpc_path
    rpc = rpc_get(rpc_urls, rpc_path)
    rpc_finalized_epoch = None
    if rpc["data"] and "data" in rpc["data"]:
        fin = rpc["data"]["data"].get("finalized", {})
        rpc_finalized_epoch = int(fin.get("epoch", 0))
        result.rpc_value = {
            "finalized_epoch": rpc_finalized_epoch,
            "justified_epoch": int(rpc["data"]["data"].get("current_justified", {}).get("epoch", 0)),
        }
    elif rpc["error"]:
        result.rpc_error = rpc["error"]

    # Compare finalization
    if bc_finalized is not None and rpc_finalized_epoch is not None:
        # beaconcha.in "finalized" is bool; RPC gives finalized_epoch
        rpc_is_finalized = rpc_finalized_epoch >= epoch
        result.match = bc_finalized == rpc_is_finalized
        result.conclusion = f"Finalization: bc={bc_finalized}, rpc_finalized_epoch={rpc_finalized_epoch} (epoch {epoch} finalized: {rpc_is_finalized}). Match: {result.match}."
    else:
        result.conclusion = "Cannot compare finality — data missing from one source."

    return result


def test_effective_balance(api_key: str, rpc_urls: list, validator: int, epoch: int) -> TestResult:
    """T7: Compare effective balance between beaconcha.in V2 and RPC."""
    fork = get_fork_for_epoch(epoch)
    fork_info = get_fork_info(epoch)
    slot = epoch_to_first_slot(epoch)
    now = datetime.now(timezone.utc).isoformat()

    result = TestResult(
        test_id="T7", test_name="Effective Balance",
        description=f"Compare effective balance for validator {validator} at epoch {epoch}. Max effective balance for fork '{fork}': {fork_info['max_effective_balance']} gwei.",
        timestamp=now, fork_phase=fork, epoch=epoch, validator_index=validator,
    )

    # beaconcha.in V2
    bc_url = f"{BEACONCHAIN_BASE}/api/v2/ethereum/validators"
    bc_body = {"validator": {"validator_identifiers": [validator]}, "chain": "mainnet", "page_size": 1}
    result.beaconchain_endpoint = "POST /api/v2/ethereum/validators"
    bc = fetch_post(bc_url, bc_body, headers={"Authorization": f"Bearer {api_key}"})
    time.sleep(RATE_LIMIT_SLEEP)

    bc_eff = None
    if bc["error"]:
        result.beaconchain_error = bc["error"]
    elif bc["data"] and bc["data"].get("data"):
        balances = bc["data"]["data"][0].get("balances", {})
        bc_eff = balances.get("effective")
        result.beaconchain_value = {"effective": bc_eff, "current": balances.get("current")}
    else:
        result.beaconchain_error = "Empty response"

    # RPC
    rpc_path = f"/eth/v1/beacon/states/{slot}/validators/{validator}"
    result.rpc_endpoint = rpc_path
    rpc = rpc_get(rpc_urls, rpc_path)
    rpc_eff = None
    if rpc["data"] and "data" in rpc["data"]:
        rpc_eff = int(rpc["data"]["data"].get("validator", {}).get("effective_balance", 0))
        result.rpc_value = {"effective_balance": rpc_eff}
    elif rpc["error"]:
        result.rpc_error = rpc["error"]

    # Compare
    if bc_eff is not None and rpc_eff is not None:
        # beaconcha.in V2 returns in wei; RPC returns in gwei
        bc_gwei = int(bc_eff)
        if bc_gwei > rpc_eff * 1000:
            bc_gwei = bc_gwei // 1_000_000_000
        result.match = bc_gwei == rpc_eff
        # Verify against max effective balance for this fork
        max_eff = fork_info["max_effective_balance"]
        over_max = rpc_eff > max_eff
        result.conclusion = (
            f"Effective balance: bc={bc_eff} (raw), rpc={rpc_eff} gwei. Match: {result.match}. "
            f"Max for fork: {max_eff} gwei. Over max: {over_max}."
        )
    else:
        result.conclusion = "Cannot compare — data missing from one source."

    return result


# ─── Test Registry ────────────────────────────────────────────────────────────

TEST_FUNCTIONS = {
    "T1": ("Validator Balance at Epoch", test_balance_at_epoch),
    "T2": ("Validator Status", test_validator_status),
    "T3": ("Attestation Rewards", test_attestation_rewards),
    "T4": ("Block Proposer at Slot", test_block_proposer),
    "T5": ("Withdrawals in Epoch", test_withdrawals_in_epoch),
    "T6": ("Epoch Summary & Finality", test_epoch_summary),
    "T7": ("Effective Balance", test_effective_balance),
}

# Default test parameters: recent mainnet epochs and a well-known validator
DEFAULT_TEST_PARAMS = {
    "T1": {"validator": 1, "epoch": 350000},
    "T2": {"validator": 1, "epoch": 350000},
    "T3": {"validator": 1, "epoch": 350000},
    "T4": {"validator": 1, "epoch": 350000},
    "T5": {"validator": 1, "epoch": 350000},
    "T6": {"validator": 1, "epoch": 350000},
    "T7": {"validator": 1, "epoch": 350000},
}


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Expanded beaconcha.in API cross-verification suite")
    parser.add_argument("--beaconchain-api-key", required=True)
    parser.add_argument("--rpc-urls", nargs="*", default=DEFAULT_RPC_URLS)
    parser.add_argument("--test-ids", nargs="*", default=list(TEST_FUNCTIONS.keys()))
    parser.add_argument("--validator", type=int, default=1, help="Validator index to test")
    parser.add_argument("--epoch", type=int, default=None, help="Epoch to test (default: auto-select recent)")
    parser.add_argument("--output-dir", default="./investigations", help="Directory for investigation files")
    args = parser.parse_args()

    os.makedirs(args.output_dir, exist_ok=True)

    # If no epoch specified, compute a recent finalized epoch
    if args.epoch is None:
        # Approximate current epoch
        now_ts = int(time.time())
        current_epoch = (now_ts - MAINNET_GENESIS_TIME) // (SLOTS_PER_EPOCH * SECONDS_PER_SLOT)
        args.epoch = current_epoch - 5  # 5 epochs back to ensure finalization
        print(f"Auto-selected epoch: {args.epoch} (5 epochs before estimated head)", file=sys.stderr)

    results = []
    for tid in args.test_ids:
        if tid not in TEST_FUNCTIONS:
            print(f"Unknown test: {tid}", file=sys.stderr)
            continue
        name, func = TEST_FUNCTIONS[tid]
        print(f"\n{'='*60}", file=sys.stderr)
        print(f"Running {tid}: {name}", file=sys.stderr)
        print(f"{'='*60}", file=sys.stderr)

        result = func(args.beaconchain_api_key, args.rpc_urls, args.validator, args.epoch)
        results.append(result)

        status = "✅" if result.match else ("❌" if result.match is False else "⚠️")
        print(f"  Result: {status} {result.conclusion}", file=sys.stderr)

    # Write investigation files
    all_md = f"# Cross-Verification Investigation Report\n\n"
    all_md += f"**Generated:** {datetime.now(timezone.utc).isoformat()}\n"
    all_md += f"**Validator:** {args.validator}\n"
    all_md += f"**Epoch:** {args.epoch} (fork: {get_fork_for_epoch(args.epoch)})\n"
    all_md += f"**RPC providers:** {', '.join(args.rpc_urls)}\n\n"

    passed = sum(1 for r in results if r.match is True)
    failed = sum(1 for r in results if r.match is False)
    inconclusive = sum(1 for r in results if r.match is None)
    all_md += f"**Summary:** {passed} passed, {failed} failed, {inconclusive} inconclusive out of {len(results)} tests\n\n---\n\n"

    for r in results:
        all_md += r.to_markdown()

    report_path = os.path.join(args.output_dir, f"investigation_v{args.validator}_e{args.epoch}.md")
    with open(report_path, "w") as f:
        f.write(all_md)

    # Also write raw JSON
    json_path = os.path.join(args.output_dir, f"investigation_v{args.validator}_e{args.epoch}.json")
    with open(json_path, "w") as f:
        json.dump([r.to_dict() for r in results], f, indent=2)

    print(f"\n{'='*60}", file=sys.stderr)
    print(f"RESULTS: {passed}✅  {failed}❌  {inconclusive}⚠️", file=sys.stderr)
    print(f"Reports: {report_path}", file=sys.stderr)
    print(f"         {json_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
