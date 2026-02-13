---
name: beaconchain-verifier
description: Cross-verify beaconcha.in API responses against public Ethereum consensus RPC providers (Beacon Node APIs). Use when the user wants to validate beaconcha.in data, compare epoch balances, investigate discrepancies, check withdrawal data, or audit beaconcha.in API correctness. Also use for historical fork-phase testing and regression detection across Ethereum hard forks.
---

# Beaconcha.in API Verifier Skill (Expanded)

Automated cross-verification of beaconcha.in API data against public Ethereum Beacon Node REST APIs. Covers 7 test categories across all mainnet consensus-layer fork phases.

## CRITICAL OPERATING PRINCIPLE

**NEVER trust user-reported values.** Always:
1. Call beaconcha.in yourself first.
2. Call the RPC provider(s) yourself.
3. Only then compare the two and draw conclusions.

If either API is unreachable, state this explicitly. Conclusions without independent verification are **unverified hypotheses**.

## Prerequisites

- Python 3.10+ with `requests`
- beaconcha.in API key (free: https://beaconcha.in/user/api-key-management)
- Network access to beaconcha.in AND at least one Beacon Node RPC provider

## Network Access (Claude Desktop)

These domains must be on the egress allowlist:

| Domain | Purpose |
|--------|---------|
| `beaconcha.in` | beaconcha.in API (mainnet) |
| `hoodi.beaconcha.in` | beaconcha.in API (Hoodi testnet) |
| `eth-beacon-chain.drpc.org` | Primary RPC (mainnet) |
| `eth-beacon-chain-hoodi.drpc.org` | Primary RPC (Hoodi) |
| `ethereum-beacon-api.publicnode.com` | Fallback RPC (mainnet) |
| `ethereum-hoodi-beacon-api.publicnode.com` | Fallback RPC (Hoodi) |

**To add domains:** claude.ai > Admin Settings (Team/Enterprise) or Settings (Pro) > Capabilities > Allow network egress > Package managers and specific domains > Add each domain.

## Test Categories

| ID | Test | beaconcha.in Endpoint | RPC Endpoint | Fork Req |
|----|------|----------------------|--------------|----------|
| T1 | Validator Balance at Epoch | `GET /api/v1/validator/{id}/balancehistory` | `GET /eth/v1/beacon/states/{slot}/validators/{id}` | All |
| T2 | Validator Status | `POST /api/v2/ethereum/validators` | `GET /eth/v1/beacon/states/{slot}/validators/{id}` | All |
| T3 | Attestation Rewards | `POST /api/v2/ethereum/validators/rewards-list` | `POST /eth/v1/beacon/rewards/attestations/{epoch}` | Capella+ |
| T4 | Block Proposer at Slot | `GET /api/v1/slot/{slot}` | `GET /eth/v2/beacon/blocks/{slot}` | Bellatrix+ |
| T5 | Withdrawals in Epoch | Balance delta + block scan | `GET /eth/v2/beacon/blocks/{slot}` withdrawals | Capella+ |
| T6 | Epoch Summary & Finality | `GET /api/v1/epoch/{epoch}` | `GET /eth/v1/beacon/states/{slot}/finality_checkpoints` | All |
| T7 | Effective Balance | `POST /api/v2/ethereum/validators` | `GET /eth/v1/beacon/states/{slot}/validators/{id}` | All |

## Mainnet Hard Fork Epoch Registry

| Fork | Start Epoch | End Epoch | Date | Key Feature |
|------|------------|-----------|------|-------------|
| Phase 0 | 0 | 74,239 | 2020-12-01 | Beacon Chain launch |
| Altair | 74,240 | 144,895 | 2021-10-27 | Sync committees |
| Bellatrix | 144,896 | 194,047 | 2022-09-06 | The Merge prep |
| Capella | 194,048 | 269,567 | 2023-04-12 | Withdrawals enabled |
| Deneb | 269,568 | 364,031 | 2024-03-13 | Proto-danksharding |
| Electra | 364,032 | 411,391 | 2025-05-07 | MaxEB 2048 ETH |
| Fulu | 411,392 | ongoing | 2025-12-03 | PeerDAS |

Source: ethereum/consensus-specs configs/mainnet.yaml, EF blog announcements.

## Scripts

### `scripts/verify_all.py` — Full 7-test suite for one epoch/validator
```bash
python3 scripts/verify_all.py --beaconchain-api-key KEY --validator 1 --epoch 350000
```

### `scripts/historical_fork_test.py` — Randomized cross-fork regression (MAINNET ONLY)
```bash
python3 scripts/historical_fork_test.py --beaconchain-api-key KEY --validator 1 --samples-per-fork 2 --seed 42
```

### `scripts/fork_epochs.py` — Fork epoch registry and utilities
### `scripts/verify_balance.py` — Single-epoch balance verification (v1)
### `scripts/batch_verify.py` — Multi-epoch balance drift detection (v1)
### `scripts/epoch_slot_utils.py` — Epoch/slot/timestamp conversions (v1)

## Validation Rules

- **T1 Balance:** Must match either first-slot OR last-slot RPC balance
- **T2 Status:** Root category must match (active/pending/exited/withdrawal)
- **T3 Rewards:** beaconcha.in returns wei, RPC returns gwei — auto-converted
- **T4 Proposer:** Must match exactly; missed slots = RPC 404
- **T5 Withdrawals:** Sum must equal balance delta ± attestation rewards
- **T6 Finality:** Boolean consistent with RPC finalized_epoch >= epoch
- **T7 Effective Balance:** Must match; post-Pectra max = 2048 ETH

## Investigation Output

Each run produces a markdown report and JSON file with per-test details including timestamps, raw values, match status, discrepancies, and conclusions.
