# Complete Serverless RAG Pipeline on AWS

This workshop builds an end-to-end Retrieval Augmented Generation application on AWS.

The application answers questions from PDF policy documents. The UI is a static website hosted on Amazon S3. PDF ingestion and question answering run on AWS Lambda. Embeddings and answer generation use Amazon Bedrock. Vector search uses Amazon OpenSearch Serverless.

## What You Will Build

```text
User browser
  -> S3 static website
  -> API Gateway HTTP API
  -> Query Lambda
  -> Amazon Bedrock Titan Embeddings
  -> OpenSearch Serverless vector index
  -> Amazon Bedrock Nova Lite
  -> grounded answer with citations

PDF upload
  -> S3 source bucket
  -> S3 ObjectCreated event
  -> Ingestion Lambda
  -> PDF extraction
  -> chunking
  -> Titan embeddings
  -> OpenSearch Serverless indexing
```

## Use Case

Build an **Employee Policy and Operations Assistant** that answers questions from generated PDF documents:

- employee handbook
- travel and expense policy
- information security policy
- remote work policy
- procurement policy
- onboarding guide

Example question:

```text
What approvals are required for purchases above USD 5000?
```

## Repository Structure

```text
frontend/                 Static S3 website files
lambdas/query_handler/    Lambda handler for RAG queries
lambdas/ingest_handler/   Lambda handler for PDF ingestion
lambdas/shared/           Shared S3, Bedrock, OpenSearch, PDF, RAG code
scripts/                  Build, upload, index, and test helper scripts
data/generated_pdfs/      Generated workshop PDF files
config/settings.yaml      Reference configuration
iam/                      IAM and OpenSearch policy templates
examples/                 Sample questions
```

## Reference Values

These values are already wired into this repo for the instructor AWS account.

If learners use their own AWS account, replace the account id and generated endpoints everywhere they appear in `.env.example`, `config/settings.yaml`, `frontend/config.js`, IAM policy files, and the commands below.

```text
PROJECT_NAME=aster-policy-rag
AWS_REGION=us-east-1
AWS_ACCOUNT_ID=851725469799

SOURCE_BUCKET_NAME=aster-policy-rag-source-pdfs-851725469799-us-east-1
FRONTEND_BUCKET_NAME=aster-policy-rag-frontend-851725469799-us-east-1
SOURCE_PREFIX=raw-pdfs/

OPENSEARCH_COLLECTION_NAME=aster-policy-rag-vector
OPENSEARCH_ENDPOINT=https://3o35kp5w5p9kc8gtzhpa.us-east-1.aoss.amazonaws.com
OPENSEARCH_INDEX=aster-policy-rag-index

QUERY_LAMBDA_FUNCTION_NAME=aster-policy-rag-query
INGEST_LAMBDA_FUNCTION_NAME=aster-policy-rag-ingest
QUERY_LAMBDA_ROLE_NAME=aster-policy-rag-query-role
INGEST_LAMBDA_ROLE_NAME=aster-policy-rag-ingest-role

API_BASE_URL=https://sl04qbrtfa.execute-api.us-east-1.amazonaws.com/prod

BEDROCK_EMBED_MODEL_ID=amazon.titan-embed-text-v2:0
BEDROCK_LLM_MODEL_ID=us.amazon.nova-lite-v1:0
```

Important:

- `OPENSEARCH_ENDPOINT` must be the non-FIPS **OpenSearch endpoint** from the collection page.
- Do not use the OpenSearch Dashboards URL, OpenSearch UI Application URL, or FIPS endpoint in Lambda config.
- `BEDROCK_LLM_MODEL_ID=us.amazon.nova-lite-v1:0` is the US inference profile for Amazon Nova Lite.
- Do not set `AWS_REGION` as a Lambda environment variable. Lambda provides it automatically.

## Prerequisites

Install or configure:

- Python 3.12 or compatible Python 3.x
- AWS CLI
- AWS credentials for account `851725469799`
- Region `us-east-1`
- Amazon Bedrock model access
- Permissions to create S3 buckets, IAM roles, Lambda functions, API Gateway APIs, and OpenSearch Serverless collections

Verify your CLI identity:

```bash
aws sts get-caller-identity
```

## Step 1: Enable Bedrock Model Access

Open the Amazon Bedrock console in `us-east-1`.

Go to **Model access** and enable:

- Amazon Titan Text Embeddings V2
- Amazon Nova Lite

Wait until model access is active before testing the Lambdas.

## Step 2: Generate Source PDFs

Generate workshop PDF files locally:

```bash
python3 scripts/generate_policy_pdfs.py
```

Output:

```text
data/generated_pdfs/
```

The generator is dependency-free, so this step works before installing Python packages.

## Step 3: Create S3 Buckets

Create the source PDF bucket:

```bash
aws s3 mb s3://aster-policy-rag-source-pdfs-851725469799-us-east-1 --region us-east-1
```

Create the static frontend bucket:

```bash
aws s3 mb s3://aster-policy-rag-frontend-851725469799-us-east-1 --region us-east-1
```

If a bucket name is already taken, change only the final suffix and keep the rest of the naming pattern consistent.

## Step 4: Configure Static Website Hosting

Open the S3 console and select:

```text
aster-policy-rag-frontend-851725469799-us-east-1
```

In **Properties > Static website hosting**:

- Enable static website hosting
- Index document: `index.html`
- Error document: `index.html`

For workshop simplicity, allow public read access:

1. Go to **Permissions**.
2. Disable **Block all public access** for this frontend bucket.
3. Apply the bucket policy from:

```text
iam/frontend_bucket_policy.json
```

Production note: for real production use, prefer CloudFront with Origin Access Control instead of public S3 website hosting.

## Step 5: Upload PDFs to S3

Upload generated PDFs to the source bucket:

```bash
python3 scripts/upload_pdfs_to_s3.py \
  --bucket aster-policy-rag-source-pdfs-851725469799-us-east-1 \
  --prefix raw-pdfs/ \
  --region us-east-1
```

Expected S3 path example:

```text
s3://aster-policy-rag-source-pdfs-851725469799-us-east-1/raw-pdfs/employee-handbook.pdf
```

## Step 6: Create Lambda IAM Roles

Create two Lambda execution roles:

- `aster-policy-rag-query-role`
- `aster-policy-rag-ingest-role`

Both use this trust policy:

```text
iam/lambda_trust_policy.json
```

Create roles:

```bash
aws iam create-role \
  --role-name aster-policy-rag-query-role \
  --assume-role-policy-document file://iam/lambda_trust_policy.json
```

```bash
aws iam create-role \
  --role-name aster-policy-rag-ingest-role \
  --assume-role-policy-document file://iam/lambda_trust_policy.json
```

Attach basic Lambda logging:

```bash
aws iam attach-role-policy \
  --role-name aster-policy-rag-query-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
```

```bash
aws iam attach-role-policy \
  --role-name aster-policy-rag-ingest-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
```

Create custom policies:

```bash
aws iam create-policy \
  --policy-name aster-policy-rag-query-policy \
  --policy-document file://iam/lambda_query_policy.json
```

```bash
aws iam create-policy \
  --policy-name aster-policy-rag-ingest-policy \
  --policy-document file://iam/lambda_ingest_policy.json
```

Attach custom policies:

```bash
aws iam attach-role-policy \
  --role-name aster-policy-rag-query-role \
  --policy-arn arn:aws:iam::851725469799:policy/aster-policy-rag-query-policy
```

```bash
aws iam attach-role-policy \
  --role-name aster-policy-rag-ingest-role \
  --policy-arn arn:aws:iam::851725469799:policy/aster-policy-rag-ingest-policy
```

Wait 30-60 seconds for IAM propagation before creating Lambda functions.

## Step 7: Create OpenSearch Serverless Collection

Open **Amazon OpenSearch Service** in `us-east-1`.

Go to **Serverless > Collections > Create collection**.

Use these settings:

- Collection type: `Vector search`
- Collection name: `aster-policy-rag-vector`
- Description: `Serverless vector store for the Aster policy RAG workshop`
- Enable redundancy: unchecked for workshop cost control
- Vector database GPU acceleration: unchecked
- Collection creation method: `Standard create`
- Encryption: `Use an AWS owned key`
- Network access: `Public`
- Resource type: enable access to `OpenSearch endpoint`
- OpenSearch Dashboards access: optional
- Tags:
  - `Project = aster-policy-rag`
  - `Environment = workshop`

### Data Access Policy

Create or update the OpenSearch Serverless data access policy using:

```text
iam/opensearch_data_access_policy.json
```

The important resources are:

```text
collection/aster-policy-rag-vector
index/aster-policy-rag-vector/*
```

The policy includes these principals:

```text
arn:aws:iam::851725469799:role/aster-policy-rag-query-role
arn:aws:iam::851725469799:role/aster-policy-rag-ingest-role
arn:aws:iam::851725469799:user/aws-de-bootcamp-4
arn:aws:iam::851725469799:root
```

Why root is included here:

- In this workshop account, the CLI uses `aws-de-bootcamp-4`.
- The browser console was signed in as root.
- OpenSearch Serverless requires data access policy principals for data-plane access.
- Including root lets the console display indexes during the workshop.

Production note: do not rely on root for production access. Use an IAM user or IAM role and add that ARN to the data access policy.

After the collection is active, copy the non-FIPS OpenSearch endpoint:

```text
https://3o35kp5w5p9kc8gtzhpa.us-east-1.aoss.amazonaws.com
```

## Step 8: Create the Vector Index

Install local setup dependencies:

```bash
python3 -m pip install -r requirements.txt
```

Create the vector index:

```bash
python3 scripts/create_opensearch_index.py \
  --endpoint https://3o35kp5w5p9kc8gtzhpa.us-east-1.aoss.amazonaws.com \
  --index aster-policy-rag-index \
  --dimension 1024 \
  --region us-east-1
```

Expected result:

- OpenSearch collection shows index `aster-policy-rag-index`
- Vector field: `embedding`
- Dimensions: `1024`
- Engine: `faiss`
- Distance type: `cosine`

At this point the document count can still be `0`. Documents appear after ingestion.

## Step 9: Build Lambda Deployment Packages

Build both Lambda zip packages:

```bash
python3 scripts/build_lambda_packages.py
```

Output:

```text
lambda_packages/query_handler.zip
lambda_packages/ingest_handler.zip
```

The build script packages:

- each Lambda handler
- shared project modules
- external dependencies from each handler's `requirements.txt`

## Step 10: Create Lambda Functions

Create the query Lambda:

```bash
aws lambda create-function \
  --function-name aster-policy-rag-query \
  --runtime python3.12 \
  --handler app.lambda_handler \
  --zip-file fileb://lambda_packages/query_handler.zip \
  --role arn:aws:iam::851725469799:role/aster-policy-rag-query-role \
  --timeout 60 \
  --memory-size 1024 \
  --region us-east-1
```

Create the ingestion Lambda:

```bash
aws lambda create-function \
  --function-name aster-policy-rag-ingest \
  --runtime python3.12 \
  --handler app.lambda_handler \
  --zip-file fileb://lambda_packages/ingest_handler.zip \
  --role arn:aws:iam::851725469799:role/aster-policy-rag-ingest-role \
  --timeout 900 \
  --memory-size 2048 \
  --region us-east-1
```

If the functions already exist, update code instead:

```bash
aws lambda update-function-code \
  --function-name aster-policy-rag-query \
  --zip-file fileb://lambda_packages/query_handler.zip \
  --region us-east-1
```

```bash
aws lambda update-function-code \
  --function-name aster-policy-rag-ingest \
  --zip-file fileb://lambda_packages/ingest_handler.zip \
  --region us-east-1
```

## Step 11: Configure Lambda Environment Variables

Do not include `AWS_REGION` in Lambda environment variables. Lambda reserves and provides it automatically.

Set query Lambda variables:

```bash
aws lambda update-function-configuration \
  --function-name aster-policy-rag-query \
  --environment "Variables={OPENSEARCH_ENDPOINT=https://3o35kp5w5p9kc8gtzhpa.us-east-1.aoss.amazonaws.com,OPENSEARCH_INDEX=aster-policy-rag-index,VECTOR_DIMENSION=1024,BEDROCK_EMBED_MODEL_ID=amazon.titan-embed-text-v2:0,BEDROCK_LLM_MODEL_ID=us.amazon.nova-lite-v1:0,TOP_K=5,MAX_CONTEXT_CHARS=12000}" \
  --region us-east-1
```

Set ingestion Lambda variables:

```bash
aws lambda update-function-configuration \
  --function-name aster-policy-rag-ingest \
  --environment "Variables={SOURCE_BUCKET_NAME=aster-policy-rag-source-pdfs-851725469799-us-east-1,SOURCE_PREFIX=raw-pdfs/,OPENSEARCH_ENDPOINT=https://3o35kp5w5p9kc8gtzhpa.us-east-1.aoss.amazonaws.com,OPENSEARCH_INDEX=aster-policy-rag-index,VECTOR_DIMENSION=1024,BEDROCK_EMBED_MODEL_ID=amazon.titan-embed-text-v2:0,BEDROCK_LLM_MODEL_ID=us.amazon.nova-lite-v1:0,CHUNK_SIZE=1200,CHUNK_OVERLAP=180}" \
  --region us-east-1
```

## Step 12: Configure S3 Trigger for Ingestion

Allow S3 to invoke the ingestion Lambda:

```bash
aws lambda add-permission \
  --function-name aster-policy-rag-ingest \
  --statement-id allow-source-bucket-invoke \
  --action lambda:InvokeFunction \
  --principal s3.amazonaws.com \
  --source-arn arn:aws:s3:::aster-policy-rag-source-pdfs-851725469799-us-east-1 \
  --region us-east-1
```

In the S3 console, open:

```text
aster-policy-rag-source-pdfs-851725469799-us-east-1
```

Go to **Properties > Event notifications > Create event notification**:

- Event name: `trigger-policy-rag-ingestion`
- Prefix: `raw-pdfs/`
- Suffix: `.pdf`
- Event types: all object create events
- Destination: Lambda function
- Lambda function: `aster-policy-rag-ingest`

Future PDF uploads under `raw-pdfs/` will trigger ingestion automatically.

## Step 13: Backfill Already Uploaded PDFs

If PDFs were uploaded before the S3 trigger was configured, run:

```bash
python3 scripts/backfill_ingestion.py \
  --bucket aster-policy-rag-source-pdfs-851725469799-us-east-1 \
  --prefix raw-pdfs/ \
  --function-name aster-policy-rag-ingest \
  --region us-east-1
```

You can test one PDF directly:

```bash
aws lambda invoke \
  --function-name aster-policy-rag-ingest \
  --cli-binary-format raw-in-base64-out \
  --payload '{"bucket":"aster-policy-rag-source-pdfs-851725469799-us-east-1","key":"raw-pdfs/employee-handbook.pdf"}' \
  --region us-east-1 \
  /tmp/aster-policy-rag-ingest-response.json

cat /tmp/aster-policy-rag-ingest-response.json
```

Expected response contains:

```text
"bulk_errors": false
```

OpenSearch document count can take 1-2 minutes to refresh.

## Step 14: Create API Gateway

Create an HTTP API in API Gateway:

1. Open API Gateway.
2. Choose **Create API**.
3. Choose **HTTP API**.
4. Add integration: Lambda.
5. Region: `us-east-1`.
6. Lambda function: `aster-policy-rag-query`.
7. API name: `aster-policy-rag-api`.
8. Route: `POST /query`.
9. Stage name: `prod`.
10. Enable auto deploy.

After creation, the invoke URL is:

```text
https://sl04qbrtfa.execute-api.us-east-1.amazonaws.com/prod
```

Allow API Gateway to invoke the query Lambda:

```bash
aws lambda add-permission \
  --function-name aster-policy-rag-query \
  --statement-id allow-api-gateway-invoke \
  --action lambda:InvokeFunction \
  --principal apigateway.amazonaws.com \
  --source-arn "arn:aws:execute-api:us-east-1:851725469799:sl04qbrtfa/*/*/query" \
  --region us-east-1
```

## Step 15: Configure API Gateway CORS

The S3-hosted browser UI needs CORS. Curl can work even when browser CORS is broken, so configure CORS explicitly.

Configure CORS on **API Gateway**, not on the S3 static website bucket. The frontend bucket only hosts HTML, CSS, and JavaScript. The cross-origin request is from the browser to API Gateway.

Use CLI:

```bash
aws apigatewayv2 update-api \
  --api-id sl04qbrtfa \
  --cors-configuration AllowOrigins="*",AllowMethods="POST,OPTIONS",AllowHeaders="content-type,authorization",MaxAge=300 \
  --region us-east-1
```

Or configure in API Gateway console:

- Open `aster-policy-rag-api`
- Go to CORS
- Access-Control-Allow-Origin: `*`
- Access-Control-Allow-Methods: `POST, OPTIONS`
- Access-Control-Allow-Headers: `content-type, authorization`
- Access-Control-Max-Age: `300`
- Save

Verify preflight:

```bash
curl -i -X OPTIONS "https://sl04qbrtfa.execute-api.us-east-1.amazonaws.com/prod/query" \
  -H "Origin: https://aster-policy-rag-frontend-851725469799-us-east-1.s3.us-east-1.amazonaws.com" \
  -H "Access-Control-Request-Method: POST" \
  -H "Access-Control-Request-Headers: content-type"
```

Expected headers include:

```text
access-control-allow-origin: *
access-control-allow-methods: POST,OPTIONS
access-control-allow-headers: content-type,authorization
```

## Step 16: Configure and Upload Frontend

The static frontend reads its API endpoint from:

```text
frontend/config.js
```

It should contain:

```javascript
window.RAG_CONFIG = {
  API_BASE_URL: "https://sl04qbrtfa.execute-api.us-east-1.amazonaws.com/prod"
};
```

Upload frontend files to the frontend bucket:

```bash
python3 scripts/upload_frontend_to_s3.py \
  --bucket aster-policy-rag-frontend-851725469799-us-east-1 \
  --region us-east-1
```

Open the S3 static website URL from the bucket's **Properties > Static website hosting** section.

## Step 17: Test the Query API

Test from terminal:

```bash
curl -X POST "https://sl04qbrtfa.execute-api.us-east-1.amazonaws.com/prod/query" \
  -H "Content-Type: application/json" \
  -d '{"question":"What approvals are required for purchases above USD 5000?","top_k":5}'
```

Expected shape:

```json
{
  "answer": "Purchases above USD 5,000 require manager, budget owner, and Finance approval [1].",
  "citations": [
    {
      "citation_id": 1,
      "document_name": "procurement-policy.pdf",
      "page_number": 1,
      "source_uri": "s3://aster-policy-rag-source-pdfs-851725469799-us-east-1/raw-pdfs/procurement-policy.pdf"
    }
  ]
}
```

Then test the same question from the S3-hosted UI.

## Operational Flow for Learners

After setup, the workflow is simple:

1. Upload a PDF into `s3://aster-policy-rag-source-pdfs-851725469799-us-east-1/raw-pdfs/`.
2. S3 triggers `aster-policy-rag-ingest`.
3. The ingestion Lambda extracts text, chunks it, embeds it, and indexes it.
4. The learner asks a question in the static UI.
5. API Gateway invokes `aster-policy-rag-query`.
6. The query Lambda retrieves relevant chunks and asks Nova Lite to answer with citations.

## Troubleshooting

### Ingestion Triggered but Document Count Is 0

Manually invoke ingestion:

```bash
aws lambda invoke \
  --function-name aster-policy-rag-ingest \
  --cli-binary-format raw-in-base64-out \
  --payload '{"bucket":"aster-policy-rag-source-pdfs-851725469799-us-east-1","key":"raw-pdfs/employee-handbook.pdf"}' \
  --region us-east-1 \
  /tmp/aster-policy-rag-ingest-response.json

cat /tmp/aster-policy-rag-ingest-response.json
```

Check CloudWatch logs for:

- parsed S3 records
- downloaded byte count
- extracted page count
- chunk count
- embedding progress
- OpenSearch bulk indexing result

If you see:

```text
Document ID is not supported in create/index operation request
```

redeploy the latest ingestion Lambda package. The current code lets OpenSearch auto-generate internal document ids and stores `chunk_id` as metadata.

### UI Shows `Failed to fetch` but Curl Works

This is usually API Gateway CORS.

Run:

```bash
aws apigatewayv2 update-api \
  --api-id sl04qbrtfa \
  --cors-configuration AllowOrigins="*",AllowMethods="POST,OPTIONS",AllowHeaders="content-type,authorization",MaxAge=300 \
  --region us-east-1
```

Then re-upload frontend files if `frontend/config.js` changed:

```bash
python3 scripts/upload_frontend_to_s3.py \
  --bucket aster-policy-rag-frontend-851725469799-us-east-1 \
  --region us-east-1
```

Refresh the browser and retry.

## Cleanup

Delete the vector index:

```bash
python3 scripts/delete_opensearch_index.py \
  --endpoint https://3o35kp5w5p9kc8gtzhpa.us-east-1.aoss.amazonaws.com \
  --index aster-policy-rag-index \
  --region us-east-1
```

Then delete, in this order:

1. API Gateway API
2. Lambda functions
3. OpenSearch Serverless collection
4. S3 objects and buckets
5. IAM policies and roles
