# Legal data governance

PackSure separates OCR evidence, deterministic software checks, and legal-source verification. The repository contains no claim that its demonstration rules reproduce current Legal Metrology law.

Every rule has one verification status:

- `DEMO`: created only to demonstrate software behavior.
- `PROVISIONAL`: based on work in progress and still awaiting authoritative review.
- `VERIFIED`: assigned only after a qualified reviewer checks the official source, exact text, amendment history, effective dates, scope, category applicability, units, exceptions, and source reference.

The application never upgrades a rule to `VERIFIED`. Importing a verified record requires an explicit commit acknowledgement, but that acknowledgement is only a technical guard. It is not proof that legal review occurred.

## Import procedure

1. Copy [the example](../backend/examples/rules.example.json).
2. Enter structured data only. Python, expressions, arbitrary regular expressions, and unknown configuration keys are rejected.
3. In Admin > Rules, paste the JSON and select **Validate / Preview**.
4. Review `CREATE`, `UNCHANGED`, and `CONFLICT` actions.
5. Commit only after resolving conflicts. A code/version pair is immutable; publish a higher version for a changed rule.
6. Keep source documents outside this repository under controlled document management. Record a stable document name and precise reference.

Before any production or enforcement use, an authorized legal/domain reviewer must verify all records, and the organization must define approval, withdrawal, supersession, and periodic-review procedures.
