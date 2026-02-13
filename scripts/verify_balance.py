#!/usr/bin/env python3
"""
beaconchain-verifier: Cross-verify beaconcha.in epoch balance against Beacon Node RPC.

Usage:
    python3 verify_balance.py \
        --network hoodi \
        --validator 1235383 \
        --epoch 57993 \
        --beaconchain-api-key YOUR_KEY \
        [--rpc-urls URL1 URL2 ...]
"""

import argparse
import json
import sys
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

try:
    import requests
except ImportError:
    print("ERROR: 'requests' library required. Install with: pip install requests", file=sys.stderr)
    sys.exit(1)

# ─── Constants ───────────────────────────────────────────────────────────────

SLOTS_PER_EPOCH = 32

DEFAULT_RPC_URLS = {
    "mainnet": ["https://eth-beacon-chain.drpc.org"],
    "hoodi":   ["https://eth-beacon-chain-hoodi.drpc.org"],
}

BEACONCHAIN_BASE_URLS = {
    "mainnet": "https://beaconcha.in",
    "hoodi":   "https://hoodi.beaconcha.in",
    "holesky": "https://holesky.beaconcha.in",
}

MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds


# ─── Data Classes ────────────────────────────────────────────────────────────

@dataclass
class RPCCall:
    url: str
    status_code: int
    success: bool
    response_excerpt: Optional[dict] = None
    error: Optional[str] = None


@dataclass
class WithdrawalInfo:
    slot: int
    index: int
    validator_index: int
    address: str
    amount_gwei: int


@dataclass
class VerificationReport:
    # Request parameters
    network: str
    validator_index: int
    epoch: int
    first_slot: int
    last_slot: int

    # beaconcha.in data
    beaconchain_endpoint: str = ""
    beaconchain_balance_gwei: Optional[int] = None
    beaconchain_error: Optional[str] = None

    # RPC data
    rpc_calls: list = field(default_factory=list)
    rpc_balance_first_slot_gwei: Optional[int] = None
    rpc_balance_last_slot_gwei: Optional[int] = None
    rpc_withdrawals: list = field(default_factory=list)

    # Derived computation
    withdrawal_total_gwei: int = 0
    expected_balance_after_withdrawal: Optional[int] = None

    # Comparison
    matches_first_slot: Optional[bool] = None
    matches_last_slot: Optional[bool] = None
    likely_definition: str = ""
    conclusion: str = ""
    recommended_next_steps: list = field(default_factory=list)

    def to_dict(self):
        d = asdict(self)
        # Convert WithdrawalInfo and RPCCall objects
        d["rpc_calls"] = [asdict(c) if hasattr(c, "__dataclass_fields__") else c for c in self.rpc_calls]
        d["rpc_withdrawals"] = [asdict(w) if hasattr(w, "__dataclass_fields__") else w for w in self.rpc_withdrawals]
        return d


# ─── HTTP Helpers ────────────────────────────────────────────────────────────

def fetch_with_retry(url: str, headers: Optional[dict] = None, max_retries: int = MAX_RETRIES) -> tuple:
    """
    Fetch a URL with retry on 429/5xx. Returns (status_code, json_response | None, error_msg | None).
    """
    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers=headers or {}, timeout=30)
            if resp.status_code == 200:
                return resp.status_code, resp.json(), None
            elif resp.status_code == 429 or resp.status_code >= 500:
                wait = RETRY_BACKOFF_BASE ** (attempt + 1)
                # Check for ratelimit-reset header
                reset = resp.headers.get("ratelimit-reset")
                if reset:
                    try:
                        wait = max(wait, int(reset))
                    except ValueError:
                        pass
                print(f"  ⏳ {resp.status_code} on attempt {attempt+1}, retrying in {wait}s...", file=sys.stderr)
                time.sleep(wait)
            else:
                return resp.status_code, None, f"HTTP {resp.status_code}: {resp.text[:200]}"
        except requests.RequestException as e:
            if attempt < max_retries - 1:
                wait = RETRY_BACKOFF_BASE ** (attempt + 1)
                print(f"  ⏳ Connection error on attempt {attempt+1}, retrying in {wait}s...", file=sys.stderr)
                time.sleep(wait)
            else:
                return 0, None, f"Connection error: {e}"
    return 0, None, "Max retries exceeded"


# ─── beaconcha.in API ────────────────────────────────────────────────────────

def fetch_beaconchain_balance(base_url: str, api_key: str, validator: int, epoch: int) -> tuple:
    """
    Fetch epoch balance from beaconcha.in V1 balancehistory.
    Returns (balance_gwei | None, endpoint_url, error | None).
    """
    endpoint = f"{base_url}/api/v1/validator/{validator}/balancehistory"
    params = f"?latest_epoch={epoch}&offset=0&limit=1&apikey={api_key}"
    url = endpoint + params
    # Redact API key in display URL
    display_url = endpoint + f"?latest_epoch={epoch}&offset=0&limit=1&apikey=REDACTED"

    status, data, err = fetch_with_retry(url)
    if err:
        return None, display_url, err
    if not data or "data" not in data or not data["data"]:
        return None, display_url, f"Empty response: {json.dumps(data)[:200]}"

    entry = data["data"][0]
    balance = entry.get("balance")
    if balance is None:
        return None, display_url, f"No 'balance' field in response: {json.dumps(entry)[:200]}"

    return int(balance), display_url, None


# ─── Beacon Node RPC API ─────────────────────────────────────────────────────

def fetch_rpc_validator_balance(rpc_urls: list, slot: int, validator: int) -> tuple:
    """
    Fetch validator balance at a specific slot from RPC providers.
    Tries providers in order. Returns (balance_gwei | None, RPCCall, error | None).
    """
    for rpc_base in rpc_urls:
        url = f"{rpc_base.rstrip('/')}/eth/v1/beacon/states/{slot}/validators/{validator}"
        status, data, err = fetch_with_retry(url)

        if err:
            call = RPCCall(url=url, status_code=status, success=False, error=err)
            continue  # try next provider

        if data and "data" in data:
            balance = int(data["data"].get("balance", 0))
            excerpt = {
                "index": data["data"].get("index"),
                "balance": data["data"].get("balance"),
                "status": data["data"].get("status"),
                "effective_balance": data["data"].get("validator", {}).get("effective_balance"),
            }
            call = RPCCall(url=url, status_code=200, success=True, response_excerpt=excerpt)
            return balance, call, None
        else:
            call = RPCCall(url=url, status_code=status, success=False, error=f"Unexpected format: {json.dumps(data)[:200]}")
            continue

    return None, RPCCall(url="(all providers failed)", status_code=0, success=False, error="All RPC providers failed"), "All RPC providers failed"


def fetch_rpc_block_withdrawals(rpc_urls: list, slot: int, validator: int) -> tuple:
    """
    Fetch withdrawals for a specific validator from a specific slot's block.
    Returns (list[WithdrawalInfo], RPCCall | None, error | None).
    """
    withdrawals = []
    for rpc_base in rpc_urls:
        url = f"{rpc_base.rstrip('/')}/eth/v2/beacon/blocks/{slot}"
        status, data, err = fetch_with_retry(url)

        if status == 404:
            # Slot was likely missed (no block produced)
            return [], RPCCall(url=url, status_code=404, success=True, response_excerpt={"note": "no block at slot"}), None

        if err:
            continue

        if data and "data" in data:
            body = data["data"].get("message", {}).get("body", {})
            exec_payload = body.get("execution_payload", {})
            raw_withdrawals = exec_payload.get("withdrawals", [])

            for w in raw_withdrawals:
                if int(w.get("validator_index", -1)) == validator:
                    withdrawals.append(WithdrawalInfo(
                        slot=slot,
                        index=int(w["index"]),
                        validator_index=int(w["validator_index"]),
                        address=w.get("address", ""),
                        amount_gwei=int(w["amount"]),
                    ))

            call = RPCCall(url=url, status_code=200, success=True,
                          response_excerpt={"total_withdrawals_in_block": len(raw_withdrawals),
                                           "matching_validator_withdrawals": len(withdrawals)})
            return withdrawals, call, None

    return [], None, "All RPC providers failed for block query"


def scan_epoch_withdrawals(rpc_urls: list, epoch: int, validator: int, report: VerificationReport) -> list:
    """
    Scan all slots in an epoch for withdrawals affecting a validator.
    Returns list of WithdrawalInfo.
    """
    first_slot = epoch * SLOTS_PER_EPOCH
    last_slot = first_slot + SLOTS_PER_EPOCH - 1
    all_withdrawals = []

    print(f"  🔍 Scanning slots {first_slot}-{last_slot} for withdrawals...", file=sys.stderr)

    for slot in range(first_slot, last_slot + 1):
        wds, call, err = fetch_rpc_block_withdrawals(rpc_urls, slot, validator)
        if call:
            report.rpc_calls.append(call)
        if wds:
            all_withdrawals.extend(wds)
            print(f"    ✅ Withdrawal found at slot {slot}: {sum(w.amount_gwei for w in wds)} gwei", file=sys.stderr)

        # Small delay to avoid rate limits
        time.sleep(0.15)

    return all_withdrawals


# ─── Main Verification Logic ─────────────────────────────────────────────────

def verify_epoch_balance(
    network: str,
    validator: int,
    epoch: int,
    api_key: str,
    rpc_urls: Optional[list] = None,
    scan_withdrawals: bool = True,
) -> VerificationReport:
    """
    Full verification of a beaconcha.in epoch balance against RPC data.
    """
    first_slot = epoch * SLOTS_PER_EPOCH
    last_slot = first_slot + SLOTS_PER_EPOCH - 1

    report = VerificationReport(
        network=network,
        validator_index=validator,
        epoch=epoch,
        first_slot=first_slot,
        last_slot=last_slot,
    )

    if rpc_urls is None:
        rpc_urls = DEFAULT_RPC_URLS.get(network, [])

    beaconchain_base = BEACONCHAIN_BASE_URLS.get(network)
    if not beaconchain_base:
        report.beaconchain_error = f"Unknown network: {network}"
        return report

    # ── Step 1: Fetch beaconcha.in balance ──
    print(f"📡 Fetching beaconcha.in balance for validator {validator}, epoch {epoch}...", file=sys.stderr)
    bc_balance, bc_endpoint, bc_err = fetch_beaconchain_balance(beaconchain_base, api_key, validator, epoch)
    report.beaconchain_endpoint = bc_endpoint
    report.beaconchain_balance_gwei = bc_balance
    report.beaconchain_error = bc_err

    # ── Step 2: Fetch RPC balance at first slot of epoch ──
    print(f"📡 Fetching RPC balance at first slot {first_slot}...", file=sys.stderr)
    bal_first, call_first, err_first = fetch_rpc_validator_balance(rpc_urls, first_slot, validator)
    report.rpc_calls.append(call_first)
    report.rpc_balance_first_slot_gwei = bal_first
    if err_first:
        print(f"  ⚠️  First slot error: {err_first}", file=sys.stderr)

    # ── Step 3: Fetch RPC balance at last slot of epoch ──
    print(f"📡 Fetching RPC balance at last slot {last_slot}...", file=sys.stderr)
    bal_last, call_last, err_last = fetch_rpc_validator_balance(rpc_urls, last_slot, validator)
    report.rpc_calls.append(call_last)
    report.rpc_balance_last_slot_gwei = bal_last
    if err_last:
        print(f"  ⚠️  Last slot error: {err_last}", file=sys.stderr)

    # ── Step 4: Scan for withdrawals (optional) ──
    if scan_withdrawals:
        print(f"📡 Scanning epoch {epoch} for withdrawals...", file=sys.stderr)
        wds = scan_epoch_withdrawals(rpc_urls, epoch, validator, report)
        report.rpc_withdrawals = wds
        report.withdrawal_total_gwei = sum(w.amount_gwei for w in wds)

        if bal_first is not None:
            report.expected_balance_after_withdrawal = bal_first - report.withdrawal_total_gwei

    # ── Step 5: Compare and conclude ──
    _compute_comparison(report)

    return report


def _compute_comparison(report: VerificationReport):
    """Analyze the collected data and produce a conclusion."""
    bc = report.beaconchain_balance_gwei
    first = report.rpc_balance_first_slot_gwei
    last = report.rpc_balance_last_slot_gwei

    if bc is None:
        report.conclusion = "Cannot compare: beaconcha.in data unavailable."
        return

    # Check matches
    if first is not None:
        report.matches_first_slot = (bc == first)
    if last is not None:
        report.matches_last_slot = (bc == last)

    # Determine likely definition
    if report.matches_first_slot and not report.matches_last_slot:
        report.likely_definition = "first_slot_of_epoch"
        report.conclusion = (
            "beaconcha.in balance matches the FIRST slot of the epoch (epoch boundary start). "
            "This is the pre-withdrawal balance."
        )
    elif report.matches_last_slot and not report.matches_first_slot:
        report.likely_definition = "last_slot_of_epoch"
        report.conclusion = (
            "beaconcha.in balance matches the LAST slot of the epoch (end-of-epoch state). "
            "This is the post-withdrawal balance."
        )
    elif report.matches_first_slot and report.matches_last_slot:
        report.likely_definition = "ambiguous_both_match"
        report.conclusion = (
            "beaconcha.in balance matches BOTH first and last slot balances. "
            "No withdrawals occurred in this epoch, so both definitions yield the same value."
        )
    elif first is not None and last is not None:
        # Neither matches
        report.likely_definition = "unknown"
        diff_first = abs(bc - first)
        diff_last = abs(bc - last)
        report.conclusion = (
            f"beaconcha.in balance matches NEITHER slot boundary. "
            f"Difference from first slot: {diff_first} gwei, from last slot: {diff_last} gwei. "
            f"Possible causes: RPC provider lag, beaconcha.in indexing delay, or mid-epoch state reference."
        )

    # Withdrawal analysis
    if report.withdrawal_total_gwei > 0 and first is not None and last is not None:
        delta = first - last
        if delta == report.withdrawal_total_gwei:
            report.conclusion += (
                f" The balance difference between first and last slot ({delta} gwei) "
                f"exactly matches the total withdrawal amount ({report.withdrawal_total_gwei} gwei), "
                f"confirming a partial withdrawal occurred in this epoch."
            )

    # Recommended next steps
    report.recommended_next_steps = [
        "Log both first-slot and last-slot balances for each epoch to detect definition changes.",
        "File a beaconcha.in support ticket asking for documentation of the epoch balance definition.",
        "In your indexer, compute balance at BOTH epoch boundaries and store both values.",
        "For epochs with withdrawals, note that first_slot != last_slot and handle accordingly.",
        "Consider using the beaconcha.in V2 balance-list endpoint which may have clearer semantics.",
    ]


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Cross-verify beaconcha.in epoch balance against Beacon Node RPC",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 verify_balance.py --network hoodi --validator 1235383 --epoch 57993 --beaconchain-api-key YOUR_KEY
  python3 verify_balance.py --network mainnet --validator 42 --epoch 300000 --beaconchain-api-key KEY --rpc-urls https://my-node.example.com
        """,
    )
    parser.add_argument("--network", required=True, choices=["mainnet", "hoodi", "holesky"],
                       help="Ethereum network")
    parser.add_argument("--validator", required=True, type=int,
                       help="Validator index")
    parser.add_argument("--epoch", required=True, type=int,
                       help="Epoch number to verify")
    parser.add_argument("--beaconchain-api-key", required=True,
                       help="beaconcha.in API key")
    parser.add_argument("--rpc-urls", nargs="*", default=None,
                       help="Override default RPC provider URLs")
    parser.add_argument("--skip-withdrawal-scan", action="store_true",
                       help="Skip scanning all 32 slots for withdrawals (faster)")
    parser.add_argument("--output", default=None,
                       help="Output file path (default: stdout)")

    args = parser.parse_args()

    report = verify_epoch_balance(
        network=args.network,
        validator=args.validator,
        epoch=args.epoch,
        api_key=args.beaconchain_api_key,
        rpc_urls=args.rpc_urls,
        scan_withdrawals=not args.skip_withdrawal_scan,
    )

    output_json = json.dumps(report.to_dict(), indent=2)

    if args.output:
        with open(args.output, "w") as f:
            f.write(output_json)
        print(f"\n✅ Report saved to {args.output}", file=sys.stderr)
    else:
        print(output_json)

    # Print human-readable summary to stderr
    print("\n" + "=" * 70, file=sys.stderr)
    print("VERIFICATION SUMMARY", file=sys.stderr)
    print("=" * 70, file=sys.stderr)
    print(f"Network:    {report.network}", file=sys.stderr)
    print(f"Validator:  {report.validator_index}", file=sys.stderr)
    print(f"Epoch:      {report.epoch} (slots {report.first_slot}-{report.last_slot})", file=sys.stderr)
    print(f"", file=sys.stderr)
    print(f"beaconcha.in balance:     {report.beaconchain_balance_gwei} gwei", file=sys.stderr)
    print(f"RPC balance (first slot): {report.rpc_balance_first_slot_gwei} gwei", file=sys.stderr)
    print(f"RPC balance (last slot):  {report.rpc_balance_last_slot_gwei} gwei", file=sys.stderr)
    print(f"Total withdrawals:        {report.withdrawal_total_gwei} gwei ({len(report.rpc_withdrawals)} txns)", file=sys.stderr)
    print(f"", file=sys.stderr)
    print(f"Matches first slot: {report.matches_first_slot}", file=sys.stderr)
    print(f"Matches last slot:  {report.matches_last_slot}", file=sys.stderr)
    print(f"Likely definition:  {report.likely_definition}", file=sys.stderr)
    print(f"", file=sys.stderr)
    print(f"CONCLUSION: {report.conclusion}", file=sys.stderr)
    print("=" * 70, file=sys.stderr)

    return 0 if (report.matches_first_slot or report.matches_last_slot) else 1


if __name__ == "__main__":
    sys.exit(main())
