#!/usr/bin/env python3
"""
Ethereum mainnet consensus-layer hard fork epoch boundaries.

Source of truth: ethereum/consensus-specs configs/mainnet.yaml
Cross-referenced with: ethereum.org/en/history, EF blog announcements.

Fusaka slot from: blog.ethereum.org (slot 13164544 → epoch 411392)
"""

SLOTS_PER_EPOCH = 32
SECONDS_PER_SLOT = 12
MAINNET_GENESIS_TIME = 1606824023  # Dec 1, 2020, 12:00:23 UTC

# ── Consensus-layer fork activation epochs (mainnet) ──────────────────────
# Each fork activates at the FIRST SLOT of its activation epoch.
FORK_EPOCHS = {
    "phase0":    {"start_epoch": 0,      "end_epoch": 74239,  "date": "2020-12-01", "name": "Phase 0 (Genesis)"},
    "altair":    {"start_epoch": 74240,  "end_epoch": 144895, "date": "2021-10-27", "name": "Altair"},
    "bellatrix": {"start_epoch": 144896, "end_epoch": 194047, "date": "2022-09-06", "name": "Bellatrix (pre-Merge)"},
    "capella":   {"start_epoch": 194048, "end_epoch": 269567, "date": "2023-04-12", "name": "Capella (Shapella)"},
    "deneb":     {"start_epoch": 269568, "end_epoch": 364031, "date": "2024-03-13", "name": "Deneb (Dencun)"},
    "electra":   {"start_epoch": 364032, "end_epoch": 411391, "date": "2025-05-07", "name": "Electra (Pectra)"},
    "fulu":      {"start_epoch": 411392, "end_epoch": None,   "date": "2025-12-03", "name": "Fulu (Fusaka)"},
}

# Features available per fork that affect verification logic
FORK_FEATURES = {
    "phase0":    {"withdrawals": False, "sync_committees": False, "execution_payload": False, "max_effective_balance": 32_000_000_000},
    "altair":    {"withdrawals": False, "sync_committees": True,  "execution_payload": False, "max_effective_balance": 32_000_000_000},
    "bellatrix": {"withdrawals": False, "sync_committees": True,  "execution_payload": True,  "max_effective_balance": 32_000_000_000},
    "capella":   {"withdrawals": True,  "sync_committees": True,  "execution_payload": True,  "max_effective_balance": 32_000_000_000},
    "deneb":     {"withdrawals": True,  "sync_committees": True,  "execution_payload": True,  "max_effective_balance": 32_000_000_000},
    "electra":   {"withdrawals": True,  "sync_committees": True,  "execution_payload": True,  "max_effective_balance": 2_048_000_000_000},
    "fulu":      {"withdrawals": True,  "sync_committees": True,  "execution_payload": True,  "max_effective_balance": 2_048_000_000_000},
}


def get_fork_for_epoch(epoch: int) -> str:
    """Return the fork name active at a given epoch."""
    for fork, info in reversed(list(FORK_EPOCHS.items())):
        if epoch >= info["start_epoch"]:
            return fork
    return "phase0"


def get_fork_info(epoch: int) -> dict:
    """Return full fork info dict for a given epoch."""
    fork = get_fork_for_epoch(epoch)
    return {**FORK_EPOCHS[fork], "fork": fork, **FORK_FEATURES[fork]}


def epoch_to_first_slot(epoch: int) -> int:
    return epoch * SLOTS_PER_EPOCH


def epoch_to_last_slot(epoch: int) -> int:
    return (epoch + 1) * SLOTS_PER_EPOCH - 1


def epoch_to_timestamp(epoch: int) -> int:
    return MAINNET_GENESIS_TIME + epoch_to_first_slot(epoch) * SECONDS_PER_SLOT


def list_forks():
    """Print all forks with epoch ranges."""
    for fork, info in FORK_EPOCHS.items():
        end = info["end_epoch"] or "ongoing"
        features = FORK_FEATURES[fork]
        flags = []
        if features["withdrawals"]:
            flags.append("withdrawals")
        if features["sync_committees"]:
            flags.append("sync_committees")
        if features["execution_payload"]:
            flags.append("execution_payload")
        print(f"  {info['name']:30s}  epochs {info['start_epoch']:>7d} – {str(end):>7s}  ({info['date']})  [{', '.join(flags)}]")


if __name__ == "__main__":
    print("Ethereum Mainnet Consensus-Layer Fork Epochs")
    print("=" * 100)
    list_forks()
