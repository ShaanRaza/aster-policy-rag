# Aster Policy RAG

An end-to-end Retrieval Augmented Generation (RAG) application built on AWS.

## What it does

Answers questions from PDF policy documents using semantic search and AI generation.
Upload a policy PDF, ask a question in natural language, get a cited answer back.

## Architecture

PDF → S3 → Ingest Lambda → Bedrock (embeddings) → OpenSearch (vector store)
Question → API Gateway → Query Lambda → Bedrock (search + generate) → Answer


## AWS Services Used

- **S3** — PDF storage and static frontend hosting
- **AWS Lambda** — PDF ingestion and RAG query handling
- **Amazon Bedrock** — Titan embeddings + Nova Lite generation
- **OpenSearch Serverless** — Vector search index
- **API Gateway** — HTTP API for the frontend

## Project Structure

frontend/ Static website files
lambdas/ Lambda function code
ingest_handler/ PDF ingestion Lambda
query_handler/ RAG query Lambda
shared/ Shared clients and pipeline code
scripts/ Setup and deployment scripts
iam/ IAM and OpenSearch policy templates
config/ Reference configuration
examples/ Sample questions


## Setup

See the workshop steps for full deployment instructions.

**Prerequisites:**
- Python 3.12+
- AWS CLI configured
- Amazon Bedrock model access (Titan Embeddings V2 + Nova Lite)

**Quick start:**
```bash
# Install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Generate sample PDFs
python3 scripts/generate_policy_pdfs.py

# Deploy infrastructure (see workshop steps)
```

## Sample Questions

- What approvals are required for purchases above USD 5,000?
- How many sick days do employees get?
- What is the hotel reimbursement limit for international travel?
- Can employees work remotely from another country?

