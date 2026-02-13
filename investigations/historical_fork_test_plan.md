# Historical Fork-Phase Verification Report

**Generated:** 2026-02-13T10:00:00Z (template — run historical_fork_test.py for live data)
**Network:** Ethereum Mainnet (ONLY)
**Validator:** 1
**Random seed:** 42

## Test Plan: Sampled Epochs per Fork Phase

| Fork | Epochs Sampled | Tests Applied | Rationale |
|------|---------------|---------------|-----------|
| Phase 0 (Genesis) | 2, 20198 | T1 T2 T6 T7 | No withdrawals, no sync committees. Boundary + mid-phase. |
| Altair | 74245, 107952 | T1 T2 T6 T7 | Sync committees added but pre-merge. Near boundary + mid. |
| Bellatrix | 144900, 161755 | T1 T2 T4 T6 T7 | Post-merge, execution payload. Block proposer test added. |
| Capella | 194050, 248668 | T1-T7 (all) | Withdrawals enabled. Full suite. Near boundary + mid. |
| Deneb | 269570, 331881 | T1-T7 (all) | Proto-danksharding era. Full suite. |
| Electra | 364039, 376912 | T1-T7 (all) | MaxEB 2048 ETH. Full suite. |
| Fulu | 411393, 416181 | T1-T7 (all) | PeerDAS era. Full suite. |

## Expected Results

### Phase 0 (epochs 0–74,239)
**Epoch 2:** Near-genesis. Very few validators active. Balance should be ~32 ETH.
**Epoch 20,198:** Mid-Phase 0. Validators accumulated ~2 years of rewards by this point.
- T5 (withdrawals) and T3 (attestation rewards API) skipped — not available pre-Capella
- RPC providers may not serve state for these ancient epochs

### Altair (epochs 74,240–144,895)
**Epoch 74,245:** Just 5 epochs after Altair activation. Tests sync committee introduction.
**Epoch 107,952:** Mid-Altair. Stable state.
- Sync committee rewards exist but not tested (no separate API for historical sync)

### Bellatrix (epochs 144,896–194,047)
**Epoch 144,900:** 4 epochs after Bellatrix. The Merge happened during this phase.
**Epoch 161,755:** Well into post-Merge era. Block proposer data should be available.
- T4 (block proposer) added — execution payload blocks now exist

### Capella (epochs 194,048–269,567)
**Epoch 194,050:** Just 2 epochs post-Capella. First withdrawals happening.
**Epoch 248,668:** Mid-Capella. Withdrawal sweeps well-established.
- T5 (withdrawals) now tested — validators may have partial withdrawals
- T3 (attestation rewards) now available

### Deneb (epochs 269,568–364,031)
**Epoch 269,570:** Just 2 epochs post-Deneb. Proto-danksharding active.
**Epoch 331,881:** Mid-Deneb. Blob market established.
- Full test suite. No new test types vs Capella.

### Electra (epochs 364,032–411,391)
**Epoch 364,039:** 7 epochs post-Pectra. New MaxEB (2048 ETH) in effect.
**Epoch 376,912:** Mid-Electra.
- T7 (effective balance) validates new 2048 ETH max
- Some validators may have consolidated (effective balance > 32 ETH)

### Fulu (epochs 411,392–ongoing)
**Epoch 411,393:** Just 1 epoch post-Fusaka. PeerDAS active.
**Epoch 416,181:** Mid-Fulu (if reached).
- Full suite. Validates continued data consistency.

## Run Command

```bash
python3 scripts/historical_fork_test.py \
  --beaconchain-api-key YOUR_KEY \
  --validator 1 \
  --samples-per-fork 2 \
  --seed 42 \
  --output-dir investigations/historical/
```

This will generate:
- `investigations/historical/historical_fork_test_report.md` — full results
- `investigations/historical/historical_fork_test_results.json` — machine-parseable

## Key Risks and What to Watch For

1. **Fork boundary epochs:** beaconcha.in may return data from the wrong fork version near boundaries
2. **Withdrawal definition drift:** Balance may shift between first-slot and last-slot definitions across forks
3. **Unit changes:** beaconcha.in V2 uses wei; V1 uses gwei. Scripts auto-detect.
4. **Historical state unavailability:** Public RPCs often prune states older than ~1 year. Phase 0 and Altair epochs may fail with 404.
5. **Post-Pectra effective balance:** Validators that consolidated will show effective balance > 32 ETH. This is correct behavior, not a bug.
