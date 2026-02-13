#!/usr/bin/env python3
"""
Batch verification of beaconcha.in epoch balances across a range of epochs.
Useful for detecting whether the balance definition is consistently first-slot or last-slot.

Usage:
    python3 batch_verify.py \
        --network hoodi \
        --validator 1235383 \
        --start-epoch 57990 \
        --end-epoch 57995 \
        --beaconchain-api-key YOUR_KEY \
        [--rpc-urls URL1 URL2 ...]
"""

import argparse
import json
import sys
import time
from verify_balance import (
    fetch_beaconchain_balance,
    fetch_rpc_validator_balance,
    BEACONCHAIN_BASE_URLS,
    DEFAULT_RPC_URLS,
    SLOTS_PER_EPOCH,
)


def batch_verify(
    network: str,
    validator: int,
    start_epoch: int,
    end_epoch: int,
    api_key: str,
    rpc_urls: list = None,
) -> list:
    """Verify epoch balances across a range and report which definition matches."""

    if rpc_urls is None:
        rpc_urls = DEFAULT_RPC_URLS.get(network, [])

    beaconchain_base = BEACONCHAIN_BASE_URLS.get(network)
    if not beaconchain_base:
        print(f"ERROR: Unknown network: {network}", file=sys.stderr)
        return []

    results = []

    for epoch in range(start_epoch, end_epoch + 1):
        first_slot = epoch * SLOTS_PER_EPOCH
        last_slot = first_slot + SLOTS_PER_EPOCH - 1

        print(f"\n--- Epoch {epoch} (slots {first_slot}-{last_slot}) ---", file=sys.stderr)

        # Fetch beaconcha.in balance
        bc_bal, _, bc_err = fetch_beaconchain_balance(beaconchain_base, api_key, validator, epoch)
        if bc_err:
            print(f"  beaconcha.in error: {bc_err}", file=sys.stderr)

        # Fetch RPC balances
        rpc_first, _, err_first = fetch_rpc_validator_balance(rpc_urls, first_slot, validator)
        rpc_last, _, err_last = fetch_rpc_validator_balance(rpc_urls, last_slot, validator)

        # Compare
        matches_first = bc_bal == rpc_first if (bc_bal is not None and rpc_first is not None) else None
        matches_last = bc_bal == rpc_last if (bc_bal is not None and rpc_last is not None) else None

        delta = None
        if rpc_first is not None and rpc_last is not None:
            delta = rpc_first - rpc_last  # positive = withdrawal occurred

        result = {
            "epoch": epoch,
            "beaconchain_gwei": bc_bal,
            "rpc_first_slot_gwei": rpc_first,
            "rpc_last_slot_gwei": rpc_last,
            "first_last_delta_gwei": delta,
            "matches_first_slot": matches_first,
            "matches_last_slot": matches_last,
            "has_withdrawal": delta is not None and delta > 0,
        }
        results.append(result)

        print(f"  bc={bc_bal}  first={rpc_first}  last={rpc_last}  "
              f"Δ={delta}  match_first={matches_first}  match_last={matches_last}",
              file=sys.stderr)

        # Rate limit courtesy
        time.sleep(1.5)  # beaconcha.in free tier = 1 req/sec

    return results


def print_summary(results: list):
    """Print a summary table."""
    print("\n" + "=" * 90)
    print(f"{'Epoch':>8}  {'bc.in':>15}  {'RPC first':>15}  {'RPC last':>15}  "
          f"{'Δ':>10}  {'Match':>12}")
    print("-" * 90)

    first_matches = 0
    last_matches = 0
    withdrawal_epochs = 0

    for r in results:
        match_str = ""
        if r["matches_first_slot"] and r["matches_last_slot"]:
            match_str = "BOTH"
        elif r["matches_first_slot"]:
            match_str = "FIRST ◀"
            first_matches += 1
        elif r["matches_last_slot"]:
            match_str = "LAST ◀"
            last_matches += 1
        else:
            match_str = "NEITHER ⚠"

        if r["has_withdrawal"]:
            withdrawal_epochs += 1

        print(f"{r['epoch']:>8}  {r['beaconchain_gwei'] or 'N/A':>15}  "
              f"{r['rpc_first_slot_gwei'] or 'N/A':>15}  "
              f"{r['rpc_last_slot_gwei'] or 'N/A':>15}  "
              f"{r['first_last_delta_gwei'] or 0:>10}  {match_str:>12}")

    print("=" * 90)
    print(f"\nSummary across {len(results)} epochs:")
    print(f"  Epochs with withdrawals:    {withdrawal_epochs}")
    print(f"  Matched first slot only:    {first_matches}")
    print(f"  Matched last slot only:     {last_matches}")

    if last_matches > first_matches:
        print(f"\n  → beaconcha.in is currently using LAST SLOT OF EPOCH definition")
    elif first_matches > last_matches:
        print(f"\n  → beaconcha.in is currently using FIRST SLOT OF EPOCH definition")
    else:
        print(f"\n  → Inconclusive (try epochs with withdrawals for disambiguation)")


def main():
    parser = argparse.ArgumentParser(description="Batch verify beaconcha.in epoch balances")
    parser.add_argument("--network", required=True, choices=["mainnet", "hoodi", "holesky"])
    parser.add_argument("--validator", required=True, type=int)
    parser.add_argument("--start-epoch", required=True, type=int)
    parser.add_argument("--end-epoch", required=True, type=int)
    parser.add_argument("--beaconchain-api-key", required=True)
    parser.add_argument("--rpc-urls", nargs="*", default=None)
    parser.add_argument("--output-json", default=None, help="Save raw results as JSON")

    args = parser.parse_args()

    results = batch_verify(
        network=args.network,
        validator=args.validator,
        start_epoch=args.start_epoch,
        end_epoch=args.end_epoch,
        api_key=args.beaconchain_api_key,
        rpc_urls=args.rpc_urls,
    )

    print_summary(results)

    if args.output_json:
        with open(args.output_json, "w") as f:
            json.dump(results, f, indent=2)
        print(f"\nRaw results saved to {args.output_json}")


if __name__ == "__main__":
    main()
