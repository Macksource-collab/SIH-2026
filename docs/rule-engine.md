# Deterministic rule engine

The rule engine consumes persisted extracted declarations and evidence. It never executes imported code and does not use an LLM for compliance decisions.

Supported validators are `required`, `regex`, `numeric`, `date`, `comparison`, and `conditional_required`. Regex imports select only the built-in `email` or `phone` pattern. Validator configuration uses a strict key allowlist; unknown keys and unsupported fields are rejected.

Evaluation follows this order:

1. Check active state, effective date, and product-category applicability.
2. Select evidence, preferring human-reviewed declarations.
3. Return `REVIEW` for poor images, low confidence, ambiguity, failed OCR, or uncertain applicability.
4. Apply the configured deterministic validator.
5. Store `PASS`, `FAIL`, or `REVIEW`, its reason, a rule snapshot, and evidence field ID.

Overall results are `COMPLIANT`, `NON_COMPLIANT`, or `REVIEW_REQUIRED`. Any active DEMO/PROVISIONAL evaluation keeps the overall result at `REVIEW_REQUIRED`, even if the demonstration check passes.

## Import API

- `POST /admin/rules/import/validate`: validates and returns a digest plus preview actions.
- `POST /admin/rules/import/commit`: accepts the unchanged rules, preview digest, and optional verified-review acknowledgement.

Both endpoints require the admin role. A conflicting existing code/version blocks the whole commit. Identical rows are idempotently reported as unchanged.
