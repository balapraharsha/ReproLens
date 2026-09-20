# Architecture

This is the condensed, code-facing version. The full 35-section technical
document (requirements, competitive analysis, judging-criteria pressure
test, cost estimates, evaluator Q&A) is the companion artifact published
separately for this project — this file exists so the repository is
self-contained without duplicating all of it.

## Request flow

1. `POST /investigations` (`create_investigation.py`) — generates an
   investigation ID, returns pre-signed S3 PUT URLs for the five artifact
   slots.
2. Browser uploads whichever artifacts it has directly to S3.
3. `POST /investigations/{id}/investigate` (`investigate_handler.py`) —
   fetches whatever's in S3 (`storage.fetch_uploaded_artifacts`), normalizes
   it (`normalize.build_evidence_bundle`), calls Bedrock
   (`bedrock_client.diagnose`), validates the response against the JSON
   Schema, fires an async DynamoDB write, returns the diagnosis.
4. `POST /investigations/{id}/explain` (`explain_handler.py`) — the "why"
   follow-up, scoped to the same evidence bundle and the already-produced
   diagnosis.

## Why normalization is a separate module from the Bedrock call

`normalize.py` has zero AWS SDK dependencies and zero network calls — it's
pure Python string/YAML/JSON handling. That's why `tests/test_normalization.py`
and `tests/test_security.py` can run in any environment, including one with
no AWS access at all, and still meaningfully prove the artifact-handling
logic is correct before a single dollar of Bedrock inference is spent.

## Why the diagnosis schema lives in one file

`backend/schemas/diagnosis_schema.json` is loaded once by `evidence.py` and
referenced by both `bedrock_client.py` (to build the Bedrock `toolSpec`) and
`tests/test_schema.py` (to validate sample responses). There is exactly one
copy — editing the schema can't accidentally leave the Bedrock request and
the test suite out of sync with each other.

## Why DynamoDB is written to after the response, not before

`investigate_handler.py` calls `storage.history_write_safe` only after the
diagnosis has already been computed and is ready to return.
`history_write_safe` swallows all exceptions internally and only logs them —
a DynamoDB outage degrades to "no history saved," never to "no diagnosis
returned."

## What was NOT built, on purpose

RAG, a vector database, authentication, RBAC, multi-region deployment,
containers/Kubernetes, automatic hyperparameter tuning, automatic experiment
relaunch. Each of these was considered and explicitly rejected as
out-of-scope for a 4-day MVP — see the technical document's "MVP scope" and
"engineering principles" sections for the reasoning behind each.
