# AWS API Gateway Assessment

A small API built with AWS API Gateway (HTTP API), Cognito authentication, and two Lambda functions. One endpoint fetches live cryptocurrency prices, the other lets you save a personal price alert.

---

## Architecture

```
Client
  │
  │  Authorization: Bearer <Cognito JWT>
  ▼
API Gateway (HTTP API)
  ├── GET  /getPrice  ──▶  Lambda (Node.js)  ──▶  CoinGecko API
  └── POST /setPrice  ──▶  Lambda (Python)   ──▶  CoinGecko API
                                              └──▶  SSM Parameter Store
```

**Resources created by CloudFormation:**

- API Gateway v2 (HTTP API) with a JWT authorizer
- Cognito User Pool + App Client
- Two Lambda functions (Node.js 22 and Python 3.12)
- One IAM role shared by both Lambdas (least-privilege)
- SSM Parameter Store entries written by the setPrice Lambda

All services are within the AWS Free Tier.

---

## External Services

**GET /getPrice** calls [CoinGecko](https://www.coingecko.com/en/api) — a free public API that returns real-time cryptocurrency prices. No API key is needed.

**POST /setPrice** also calls CoinGecko (to show the current price for comparison), then writes your alert price to AWS SSM Parameter Store under the path `/price-alerts/{coin}`.

---

## Prerequisites

- AWS CLI v2 installed and configured (`aws configure`)
- An S3 bucket in your target region to upload the Lambda ZIPs
- PowerShell or Command Prompt on Windows 10/11

---

## Deployment

### Step 1 — Package the Lambda functions

Open PowerShell in the project root.

```powershell
Package Lambda 1 (Node.js):
cd lambdas
Compress-Archive -Path index.mjs -DestinationPath ..\lambda1.zip -Force

Package Lambda 2 (Python):
Compress-Archive -Path lambda_function.py -DestinationPath ..\lambda2.zip -Force
cd ..
```

### Step 2 — Create an S3 bucket and upload the ZIPs

Replace `your-bucket-name` and `us-east-1` with your own values.

```powershell
$BUCKET = "your-bucket-name"
$REGION = "us-east-1"

aws s3 mb s3://$BUCKET --region $REGION

aws s3 cp lambda1.zip s3://$BUCKET/lambda1.zip
aws s3 cp lambda2.zip s3://$BUCKET/lambda2.zip
```

### Step 3 — Deploy the CloudFormation stack

```powershell
aws cloudformation deploy `
  --template-file cloudformation/main.yaml `
  --stack-name price-api-stack `
  --parameter-overrides LambdaZipBucket=$BUCKET `
  --capabilities CAPABILITY_NAMED_IAM `
  --region $REGION
```

This usually takes 2–3 minutes. When it finishes, grab the outputs:

```powershell
aws cloudformation describe-stacks `
  --stack-name price-api-stack `
  --query "Stacks[0].Outputs" `
  --region $REGION
```

You will see three values — save them all:

- `ApiEndpoint` — the base URL of the API
- `UserPoolId` — needed to create a test user
- `UserPoolClientId` — needed to get a token

### Step 4 — Create a test user in Cognito

```powershell
$USER_POOL_ID = "<UserPoolId from above>"
$CLIENT_ID    = "<UserPoolClientId from above>"
$EMAIL        = "test@example.com"
$PASSWORD     = "Test1234!"

# Create the user
aws cognito-idp admin-create-user `
  --user-pool-id $USER_POOL_ID `
  --username $EMAIL `
  --temporary-password $PASSWORD `
  --region $REGION

# Set a permanent password so you don't need to go through the
# NEW_PASSWORD_REQUIRED challenge
aws cognito-idp admin-set-user-password `
  --user-pool-id $USER_POOL_ID `
  --username $EMAIL `
  --password $PASSWORD `
  --permanent `
  --region $REGION
```

### Step 5 — Get an access token

```powershell
$TOKEN_RESPONSE = aws cognito-idp initiate-auth `
  --auth-flow USER_PASSWORD_AUTH `
  --client-id $CLIENT_ID `
  --auth-parameters USERNAME=$EMAIL,PASSWORD=$PASSWORD `
  --region $REGION | ConvertFrom-Json

$TOKEN = $TOKEN_RESPONSE.AuthenticationResult.AccessToken
echo $TOKEN
```

Save the token — you will use it in every API call as `Authorization: Bearer <token>`.

---

## Testing the endpoints

Set your API base URL:

```powershell
$API = "<ApiEndpoint from CloudFormation outputs>"
(aws cloudformation describe-stacks --stack-name price-api-stack --query "Stacks[0].Outputs" --region $REGION
)
```

### GET /getPrice

Fetch the current Bitcoin price (default):

```powershell
Invoke-RestMethod `
  -Uri "$API/getPrice" `
  -Headers @{ Authorization = "Bearer $TOKEN" }
```

Fetch a different coin using the `coin` query parameter:

```powershell
Invoke-RestMethod `
  -Uri "$API/getPrice?coin=ethereum" `
  -Headers @{ Authorization = "Bearer $TOKEN" }
```

Expected response:

```json
{
  "coin": "ethereum",
  "currency": "usd",
  "price": 3421.50,
  "change24h": -1.23,
  "retrievedAt": "2025-01-15T10:30:00.000Z"
}
```

Supported coins: `bitcoin`, `ethereum`, `solana`, `ripple`, `dogecoin`

---

### POST /setPrice

Save a price alert for Bitcoin:

```powershell
$body = '{"coin": "bitcoin", "alertPrice": 50000}'

Invoke-RestMethod `
  -Uri "$API/setPrice" `
  -Method POST `
  -Headers @{ Authorization = "Bearer $TOKEN"; "Content-Type" = "application/json" } `
  -Body $body
```

Expected response:

```json
{
  "message": "Alert price for bitcoin set successfully.",
  "coin": "bitcoin",
  "alertPrice": 50000,
  "ssmKey": "/price-alerts/bitcoin",
  "currentPrice": 97230.00,
  "status": "Alert price is BELOW current market price."
}
```

---

### Error cases

Missing or invalid token → HTTP 401

```json
{ "message": "Unauthorized" }
```

Unsupported coin → HTTP 400

```json
{ "error": "Unsupported coin \"xrp2\". Allowed values: bitcoin, dogecoin, ethereum, ripple, solana" }
```

---

## Cleanup

To avoid ongoing charges, delete the stack when you are done:

```powershell
aws cloudformation delete-stack `
  --stack-name price-api-stack `
  --region $REGION
```

Then remove the S3 bucket:

```powershell
aws s3 rm s3://$BUCKET --recursive
aws s3 rb s3://$BUCKET
```

---

## Assumptions and limitations

1. The Cognito App Client uses `USER_PASSWORD_AUTH`. This is fine for testing; a production setup should use SRP auth or a hosted UI with OAuth.

2. Allowed coin list is hardcoded in both Lambdas. This keeps the CoinGecko API surface small and avoids open-ended string injection into upstream URLs. Adding a coin requires a code change and redeployment.

3. SSM Parameter Store is used as a lightweight persistence layer for `setPrice`. If you need to query or list all alerts, replace it with DynamoDB.

4. CoinGecko's free tier has a rate limit of roughly 10–30 requests per minute. Under normal testing load this is fine; if you need higher throughput you should add caching (e.g. Lambda response caching or ElastiCache).

5. The stack uses `us-east-1` in the examples. Change `$REGION` to whichever region you prefer — all services used here are available globally.
