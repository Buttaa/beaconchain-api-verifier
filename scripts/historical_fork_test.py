#!/usr/bin/env python3
"""
Randomized Historical Fork-Phase Testing for Ethereum Mainnet.

For each consensus-layer hard fork phase, randomly selects 1-2 epochs and
runs the full verification suite against them. This detects:
  - Definition drift across fork boundaries
  - Historical data correctness in beaconcha.in
  - Fork-specific feature handling (e.g., withdrawals only post-Capella)

MAINNET ONLY. This script is intentionally restricted to Ethereum mainnet.

Usage:
    python3 historical_fork_test.py \
        --beaconchain-api-key KEY \
        [--rpc-urls URL ...] \
        [--validator 1] \
        [--samples-per-fork 2] \
        [--output-dir investigations/historical]
"""

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timezone

from fork_epochs import (
    FORK_EPOCHS, FORK_FEATURES, get_fork_for_epoch, get_fork_info,
    epoch_to_first_slot, epoch_to_last_slot, epoch_to_timestamp,
    SLOTS_PER_EPOCH, SECONDS_PER_SLOT, MAINNET_GENESIS_TIME,
)
from verify_all import (
    test_balance_at_epoch, test_validator_status, test_epoch_summary,
    test_effective_balance, test_withdrawals_in_epoch, test_attestation_rewards,
    test_block_proposer, TestResult, RATE_LIMIT_SLEEP,
    DEFAULT_RPC_URLS,
)

# Which tests to run per fork phase
FORK_TEST_MATRIX = {
    "phase0":    ["T1", "T2", "T6", "T7"],
    "altair":    ["T1", "T2", "T6", "T7"],
    "bellatrix": ["T1", "T2", "T4", "T6", "T7"],
    "capella":   ["T1", "T2", "T3", "T4", "T5", "T6", "T7"],
    "deneb":     ["T1", "T2", "T3", "T4", "T5", "T6", "T7"],
    "electra":   ["T1", "T2", "T3", "T4", "T5", "T6", "T7"],
    "fulu":      ["T1", "T2", "T3", "T4", "T5", "T6", "T7"],
}

TEST_DISPATCH = {
    "T1": test_balance_at_epoch,
    "T2": test_validator_status,
    "T3": test_attestation_rewards,
    "T4": test_block_proposer,
    "T5": test_withdrawals_in_epoch,
    "T6": test_epoch_summary,
    "T7": test_effective_balance,
}


def get_current_mainnet_epoch() -> int:
    now_ts = int(time.time())
    return (now_ts - MAINNET_GENESIS_TIME) // (SLOTS_PER_EPOCH * SECONDS_PER_SLOT)


def sample_epochs_for_fork(fork: str, samples: int, current_epoch: int) -> list:
    info = FORK_EPOCHS[fork]
    start = info["start_epoch"]
    end = info["end_epoch"]
    if end is None or end > current_epoch:
        end = current_epoch - 2
    if end <= start:
        return [start]

    epochs = []
    boundary_epoch = min(start + random.randint(1, min(10, end - start)), end)
    epochs.append(boundary_epoch)

    if samples >= 2 and end - start > 20:
        mid_start = start + (end - start) // 4
        mid_end = start + 3 * (end - start) // 4
        mid_epoch = random.randint(mid_start, mid_end)
        if mid_epoch not in epochs:
            epochs.append(mid_epoch)

    return epochs[:samples]


def run_historical_tests(api_key, rpc_urls, validator, samples_per_fork, output_dir, seed=None):
    if seed is not None:
        random.seed(seed)

    current_epoch = get_current_mainnet_epoch()
    print(f"Current estimated epoch: {current_epoch}", file=sys.stderr)
    print(f"Validator: {validator}, Samples/fork: {samples_per_fork}, Seed: {seed}", file=sys.stderr)

    os.makedirs(output_dir, exist_ok=True)

    all_results = []
    fork_summaries = {}

    for fork, info in FORK_EPOCHS.items():
        if info["start_epoch"] > current_epoch:
            print(f"\n  Skipping {info['name']} (not yet active)", file=sys.stderr)
            continue

        print(f"\n{'='*70}", file=sys.stderr)
        print(f"FORK: {info['name']} (epochs {info['start_epoch']}–{info['end_epoch'] or 'ongoing'})", file=sys.stderr)
        print(f"{'='*70}", file=sys.stderr)

        epochs = sample_epochs_for_fork(fork, samples_per_fork, current_epoch)
        tests_for_fork = FORK_TEST_MATRIX.get(fork, ["T1", "T2"])
        fork_results = []

        for epoch in epochs:
            print(f"\n  Epoch {epoch} (slot {epoch_to_first_slot(epoch)})", file=sys.stderr)
            for tid in tests_for_fork:
                if tid not in TEST_DISPATCH:
                    continue
                func = TEST_DISPATCH[tid]
                print(f"    {tid}...", end=" ", file=sys.stderr)
                try:
                    result = func(api_key, rpc_urls, validator, epoch)
                    status = "PASS" if result.match else ("FAIL" if result.match is False else "???")
                    print(f"{status}: {result.conclusion[:80]}", file=sys.stderr)
                except Exception as e:
                    result = TestResult(
                        test_id=tid, test_name=f"EXCEPTION",
                        description=str(e),
                        timestamp=datetime.now(timezone.utc).isoformat(),
                        fork_phase=fork, epoch=epoch, validator_index=validator,
                        conclusion=f"Exception: {e}",
                    )
                    print(f"ERROR: {e}", file=sys.stderr)

                fork_results.append(result)
                all_results.append(result)
                time.sleep(RATE_LIMIT_SLEEP)

        passed = sum(1 for r in fork_results if r.match is True)
        failed = sum(1 for r in fork_results if r.match is False)
        inconclusive = sum(1 for r in fork_results if r.match is None)
        fork_summaries[fork] = {
            "name": info["name"], "epochs_tested": epochs,
            "tests_run": len(fork_results),
            "passed": passed, "failed": failed, "inconclusive": inconclusive,
        }

    # Generate report
    report = _generate_report(all_results, fork_summaries, validator, current_epoch, seed)
    report_path = os.path.join(output_dir, "historical_fork_test_report.md")
    with open(report_path, "w") as f:
        f.write(report)

    json_path = os.path.join(output_dir, "historical_fork_test_results.json")
    with open(json_path, "w") as f:
        json.dump({
            "metadata": {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "validator": validator, "current_epoch": current_epoch,
                "seed": seed, "rpc_urls": rpc_urls,
            },
            "fork_summaries": fork_summaries,
            "results": [r.to_dict() for r in all_results],
        }, f, indent=2)

    # Summary
    total_p = sum(s["passed"] for s in fork_summaries.values())
    total_f = sum(s["failed"] for s in fork_summaries.values())
    total_i = sum(s["inconclusive"] for s in fork_summaries.values())
    print(f"\nTOTAL: {total_p} passed, {total_f} failed, {total_i} inconclusive", file=sys.stderr)
    print(f"Reports: {report_path}\n         {json_path}", file=sys.stderr)
    return fork_summaries


def _generate_report(results, fork_summaries, validator, current_epoch, seed):
    lines = [
        "# Historical Fork-Phase Verification Report",
        "", f"**Generated:** {datetime.now(timezone.utc).isoformat()}",
        f"**Network:** Ethereum Mainnet (ONLY)",
        f"**Validator:** {validator}",
        f"**Current epoch:** ~{current_epoch}",
        f"**Random seed:** {seed}",
        "", "## Summary by Fork Phase", "",
        "| Fork | Epochs Tested | Tests | Passed | Failed | Inconclusive |",
        "|------|--------------|-------|--------|--------|-------------|",
    ]
    for fork, s in fork_summaries.items():
        epochs_str = ", ".join(str(e) for e in s["epochs_tested"])
        lines.append(f"| {s['name']} | {epochs_str} | {s['tests_run']} | {s['passed']} | {s['failed']} | {s['inconclusive']} |")

    lines += ["", "## Detailed Results", ""]
    for r in results:
        lines.append(r.to_markdown())

    lines += [
        "## Notes", "",
        "- Restricted to Ethereum mainnet by design.",
        "- One epoch sampled near each fork boundary, one mid-phase.",
        "- Pre-Capella: no withdrawal tests. Pre-Bellatrix: no block proposer tests.",
        "- Old epochs may not be served by all public RPC providers.",
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Randomized historical fork-phase testing (MAINNET ONLY)")
    parser.add_argument("--beaconchain-api-key", required=True)
    parser.add_argument("--rpc-urls", nargs="*", default=DEFAULT_RPC_URLS)
    parser.add_argument("--validator", type=int, default=1)
    parser.add_argument("--samples-per-fork", type=int, default=2)
    parser.add_argument("--output-dir", default="./investigations/historical")
    parser.add_argument("--seed", type=int, default=None)
    args = parser.parse_args()
    run_historical_tests(
        api_key=args.beaconchain_api_key, rpc_urls=args.rpc_urls,
        validator=args.validator, samples_per_fork=args.samples_per_fork,
        output_dir=args.output_dir, seed=args.seed,
    )


if __name__ == "__main__":
    main()
