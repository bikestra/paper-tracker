# Deployment Guide

Deploy Paper Tracker to Google Cloud Run with Turso database and IAP authentication.

## Prerequisites

- Google Cloud account with billing enabled
- `gcloud` CLI installed and authenticated
- Turso account (free at turso.tech)

## 1. Create Turso Database

```bash
# Install Turso CLI
curl -sSfL https://get.tur.so/install.sh | bash

# Login
turso auth login

# Create database
turso db create paper-tracker

# Get connection URL
turso db show paper-tracker --url

# Create auth token
turso db tokens create paper-tracker
```

Save the URL and token. Your DATABASE_URL will be:
```
libsql://<your-db>.turso.io?authToken=<your-token>
```

## 2. Deploy to Cloud Run

```bash
# Set your project
export PROJECT_ID=your-gcp-project-id
gcloud config set project $PROJECT_ID

# Enable required APIs
gcloud services enable run.googleapis.com
gcloud services enable cloudbuild.googleapis.com
gcloud services enable iap.googleapis.com

# Deploy (replace DATABASE_URL with your Turso URL)
gcloud run deploy paper-tracker \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars "DATABASE_URL=libsql://your-db.turso.io?authToken=your-token"
```

Note the service URL (e.g., `https://paper-tracker-xxxxx-uc.a.run.app`)

## 3. Set Up IAP (Identity-Aware Proxy)

### Create OAuth Consent Screen
1. Go to [APIs & Services > OAuth consent screen](https://console.cloud.google.com/apis/credentials/consent)
2. Select "External" (or Internal if using Workspace)
3. Fill in app name, support email
4. Add your email to test users

### Create OAuth Credentials
1. Go to [APIs & Services > Credentials](https://console.cloud.google.com/apis/credentials)
2. Create OAuth 2.0 Client ID (Web application)
3. Add authorized redirect URI: `https://iap.googleapis.com/v1/oauth/clientIds/<CLIENT_ID>:handleRedirect`

### Enable IAP on Cloud Run
1. Go to [Security > Identity-Aware Proxy](https://console.cloud.google.com/security/iap)
2. Find your Cloud Run service
3. Toggle IAP on
4. Add yourself as IAP-secured Web App User:
   - Click the service
   - Add principal: your email
   - Role: IAP-secured Web App User

## 4. Access Your App

Visit your Cloud Run URL. You'll be prompted to log in with your Google account.

## Updating the App

```bash
gcloud run deploy paper-tracker --source . --region us-central1
```

## Local Development

```bash
# Use local SQLite
unset DATABASE_URL
source .venv/bin/activate
make db-upgrade
make run
```
