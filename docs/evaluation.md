# Evaluation

**This file is a template.** The numbers below are placeholders --
`pytest tests/test_fixtures.py -v -s` against your deployed Bedrock model
produces the real ones. Do not submit this document with placeholder values
still in it; report only what you actually measured, per the technical
document's claim-verification rules.

## Fixture results

| Fixture | Expected primary diagnosis | Actual | Evidence correct? | Confidence appropriate? | Status |
|---|---|---|---|---|---|
| 01 — dataset/config mismatch | Dataset/config mismatch, high confidence | *(fill in)* | *(fill in)* | *(fill in)* | *(pass/fail)* |
| 02 — environment incompatibility | CUDA/compiled-extension incompatibility, high confidence | | | | |
| 03 — silent generalization failure (hero) | Generalization failure, medium confidence, ≥2 competing hypotheses | | | | |
| 04 — missing artifact | Diagnosis attempted; `missing_information` names the missing file | | | | |
| 05 — contradictory evidence | Lower confidence; explicit acknowledgment of the 3-way contradiction | | | | |
| 06 — healthy experiment | `experiment_status = healthy`, no manufactured problem | | | | |

## Latency

- Measured Bedrock round-trip (average of N runs): *(fill in — from
  `_meta.bedrock_latency_seconds` in the diagnosis response, or CloudWatch)*
- Measured end-to-end request latency: *(fill in — from CloudWatch logs)*

## Schema validity rate

- Successful Bedrock calls that returned a schema-conformant tool call
  without needing the `toolChoice` fallback retry: *(fill in)* / *(total calls)*

## What this evaluation does NOT claim

- No accuracy percentage in the traditional ML sense — there is no trained
  classifier and no labeled test set beyond these 6 fixtures.
- No measured real-world researcher time savings.
- No claim that 6 fixtures constitute broad coverage of real-world ML
  failure modes — they cover 6 specific, deliberately distinct classes.
