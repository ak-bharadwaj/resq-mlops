# AI Usage & Verification Log (AI-USAGE.md)

In compliance with Challenge Brief instructions and Section 15:

- **AI Tools Used**: Antigravity Pair Programming Agent (Gemini 3.8 Flash High / Claude 3.7 Sonnet).
- **Scope of Usage**:
  - Synthesizing and formalizing the frozen v25 MLOps architecture contracts.
  - Generating initial project scaffolding, Makefile targets, and JSON schema definitions.
  - Writing automated test suites verifying P0 contracts.
- **Verification & Oversight**:
  - Every architectural contract, timezone boundary (strict UTC), cost calculation (€600/wk delta, fixed €45,600 visit baseline), and tie-breaking rule was manually verified against `LPDG_MLOps_Architecture_v25_CONTRACT_RESTORED_STRENGTHENED_FREEZE.docx` and the official challenge brief.
  - Test suites are run locally with strict assertions to ensure offline execution and zero data leakage.

---

## Concrete Review & Error Correction Case Study

### AI suggested:
In the candidate evaluation seam for Task 15 (`app/model/evaluate.py`), the assistant implemented the common evaluation population coverage check using scalar cardinality approximation:

```python
act_valid = len(predictions) + deferred_count
cand_valid = len(predictions) + deferred_count
common_valid_total += min(act_valid, cand_valid)
excluded_due_to_model_input = pop_total - common_valid_total
```

The AI proposed taking the minimum of active and candidate prediction counts (`min(act_valid, cand_valid)`) across evaluation weeks, accumulating this scalar sum, and calculating common population coverage from it.

### I caught it because:
During strict code review against Section 8 of the frozen v25 architecture specification ("Evidence Gate & Promotion Policy"), I identified that scalar cardinalities do not demonstrate set identity. For example, `min(100, 95) = 95` does not prove that the 95 gateways scored by the candidate are the exact same 95 physical assets evaluated by the active baseline. Furthermore, subtracting `common_valid_total` (a prediction count) from `pop_total` (an eligibility count accumulated across weeks) conflated fleet eligibility with model output validity.

### I corrected it by:
Refactoring the candidate evaluation engine to track explicit gateway-week sets and computing exact mathematical set intersections:

1. Tracking evaluated records as explicit sets of canonical pairs `(canonical_gateway_id, monday_iso_string)` for both active (`active_valid_gw_weeks`) and candidate (`candidate_valid_gw_weeks`) models.
2. Computing the exact set intersection:
   ```python
   common_gw_weeks = active_valid_gw_weeks & candidate_valid_gw_weeks
   common_valid_total = len(common_gw_weeks)
   ```
3. Calculating common population coverage strictly against the eligible cohort:
   ```python
   common_pop_coverage = common_valid_total / pop_total if pop_total > 0 else 0.0
   ```
4. Computing model-input exclusions as the distinct shortfall from the eligible population rather than an arbitrary scalar subtraction.

### Why the correction mattered:
The v25 promotion gate mandates that any candidate model evaluated against production must be compared on an identical population with at least 90% common coverage across all three rolling windows. The AI's scalar shortcut would have allowed a candidate model with a completely disjoint or partially divergent set of evaluated gateways to artificially satisfy the common-population guard simply because its total count of predictions was similar to the active model. In operational maintenance dispatch, comparing models over different physical assets distorts cost delta calculations (€600/week fault penalty) and risks deploying an unverified model to production. The correction guaranteed mathematical rigor and cryptographic auditability for all promotion decisions.

