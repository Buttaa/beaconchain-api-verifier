# Beaconcha.in API Verifier

A Claude Code skill that cross-verifies [beaconcha.in](https://beaconcha.in) API responses against public Ethereum Beacon Node RPC providers. Detects data discrepancies, definition drift, and API changes across all consensus-layer hard fork phases.

## Why This Exists

Beaconcha.in is the most widely used Ethereum validator dashboard, but its API responses are derived data — not the canonical source of truth. This tool independently queries both beaconcha.in and Beacon Node RPCs, then compares the results to surface any inconsistencies.

## Use Cases

- **Validator operators** — Confirm that the balances, rewards, and statuses shown on beaconcha.in match what the beacon chain actually reports.
- **Staking infrastructure teams** — Audit beaconcha.in data before relying on it for dashboards, alerts, or accounting.
- **Withdrawal verification** — Investigate whether beaconcha.in reports epoch balances at the first slot or last slot of an epoch, which matters when withdrawals occur mid-epoch.
- **Historical regression testing** — Run randomized tests across all 7 Ethereum hard fork phases (Phase 0 through Fulu) to detect data drift or API definition changes over time.
- **API integration testing** — Validate that beaconcha.in V1/V2 endpoints return correct data before integrating them into your own tools.
- **Incident investigation** — When a validator balance looks wrong on beaconcha.in, quickly determine whether the issue is on beaconcha.in's side or the RPC's side.

## Test Categories

| ID | Test | What It Compares |
|----|------|-----------------|
| T1 | Validator Balance at Epoch | beaconcha.in balance vs RPC state at first/last slot |
| T2 | Validator Status | Lifecycle status (active/pending/exited/withdrawal) |
| T3 | Attestation Rewards | Reward components (head/source/target) — Capella+ |
| T4 | Block Proposer | Who proposed a given slot — Bellatrix+ |
| T5 | Withdrawals in Epoch | Withdrawal sums vs balance deltas — Capella+ |
| T6 | Epoch Summary & Finality | Finalization status consistency |
| T7 | Effective Balance | Effective balance match (max 2048 ETH post-Pectra) |

## Prerequisites

- Python 3.10+
- `requests` library
- A free beaconcha.in API key ([get one here](https://beaconcha.in/user/api-key-management))

## Installation

```bash
git clone https://github.com/YOUR_USERNAME/beaconchain-verifier.git
cd beaconchain-verifier
pip install requests
```

## Usage

### Run the full 7-test suite for a single epoch

```bash
python scripts/verify_all.py \
  --beaconchain-api-key YOUR_KEY \
  --validator 1 \
  --epoch 350000
```

### Run historical fork regression testing (mainnet only)

```bash
python scripts/historical_fork_test.py \
  --beaconchain-api-key YOUR_KEY \
  --validator 1 \
  --samples-per-fork 2 \
  --seed 42
```

### Verify a single epoch balance

```bash
python scripts/verify_balance.py \
  --network mainnet \
  --validator 1 \
  --epoch 350000 \
  --beaconchain-api-key YOUR_KEY
```

### Batch-verify balances across multiple epochs

```bash
python scripts/batch_verify.py \
  --network mainnet \
  --validator 1 \
  --start-epoch 350000 \
  --end-epoch 350005 \
  --beaconchain-api-key YOUR_KEY
```

### Epoch/slot conversion utilities

```bash
python scripts/epoch_slot_utils.py --epoch 350000
python scripts/epoch_slot_utils.py --slot 11200000
```

## Adding to Claude Desktop as a Skill

This project is designed to be used as a [Claude Code skill](https://docs.anthropic.com/en/docs/claude-code/skills), which lets Claude run the verification scripts on your behalf.

### Setup Steps

1. **Open Claude Code settings.** In your terminal, run:
   ```bash
   claude config
   ```

2. **Add this project as a skill directory.** In your Claude Code configuration (`~/.claude/settings.json`), add the path to this repo under `skills`:
   ```json
   {
     "skills": [
       "/path/to/beaconchain-verifier"
     ]
   }
   ```

3. **Allow network egress.** The skill needs to reach these domains:

   | Domain | Purpose |
   |--------|---------|
   | `beaconcha.in` | beaconcha.in API (mainnet) |
   | `hoodi.beaconcha.in` | beaconcha.in API (Hoodi testnet) |
   | `eth-beacon-chain.drpc.org` | Primary RPC (mainnet) |
   | `eth-beacon-chain-hoodi.drpc.org` | Primary RPC (Hoodi) |
   | `ethereum-beacon-api.publicnode.com` | Fallback RPC (mainnet) |
   | `ethereum-hoodi-beacon-api.publicnode.com` | Fallback RPC (Hoodi) |

   In Claude Desktop: **Settings > Capabilities > Allow network egress > Package managers and specific domains** — add each domain.

4. **Use it.** Ask Claude something like:
   > "Verify beaconcha.in balance for validator 1 at epoch 350000. My API key is ..."

   Claude will run the appropriate script and present a detailed comparison report.

## Scripts Overview

| Script | Purpose |
|--------|---------|
| `scripts/verify_all.py` | Full 7-test suite for one validator at one epoch |
| `scripts/historical_fork_test.py` | Randomized regression testing across all fork phases (mainnet) |
| `scripts/verify_balance.py` | Detailed single-epoch balance investigation |
| `scripts/batch_verify.py` | Multi-epoch balance consistency check |
| `scripts/fork_epochs.py` | Mainnet hard fork epoch registry and utilities |
| `scripts/epoch_slot_utils.py` | Epoch/slot/timestamp conversion helpers |

## Supported Networks

- **Mainnet** — full support including historical fork testing
- **Hoodi** — testnet support
- **Holesky** — testnet support

## Output

Each verification run produces:
- A **Markdown report** with per-test results, raw values, and conclusions
- A **JSON file** with machine-parseable data for further analysis

Reports are written to the `investigations/` directory by default.

## Rate Limits

- **beaconcha.in free tier:** 1 request/second, 1,000 requests/month
- The scripts automatically throttle to stay within limits (1.1s sleep between calls)
- A full 7-test run uses ~10 beaconcha.in calls + ~40 RPC calls

## License

GPL
