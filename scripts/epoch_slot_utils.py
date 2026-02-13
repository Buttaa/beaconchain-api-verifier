#!/usr/bin/env python3
"""
Epoch/slot conversion utilities for the Beacon Chain.

Usage:
    python3 epoch_slot_utils.py --epoch 57993
    python3 epoch_slot_utils.py --slot 1855776
    python3 epoch_slot_utils.py --epoch 57993 --timestamp --genesis-time 1742212800
"""

import argparse
from datetime import datetime, timezone

SLOTS_PER_EPOCH = 32
SECONDS_PER_SLOT = 12

# Known genesis times (Unix timestamps)
GENESIS_TIMES = {
    "mainnet": 1606824023,
    "hoodi":   1742212800,   # approximate — verify for your deployment
    "holesky": 1695902400,
}


def epoch_to_slots(epoch: int) -> tuple:
    """Return (first_slot, last_slot) for a given epoch."""
    first = epoch * SLOTS_PER_EPOCH
    last = first + SLOTS_PER_EPOCH - 1
    return first, last


def slot_to_epoch(slot: int) -> int:
    """Return the epoch containing a given slot."""
    return slot // SLOTS_PER_EPOCH


def slot_to_timestamp(slot: int, genesis_time: int) -> int:
    """Return the Unix timestamp of a slot."""
    return genesis_time + slot * SECONDS_PER_SLOT


def timestamp_to_slot(ts: int, genesis_time: int) -> int:
    """Return the nearest slot for a Unix timestamp."""
    return max(0, (ts - genesis_time) // SECONDS_PER_SLOT)


def main():
    parser = argparse.ArgumentParser(description="Epoch/slot conversion utility")
    parser.add_argument("--epoch", type=int, help="Convert epoch to slot range")
    parser.add_argument("--slot", type=int, help="Convert slot to epoch")
    parser.add_argument("--timestamp", action="store_true", help="Also show timestamps")
    parser.add_argument("--genesis-time", type=int, default=None,
                       help="Genesis time (Unix). Defaults based on --network")
    parser.add_argument("--network", default="mainnet", choices=["mainnet", "hoodi", "holesky"])

    args = parser.parse_args()
    genesis = args.genesis_time or GENESIS_TIMES.get(args.network, 0)

    if args.epoch is not None:
        first, last = epoch_to_slots(args.epoch)
        print(f"Epoch {args.epoch}:")
        print(f"  First slot: {first}")
        print(f"  Last slot:  {last}")
        if args.timestamp and genesis:
            ts_first = slot_to_timestamp(first, genesis)
            ts_last = slot_to_timestamp(last, genesis)
            print(f"  First slot time: {datetime.fromtimestamp(ts_first, tz=timezone.utc).isoformat()}")
            print(f"  Last slot time:  {datetime.fromtimestamp(ts_last, tz=timezone.utc).isoformat()}")

    if args.slot is not None:
        ep = slot_to_epoch(args.slot)
        first, last = epoch_to_slots(ep)
        pos = args.slot - first
        print(f"Slot {args.slot}:")
        print(f"  Epoch: {ep}")
        print(f"  Position in epoch: {pos}/{SLOTS_PER_EPOCH - 1}")
        print(f"  Epoch range: {first}-{last}")
        if args.timestamp and genesis:
            ts = slot_to_timestamp(args.slot, genesis)
            print(f"  Slot time: {datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()}")


if __name__ == "__main__":
    main()
