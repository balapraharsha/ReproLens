# Deploying ReproLens

This assumes an AWS account with the CLI configured (`aws configure`) and
credentials with permission to create S3/DynamoDB/Lambda/IAM/API Gateway
resources. This was written and validated for logic correctness in a sandbox
without AWS network access -- **you are the first person to actually run
these commands against a real account.** Expect to debug small things (IAM
propagation timing, region-specific API differences).

## Step 0 — Bedrock model access + smoke test (DO THIS FIRST, do it tonight)

1. AWS Console → Bedrock → **Model access** → request/verify access to a
   Claude model in your target region.
2. Pick a model ID that supports the Converse API and tool use. Check the
   Bedrock console's model catalog for what's currently available in your
   region and account — model availability changes over time and by region,
   so don't assume a specific ID from any document; verify it live.
3. Run a trivial `converse()` call with that model ID from a Python shell
   with `boto3` installed and your AWS credentials configured, to confirm
   basic access works before wiring up Lambda.
4. Run one call with the `toolConfig` from `backend/lambda/evidence.py`
   (`DIAGNOSIS_TOOL_CONFIG`) against a small evidence bundle, and confirm you
   get back a `toolUse` block that validates against
   `backend/schemas/diagnosis_schema.json`. If `toolChoice` (forced tool
   selection) throws a `ValidationException`, `bedrock_client.py` already
   retries without it — but confirm this actually happens as expected for
   your specific model.
5. **Write down the exact model ID that worked.** You'll pass it as
   `BEDROCK_MODEL_ID` below.

If step 4 fails entirely (model doesn't support tool use), see "Fallback:
JSON Schema output" at the bottom of this file before proceeding.

## Step 1 — Deploy everything (backend + frontend)

```bash
cd deployment
export AWS_REGION=ap-south-1          # or your chosen region
export BEDROCK_MODEL_ID=<the model id you verified in Step 0>
./deploy.sh
```

This now does the whole path in one run: creates the private S3 bucket
(with CORS for direct browser uploads), the `Investigations` DynamoDB table,
the IAM role, all four Lambda functions, the API Gateway HTTP API, injects
the live API URL into `frontend/config.js`, zips the frontend, and deploys
it to **Amplify Hosting via the CLI** (`aws amplify create-app` /
`create-deployment` / `start-deployment` — no git provider or console
drag-and-drop needed). It prints both the API base URL and the live Amplify
site URL at the end.

If the Amplify deployment step fails partway (e.g. `create-deployment`
returns before the zip upload finishes, or the job status comes back
`FAILED`), the backend is still fully deployed — re-run just the Amplify
portion manually:

```bash
aws amplify get-job --app-id <APP_ID> --branch-name main --job-id <JOB_ID>
```

or fall back to console drag-and-drop of the `frontend/` folder if the CLI
path gives you trouble — both produce the same result, a live URL.

## Step 2 — Smoke test end-to-end

1. Open the deployed Amplify URL in a fresh (incognito) browser.
2. Use the demo-mode dropdown to load Fixture 3 (silent generalization
   failure).
3. Click Investigate. Confirm you get a real diagnosis, not an error.
4. Check CloudWatch Logs for the `reprolens-investigate` function — you
   should see the structured log lines (`investigation_created`,
   `bedrock_completed`, etc.) with real latency numbers.
5. Repeat for at least Fixtures 1, 2, and 6 (healthy) before recording your
   demo video.

## Step 3 — Run the full local + live test suite

```bash
cd ../tests
pip install -r ../backend/requirements.txt pytest --break-system-packages
pytest test_normalization.py test_schema.py test_security.py -v   # no AWS needed
export AWS_REGION=... BEDROCK_MODEL_ID=...
pytest test_fixtures.py -v -s                                      # real Bedrock calls
```

Record the actual pass/fail table from `test_fixtures.py` — that's your
honest "X/6 fixtures correctly diagnosed" number for the writeup and the
technical document's §21 Validation Framework. Do not report a number you
didn't actually see printed.

## Cleanup (after submission, to stop incurring any cost)

```bash
aws lambda delete-function --function-name reprolens-create-investigation
aws lambda delete-function --function-name reprolens-investigate
aws lambda delete-function --function-name reprolens-explain
aws lambda delete-function --function-name reprolens-list-investigations
aws apigatewayv2 delete-api --api-id <API_ID>
aws dynamodb delete-table --table-name Investigations
aws s3 rb s3://<bucket-name> --force
aws iam delete-role-policy --role-name reprolens-lambda-role --policy-name reprolens-permissions
aws iam delete-role --role-name reprolens-lambda-role
```

## Fallback: JSON Schema output instead of strict tool use

If your selected model/region rejects tool use entirely (not just forced
`toolChoice`, but tool use in general), Bedrock's separate JSON-Schema output
mechanism (`outputConfig.textFormat` on `Converse`) is the documented
alternative — check the current Bedrock "structured output" documentation
for exact request shape, since this wasn't the primary path built here and
needs verifying against whatever the current API surface looks like when you
read this. The response should still be validated against
`backend/schemas/diagnosis_schema.json` using the same `jsonschema.validate`
call already in `bedrock_client.py` — only the request-building half of that
file would need to change, not the validation half.
