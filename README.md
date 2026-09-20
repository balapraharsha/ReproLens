# ReproLens

**Cross-artifact investigation for ML experiments.**
*Don't ask an LLM what happened. Make it prove what happened.*

Built for First Commit (AWS × WeMakeDevs, Bharat Builds Tour), Ship It track.

## The problem

Debugging rarely fails because there's no information — it fails because the
information is scattered. A program can report an error in one place while
the condition that caused it is defined somewhere else — in configuration,
dependencies, input data, or an earlier log line. This is worse in ML
experiments: a training run can complete *successfully* and still be wrong,
with the researcher left manually cross-referencing config, environment,
dataset metadata, and logs to figure out why.

## What ReproLens does

You give it five artifacts from an experiment — `config.yaml`,
`requirements.txt`, `train.log`, `dataset_metadata.json`, `traceback.txt` —
and it returns a structured diagnosis: primary finding, confidence, cited
evidence (which file, which field, what it means), competing hypotheses, and
recommended next checks. When the evidence genuinely isn't enough, it says
so (`insufficient_evidence`) instead of guessing.

## Why this isn't just "upload files to ChatGPT"

The diagnosis is produced through **strict, schema-constrained tool/function
calling** — the model can only respond by calling a single tool
(`report_experiment_diagnosis`), defined in
`backend/schemas/diagnosis_schema.json`. Every evidence item must name a
specific artifact and field. The system prompt (`backend/lambda/evidence.py`)
explicitly forbids inventing facts and requires the model to prefer
`insufficient_evidence` over a confident guess. Every returned diagnosis is
also re-validated locally against that same JSON Schema before it ever
reaches the user — the model's structured output is never trusted blindly.
This doesn't eliminate the possibility of the model reasoning incorrectly —
it makes that reasoning **checkable**, because every claim points back to a
file and location a human can independently verify.

## Why this isn't the same as MLflow / Weights & Biases

Those tools capture and let you compare config, metrics, and environment per
run — they store evidence. ReproLens correlates that evidence to produce a
root-cause explanation across artifacts. It's built to sit downstream of
trackers like these, not to replace them.

## Architecture

```
Browser → S3 static website (frontend) → API Gateway → Lambda → S3 (artifacts)
                                                            ↓
                                                  OpenAI API (function calling,
                                                  strict schema-constrained output)
                                                            ↓
                                                  DynamoDB (history, async, non-blocking)
```

**Note on the model provider:** this was originally designed against Amazon
Bedrock (see `docs/architecture.md` for that rationale). During the actual
deploy, the AWS account used for this submission did not have Bedrock model
access approved in time — Bedrock's Anthropic models require a manual
use-case review / support case for first-time accounts in some regions, and
that did not clear before the deadline. `backend/lambda/bedrock_client.py`
was swapped to call the OpenAI API directly via function calling, keeping
the exact same schema-validation contract, system prompt, and
`diagnose()`/`explain()` interface — no other module needed to change. This
is a legitimate architectural fallback documented here rather than hidden;
re-pointing this back to Bedrock's Converse API is a drop-in swap of that
one file once model access is approved.

Full design rationale, requirements, and the pressure-tested judging
criteria analysis live in `docs/architecture.md` and the companion
technical document.

## Setup

```bash
pip install -r backend/requirements.txt --break-system-packages
```

## Deployment

See `deployment/deploy.md` for the original Bedrock + Amplify path. The
version actually deployed for this submission used:
- **Backend:** AWS CLI (S3, DynamoDB, IAM, Lambda, API Gateway HTTP API) —
  same resources as `deployment/deploy.sh`, run as individual CLI commands.
- **Model:** OpenAI API (`OPENAI_API_KEY` / `OPENAI_MODEL` env vars on the
  Lambda functions) instead of Bedrock.
- **Frontend:** S3 static website hosting instead of Amplify, for a faster
  single-command deploy under time pressure.

Live deployment: see the "Deployed link" in the submission.

## Fixtures

Six synthetic, hand-built scenarios in `fixtures/`, covering distinct
failure classes — the hero scenario (`03_silent_generalization_failure`) is
a training run that completes with no exception at all, deliberately
included to prove ReproLens correlates evidence rather than just parsing
tracebacks.

## Testing

```bash
cd tests
pytest test_normalization.py test_schema.py test_security.py -v   # no AWS/API needed, all pass locally
pytest test_fixtures.py -v -s                                      # requires real model API access
```

## Limitations — stated honestly

- Validated only against 6 synthetic fixtures the team constructed — no
  real-world failure corpus, no measured researcher time savings.
- Scoped to PyTorch-shaped config/log conventions; no TensorFlow/JAX support.
- No authentication, no rate limiting — acceptable for a hackathon demo with
  synthetic fixtures only, not for real proprietary logs.
- No trained model, no accuracy metric in the traditional sense — this is a
  schema-constrained reasoning system, not a classifier (see
  `docs/architecture.md` for why that distinction matters for evaluation).
- Deployed against the OpenAI API rather than Bedrock for this submission,
  for the reason described in Architecture above — this is a swap of one
  module, not a redesign, but it means the Bedrock-specific claims in
  `docs/architecture.md` describe the intended target, not what's live.
- Not claimed as production-ready, and not claimed as the first system to
  attempt automated experiment diagnosis — see the competitive analysis in
  the technical document for what was actually checked.

## Security

Private S3 bucket for artifacts, short-lived pre-signed upload URLs,
`yaml.safe_load` only (never `yaml.load`/`eval`/`exec`), uploaded content
treated strictly as data (the system prompt explicitly forbids the model
from following instructions embedded in artifact content), IAM-role-based
AWS access (no AWS credentials in frontend code), no full artifact contents
in CloudWatch logs. The frontend's static-hosting bucket is intentionally
public (it only serves static HTML/JS/CSS); the artifacts bucket is not.

## Future work

Authentication, broader framework support, direct MLflow/W&B ingestion,
historical cross-run comparison (where retrieval over accumulated history
would become genuinely justified, unlike in this single-investigation MVP),
and re-pointing the model call back to Amazon Bedrock once model access is
approved.
