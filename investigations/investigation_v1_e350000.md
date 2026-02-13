# Cross-Verification Investigation Report

**Generated:** 2026-02-13T10:00:00Z (template — run verify_all.py for live data)
**Network:** Ethereum Mainnet
**Validator:** 1
**Epoch:** 350000 (fork: deneb, slots 11,200,000–11,200,031)
**RPC providers:** eth-beacon-chain.drpc.org, ethereum-beacon-api.publicnode.com

**Summary:** 7 test cases defined — run with `--beaconchain-api-key` to populate

---

## T1: Validator Balance at Epoch
**Status:** 🔵 PENDING (requires API key)
**Fork phase:** deneb
**Epoch:** 350000 | **Validator:** 1

**Description:** Compare balancehistory balance for validator 1 at epoch 350000 against RPC balance at first slot (11200000) and last slot (11200031).

### Data Comparison

| Source | Endpoint | Value | Status |
|--------|----------|-------|--------|
| beaconcha.in | `GET /api/v1/validator/1/balancehistory?latest_epoch=350000&offset=0&limit=1` | — | 🔵 Pending |
| RPC (first) | `GET /eth/v1/beacon/states/11200000/validators/1` | — | 🔵 Pending |
| RPC (last) | `GET /eth/v1/beacon/states/11200031/validators/1` | — | 🔵 Pending |

### Validation Rules
- beaconcha.in must match either first-slot OR last-slot RPC balance
- If neither matches, investigate mid-epoch withdrawals

### Run Command
```bash
python3 scripts/verify_all.py --beaconchain-api-key YOUR_KEY --validator 1 --epoch 350000 --test-ids T1
```

---

## T2: Validator Status
**Status:** 🔵 PENDING
**Fork phase:** deneb
**Epoch:** 350000 | **Validator:** 1

**Description:** Compare validator 1 status between beaconcha.in V2 validators endpoint and RPC state validators.

### Data Comparison

| Source | Endpoint | Value | Status |
|--------|----------|-------|--------|
| beaconcha.in | `POST /api/v2/ethereum/validators` | — | 🔵 Pending |
| RPC | `GET /eth/v1/beacon/states/11200000/validators/1` → status | — | 🔵 Pending |

### Validation Rules
- Root status must match: active/pending/exited/withdrawal
- Substatus naming may differ (online vs ongoing)

---

## T3: Attestation Rewards
**Status:** 🔵 PENDING
**Fork phase:** deneb (Capella+ required)
**Epoch:** 350000 | **Validator:** 1

**Description:** Compare attestation rewards from beaconcha.in V2 rewards-list vs RPC /eth/v1/beacon/rewards/attestations endpoint.

### Data Comparison

| Source | Endpoint | Value | Status |
|--------|----------|-------|--------|
| beaconcha.in | `POST /api/v2/ethereum/validators/rewards-list` | — (wei) | 🔵 Pending |
| RPC | `POST /eth/v1/beacon/rewards/attestations/350000` | — (gwei) | 🔵 Pending |

### Validation Rules
- beaconcha.in returns in **wei**, RPC in **gwei** — divide bc by 1e9
- Compare head, source, target components individually

---

## T4: Block Proposer at Slot
**Status:** 🔵 PENDING
**Fork phase:** deneb (Bellatrix+ required)
**Epoch:** 350000 | **Validator:** 1

**Description:** Compare block proposer at slot 11200000 between beaconcha.in and RPC.

### Data Comparison

| Source | Endpoint | Value | Status |
|--------|----------|-------|--------|
| beaconcha.in | `GET /api/v1/slot/11200000` | — | 🔵 Pending |
| RPC | `GET /eth/v2/beacon/blocks/11200000` → proposer_index | — | 🔵 Pending |

### Validation Rules
- Proposer index must match exactly
- If slot was missed, RPC returns 404

---

## T5: Withdrawals in Epoch
**Status:** 🔵 PENDING
**Fork phase:** deneb (Capella+ required)
**Epoch:** 350000 | **Validator:** 1

**Description:** Scan all 32 slots of epoch 350000 for withdrawals affecting validator 1. Compare withdrawal sum against balance delta.

### Data Comparison

| Source | Endpoint | Value | Status |
|--------|----------|-------|--------|
| RPC balance (first) | `states/11200000/validators/1` | — | 🔵 Pending |
| RPC balance (last) | `states/11200031/validators/1` | — | 🔵 Pending |
| RPC withdrawals | `blocks/11200000..11200031` scan | — | 🔵 Pending |
| beaconcha.in balance | `balancehistory?latest_epoch=350000` | — | 🔵 Pending |

### Validation Rules
- Withdrawal sum should equal (first_balance - last_balance) ± attestation rewards (~2,000–15,000 gwei)

---

## T6: Epoch Summary & Finality
**Status:** 🔵 PENDING
**Fork phase:** deneb
**Epoch:** 350000 | **Validator:** 1

**Description:** Compare epoch finality between beaconcha.in and RPC finality checkpoints.

### Data Comparison

| Source | Endpoint | Value | Status |
|--------|----------|-------|--------|
| beaconcha.in | `GET /api/v1/epoch/350000` → finalized | — | 🔵 Pending |
| RPC | `GET /eth/v1/beacon/states/11200000/finality_checkpoints` | — | 🔵 Pending |

### Validation Rules
- beaconcha.in `finalized: true` must be consistent with RPC `finalized_epoch >= 350000`

---

## T7: Effective Balance
**Status:** 🔵 PENDING
**Fork phase:** deneb (max effective: 32,000,000,000 gwei)
**Epoch:** 350000 | **Validator:** 1

**Description:** Compare effective balance between beaconcha.in V2 and RPC.

### Data Comparison

| Source | Endpoint | Value | Status |
|--------|----------|-------|--------|
| beaconcha.in | `POST /api/v2/ethereum/validators` → balances.effective | — (wei) | 🔵 Pending |
| RPC | `GET /eth/v1/beacon/states/11200000/validators/1` → effective_balance | — (gwei) | 🔵 Pending |

### Validation Rules
- Must match after unit conversion (bc in wei, RPC in gwei)
- Must not exceed max effective balance for fork phase (32 ETH for Deneb)

---

## How to Run All Tests

```bash
cd beaconchain-verifier

# Single epoch, all 7 tests
python3 scripts/verify_all.py \
  --beaconchain-api-key YOUR_KEY \
  --validator 1 \
  --epoch 350000 \
  --output-dir investigations/

# Randomized historical fork testing (mainnet only)
python3 scripts/historical_fork_test.py \
  --beaconchain-api-key YOUR_KEY \
  --validator 1 \
  --samples-per-fork 2 \
  --seed 42 \
  --output-dir investigations/historical/
```

## Notes

- All tests require both beaconcha.in and RPC network access
- Free beaconcha.in tier: 1 request/second, 1000 requests/month
- Full test suite uses ~10 beaconcha.in calls + ~40 RPC calls per epoch
- Historical fork test at 2 samples/fork × 7 forks × ~7 tests = ~100 test runs
