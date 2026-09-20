#!/usr/bin/env bash
# ReproLens deployment script -- plain AWS CLI, deliberately not
# CloudFormation/SAM/CDK. For a 4-day hackathon single-stack deploy, a CLI
# script is simpler to read, debug, and re-run than a templating layer would
# be, per the technical document's "prefer the simplest architecture"
# principle. Re-running this script is roughly idempotent for the create
# steps (they'll no-op or error harmlessly if the resource already exists).
#
# REQUIRES: aws cli v2, configured credentials, and Bedrock model access
# already granted in your account/region (see deploy.md step 0).
set -euo pipefail

: "${AWS_REGION:?Set AWS_REGION, e.g. export AWS_REGION=ap-south-1}"
: "${OPENAI_API_KEY:?Set OPENAI_API_KEY, your OpenAI API key}"
: "${OPENAI_MODEL:?Set OPENAI_MODEL, e.g. gpt-4o}"

PROJECT="reprolens"
BUCKET_NAME="${PROJECT}-artifacts-$(aws sts get-caller-identity --query Account --output text)"
TABLE_NAME="Investigations"
ROLE_NAME="${PROJECT}-lambda-role"
API_NAME="${PROJECT}-api"

echo "== Region: $AWS_REGION"
echo "== Bucket: $BUCKET_NAME"

echo "\n[1/9] Creating private S3 bucket..."
aws s3api create-bucket \
  --bucket "$BUCKET_NAME" \
  --region "$AWS_REGION" \
  --create-bucket-configuration LocationConstraint="$AWS_REGION" \
  || echo "  (bucket may already exist -- continuing)"
aws s3api put-public-access-block --bucket "$BUCKET_NAME" \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

# CORS so the browser can PUT directly to pre-signed URLs.
cat > /tmp/reprolens-cors.json << EOF
{"CORSRules":[{"AllowedOrigins":["*"],"AllowedMethods":["PUT","GET"],"AllowedHeaders":["*"]}]}
EOF
aws s3api put-bucket-cors --bucket "$BUCKET_NAME" --cors-configuration file:///tmp/reprolens-cors.json

echo "\n[2/9] Creating DynamoDB table..."
aws dynamodb create-table \
  --table-name "$TABLE_NAME" \
  --attribute-definitions AttributeName=investigation_id,AttributeType=S AttributeName=created_at,AttributeType=S \
  --key-schema AttributeName=investigation_id,KeyType=HASH AttributeName=created_at,KeyType=RANGE \
  --billing-mode PAY_PER_REQUEST \
  --region "$AWS_REGION" \
  || echo "  (table may already exist -- continuing)"

echo "\n[3/9] Creating IAM role..."
sed "s/REPLACE_WITH_BUCKET_NAME/$BUCKET_NAME/;s/REPLACE_WITH_TABLE_NAME/$TABLE_NAME/" \
  iam/permissions-policy.json > /tmp/reprolens-permissions.json

aws iam create-role --role-name "$ROLE_NAME" \
  --assume-role-policy-document file://iam/trust-policy.json \
  || echo "  (role may already exist -- continuing)"
aws iam put-role-policy --role-name "$ROLE_NAME" \
  --policy-name "${PROJECT}-permissions" \
  --policy-document file:///tmp/reprolens-permissions.json

ROLE_ARN=$(aws iam get-role --role-name "$ROLE_NAME" --query 'Role.Arn' --output text)
echo "  Role ARN: $ROLE_ARN"
echo "  (IAM propagation can take ~10s before Lambda creation succeeds)"
sleep 10

echo "\n[4/9] Packaging Lambda code..."
BUILD_DIR=$(mktemp -d)
cp ../backend/lambda/*.py "$BUILD_DIR/"
cp -r ../backend/schemas "$BUILD_DIR/"
pip install -r ../backend/requirements.txt -t "$BUILD_DIR" --quiet
(cd "$BUILD_DIR" && zip -qr /tmp/reprolens-lambda.zip .)
echo "  Package: /tmp/reprolens-lambda.zip"

deploy_function() {
  local FN_NAME=$1
  local HANDLER=$2
  aws lambda create-function \
    --function-name "$FN_NAME" \
    --runtime python3.12 \
    --role "$ROLE_ARN" \
    --handler "$HANDLER" \
    --zip-file fileb:///tmp/reprolens-lambda.zip \
    --timeout 30 \
    --memory-size 512 \
    --environment "Variables={AWS_REGION=$AWS_REGION,OPENAI_API_KEY=$OPENAI_API_KEY,OPENAI_MODEL=$OPENAI_MODEL,S3_BUCKET=$BUCKET_NAME,DYNAMODB_TABLE=$TABLE_NAME}" \
    --region "$AWS_REGION" \
    2>/dev/null \
  || aws lambda update-function-code --function-name "$FN_NAME" --zip-file fileb:///tmp/reprolens-lambda.zip --region "$AWS_REGION"
}

echo "\n[5/9] Deploying Lambda functions..."
deploy_function "${PROJECT}-create-investigation" "create_investigation.lambda_handler"
deploy_function "${PROJECT}-investigate" "investigate_handler.lambda_handler"
deploy_function "${PROJECT}-explain" "explain_handler.lambda_handler"
deploy_function "${PROJECT}-list-investigations" "list_investigations.lambda_handler"

echo "\n[6/9] Creating API Gateway HTTP API..."
API_ID=$(aws apigatewayv2 create-api --name "$API_NAME" --protocol-type HTTP --target "" \
  --query 'ApiId' --output text 2>/dev/null || true)
if [ -z "${API_ID:-}" ]; then
  API_ID=$(aws apigatewayv2 get-apis --query "Items[?Name=='$API_NAME'].ApiId | [0]" --output text)
fi
echo "  API ID: $API_ID"

link_route() {
  local ROUTE_KEY=$1
  local FN_NAME=$2
  local FN_ARN
  FN_ARN=$(aws lambda get-function --function-name "$FN_NAME" --query 'Configuration.FunctionArn' --output text)
  local INTEGRATION_ID
  INTEGRATION_ID=$(aws apigatewayv2 create-integration --api-id "$API_ID" \
    --integration-type AWS_PROXY --integration-uri "$FN_ARN" \
    --payload-format-version 2.0 --query 'IntegrationId' --output text)
  aws apigatewayv2 create-route --api-id "$API_ID" --route-key "$ROUTE_KEY" \
    --target "integrations/$INTEGRATION_ID" > /dev/null
  aws lambda add-permission --function-name "$FN_NAME" \
    --statement-id "apigw-${FN_NAME}" --action lambda:InvokeFunction \
    --principal apigateway.amazonaws.com \
    --source-arn "arn:aws:execute-api:${AWS_REGION}:$(aws sts get-caller-identity --query Account --output text):${API_ID}/*/*" \
    2>/dev/null || true
}

link_route "POST /investigations" "${PROJECT}-create-investigation"
link_route "POST /investigations/{id}/investigate" "${PROJECT}-investigate"
link_route "POST /investigations/{id}/explain" "${PROJECT}-explain"
link_route "GET /investigations" "${PROJECT}-list-investigations"

aws apigatewayv2 create-stage --api-id "$API_ID" --stage-name '$default' --auto-deploy > /dev/null 2>&1 || true

API_URL="https://${API_ID}.execute-api.${AWS_REGION}.amazonaws.com"
echo "\n[7/9] Backend deployed."
echo "  API base URL: $API_URL"

echo "\n[8/9] Injecting API URL into frontend/config.js and packaging..."
CONFIG_FILE="../frontend/config.js"
if grep -q "REPLACE_WITH_YOUR_API_GATEWAY_URL" "$CONFIG_FILE"; then
  sed -i.bak "s#REPLACE_WITH_YOUR_API_GATEWAY_URL#$API_URL#" "$CONFIG_FILE"
  rm -f "${CONFIG_FILE}.bak"
  echo "  frontend/config.js updated with live API URL."
else
  echo "  frontend/config.js already configured -- leaving as-is."
fi

FRONTEND_ZIP=/tmp/reprolens-frontend.zip
rm -f "$FRONTEND_ZIP"
(cd ../frontend && zip -qr "$FRONTEND_ZIP" .)

echo "\n[9/9] Deploying to Amplify Hosting via CLI (manual deploy, no git provider needed)..."
APP_ID=$(aws amplify create-app --name "$PROJECT" --region "$AWS_REGION" \
  --query 'app.appId' --output text 2>/dev/null || \
  aws amplify list-apps --region "$AWS_REGION" --query "apps[?name=='$PROJECT'].appId | [0]" --output text)
echo "  Amplify app ID: $APP_ID"

aws amplify create-branch --app-id "$APP_ID" --branch-name main --region "$AWS_REGION" \
  > /dev/null 2>&1 || echo "  (branch may already exist -- continuing)"

DEPLOYMENT=$(aws amplify create-deployment --app-id "$APP_ID" --branch-name main --region "$AWS_REGION")
JOB_ID=$(echo "$DEPLOYMENT" | python3 -c "import sys,json;print(json.load(sys.stdin)['jobId'])")
ZIP_UPLOAD_URL=$(echo "$DEPLOYMENT" | python3 -c "import sys,json;print(json.load(sys.stdin)['zipUploadUrl'])")

curl -s -T "$FRONTEND_ZIP" "$ZIP_UPLOAD_URL" -o /dev/null
aws amplify start-deployment --app-id "$APP_ID" --branch-name main --job-id "$JOB_ID" --region "$AWS_REGION" > /dev/null

echo "  Waiting for Amplify deployment to finish..."
for i in $(seq 1 20); do
  STATUS=$(aws amplify get-job --app-id "$APP_ID" --branch-name main --job-id "$JOB_ID" --region "$AWS_REGION" \
    --query 'job.summary.status' --output text)
  echo "    status: $STATUS"
  if [ "$STATUS" = "SUCCEED" ] || [ "$STATUS" = "FAILED" ]; then break; fi
  sleep 10
done

SITE_URL="https://main.${APP_ID}.amplifyapp.com"

echo "\n=================================================================="
echo "  API base URL:      $API_URL"
echo "  Deployed frontend: $SITE_URL"
if [ "${STATUS:-}" != "SUCCEED" ]; then
  echo "  WARNING: Amplify job status was '$STATUS', not SUCCEED."
  echo "  Check: aws amplify get-job --app-id $APP_ID --branch-name main --job-id $JOB_ID"
fi
echo "  Next: open the URL above in a fresh/incognito browser and run"
echo "  the Step 3 smoke test in deployment/deploy.md."
echo "=================================================================="
