# xDrip+ to BigQuery: Ingestion Pipeline Development Plan

## Architecture Overview
* **Listener:** Python Cloud Function (Generation 2, HTTP Trigger).
* **Storage:** BigQuery table with a specific schema to accommodate xDrip+ payloads and environment tagging.
* **Security:** Dedicated GCP Service Account (Least Privilege).
* **Local Dev:** Google Functions Framework for local execution, `pytest` for the test suite.

---

## Phase 1: GCP Infrastructure & Security Setup

### 1.1 Create a Dedicated Service Account
To avoid using personal Google credentials, create a specific Service Account (SA) that only has permission to write to BigQuery.
1. Navigate to **IAM & Admin > Service Accounts** in the GCP Console.
2. Create a new SA (e.g., `xdrip-listener-sa@your-project-id.iam.gserviceaccount.com`).
3. Grant this SA the **BigQuery Data Editor** role.
4. Generate and download a JSON key for this SA. Save it locally as `gcp-key.json` (ensure this is immediately added to your `.gitignore`).

### 1.2 Provision the BigQuery Dataset & Table
1. Create a dataset in BigQuery (e.g., `health_metrics`). I'm using us-central1 for a region.
2. Create a table (e.g., `cgm_data`) with the following schema:
   * `timestamp` (TIMESTAMP) - Default to current time if not provided.
   * `glucose_value` (INTEGER)
   * `direction` (STRING)
   * `raw_data` (JSON) - Useful for storing the entire unmodified payload.
   * `is_test` (BOOLEAN) - **Crucial for filtering out your test suite data in Looker Studio.**

---

## Phase 2: Local Development Environment

### 2.1 Repository & Environment Initialization
From your terminal, set up the project structure:

```bash
mkdir xdrip-bq-listener && cd xdrip-bq-listener
git init
echo "gcp-key.json" >> .gitignore
```

### 2.2 Conda Environment Setup
This project uses a conda environment named `xdriplooker` (Python 3.14). The environment definition is exported to `environment.yml` in this repo.

To recreate the environment on a new machine:
```bash
conda env create -f environment.yml
conda activate xdriplooker
```

To activate the existing environment:
```bash
conda activate xdriplooker
```

To update `environment.yml` after installing new packages:
```bash
conda env export -n xdriplooker --no-builds > environment.yml
```

### 2.3 Configure Local Authentication
Point your local environment to the Service Account key. **This must be re-exported in every new shell session** — it is not persisted automatically. Run it from the project root so the relative path resolves correctly.

```bash
export GOOGLE_APPLICATION_CREDENTIALS="$(pwd)/gcp-key.json"
```

> **Note:** `bigquery.Client()` is called at module import time in `main.py`. If this variable is not set when you start `functions-framework`, the process will fail immediately before serving any requests. See Phase 4.1 for the full startup sequence.

---

## Phase 3: Application Code & The Test Suite

### 3.1 The Cloud Function (`main.py`)
The listener uses the Functions Framework. `bq_client` is initialized at module level (outside the handler) so the connection is reused across requests — standard GCP guidance for Cloud Functions.

> **Note:** `PROJECT_ID` falls back to `bq_client.project`, which reads the project directly from `gcp-key.json`. No `GCP_PROJECT` env var is required locally.

### 3.2 The Test Suite
The project has two complementary layers of testing:

| Layer | Files | Hits GCP? | When to run |
|---|---|---|---|
| **Unit tests** (`pytest`) | `test_main.py`, `conftest.py` | No — BQ is fully mocked | Before every commit |
| **Manual integration** (`curl`) | `functions-framework` + shell | Yes — real BigQuery write | When verifying end-to-end wiring |

**Why two files for unit tests?**

`bigquery.Client()` is called at module import time. pytest imports `test_main.py` → which imports `main.py` → which calls `bigquery.Client()` before any mock can intercept it. `conftest.py` is loaded by pytest *before* any test module is imported, so it sets `GOOGLE_APPLICATION_CREDENTIALS` in time for the constructor to succeed. Once the client exists, `test_main.py` mocks out `insert_rows_json` so no real API call is ever made.

A Flask app context fixture is also required because `jsonify()` needs one — under `functions-framework` Flask provides it automatically, but a bare pytest call does not.

---

## Phase 4: Local Simulation & Execution

### 4.1 Run the Local Server

The BigQuery client initializes at import time and resolves credentials via Google's [Application Default Credentials](https://cloud.google.com/docs/authentication/application-default-credentials) chain. Locally, that chain only has two realistic options: the `GOOGLE_APPLICATION_CREDENTIALS` environment variable pointing at `gcp-key.json`, or a `gcloud auth application-default login` session. **You must export the variable in the same shell session before starting the server**, otherwise the import fails immediately with `DefaultCredentialsError`.

```bash
conda activate xdriplooker
export GOOGLE_APPLICATION_CREDENTIALS="$(pwd)/gcp-key.json"
functions-framework --target=process_xdrip_payload --debug
```

A successful start looks like:
```
* Serving Flask app 'process_xdrip_payload'
* Debug mode: on
* Running on http://127.0.0.1:8080
```

#### Killing an orphaned server process
If the server was started in a terminal that was closed (or crashed), port 8080 stays occupied. Kill it before trying again:

```bash
# Find and kill whatever is holding port 8080
lsof -ti :8080 | xargs kill -9

# Confirm the port is free
lsof -i :8080
```

### 4.2 Simulate the xDrip+ POST Request
From another terminal window, fire a synthetic payload at your local server:

```bash
curl -X POST http://localhost:8080 \
-H "Content-Type: application/json" \
-d '{
    "sgv": 105,
    "direction": "FortyFiveUp",
    "date": 1650000000000,
    "_is_test_record": true
}'
```
A successful response looks like:
```json
{
  "is_test": true,
  "status": "success"
}
```

To verify the row landed in BigQuery, run the included helper script from the project root (make sure the conda environment is active and `GOOGLE_APPLICATION_CREDENTIALS` is exported):

```bash
python check_latest.py
```

Expected output:
```
timestamp                           glucose_value   direction            is_test
--------------------------------------------------------------------------------
2026-04-28 17:04:39.115556+00:00    105             FortyFiveUp          True
```

The script uses `list_rows()` (the BigQuery Storage read API) rather than a query job, so it works with the **BigQuery Data Editor** role already on the service account — no additional IAM permissions needed.

---

## Phase 5: Deployment to GCP

### 5.1 Install the Google Cloud SDK (`gcloud`)

`gcloud` is a standalone system-level CLI tool — it is **not** a Python package and is not part of the `xdriplooker` conda environment. It must be installed separately before any deployment steps.

The recommended approach on macOS is via Homebrew:

```bash
brew install --cask google-cloud-sdk
```

Verify the installation:

```bash
gcloud --version
```

You should see output like:
```
Google Cloud SDK 549.0.1
```

If you don't have Homebrew, or prefer a manual install, download the SDK directly from [https://cloud.google.com/sdk/docs/install](https://cloud.google.com/sdk/docs/install) and follow the instructions for your OS.

### 5.2 Pre-deployment Checklist
Before deploying, confirm both testing layers are green:

**Unit tests** — validates function logic; no credentials or running server needed:
```bash
conda activate xdriplooker
pytest test_main.py -v
```

**Manual integration test** — confirms live BigQuery connectivity (Phase 4):
- `functions-framework` server started and returned `{"status": "success"}`
- `python check_latest.py` shows the row in BigQuery

### 5.3 Authenticate `gcloud` and Verify Deployment Permissions

> **Two separate credential systems are in use in this project — do not confuse them:**
>
> - `GOOGLE_APPLICATION_CREDENTIALS` / `gcp-key.json` — used by the Python code (locally and at runtime in GCP) to authenticate the BigQuery client. This belongs to the dedicated service account with only BigQuery Data Editor permissions.
> - `gcloud` CLI credentials — used by *you* to deploy infrastructure. These are your personal Google account credentials and must have IAM permissions to create Cloud Functions, Cloud Run services, and bind service accounts. If `GOOGLE_APPLICATION_CREDENTIALS` is set in your shell when you run `gcloud`, it does **not** affect `gcloud` — the two systems are completely independent.
>
> Running `gcloud functions deploy` as the service account identity would fail; that SA has no Cloud Functions or Cloud Run permissions.

#### Step 1: Authenticate

Confirm `gcloud` is authenticated with your personal Google account:

```bash
gcloud auth list
```

If your account is not listed as active, or if you see an `invalid_grant: Bad Request` error (which means your token has expired — this happens periodically even on previously authenticated machines), log in again:

```bash
gcloud auth login
```

This opens a browser window for Google OAuth. Once complete, confirm the active account:

```bash
gcloud config get-value account
```

#### Step 2: Set the Active Project

`gcloud` deploys to whatever project is currently active — which may not be `xdriplooker` if you use `gcloud` for other GCP projects. Set it explicitly:

```bash
gcloud config set project xdriplooker
```

#### Step 3: Verify Deployment Permissions

Deploying a Gen 2 Cloud Function requires your personal account to hold at least these roles on the project:

| Role | Why it's needed |
|---|---|
| `roles/cloudfunctions.developer` | Create and update Cloud Functions |
| `roles/run.admin` | Gen 2 functions deploy to Cloud Run under the hood |
| `roles/iam.serviceAccountUser` | Bind the runtime SA to the function |
| `roles/storage.admin` or `roles/artifactregistry.writer` | Upload the source package |

If you are the project owner (`roles/owner`), all of the above are already included and you can skip ahead.

Check your roles on the project:

```bash
gcloud projects get-iam-policy xdriplooker \
  --flatten="bindings[].members" \
  --format="table(bindings.role)" \
  --filter="bindings.members:YOUR_EMAIL@gmail.com"
```

Replace `YOUR_EMAIL@gmail.com` with your Google account. If `roles/owner` appears in the output, you have full permissions. Example output:

```
ROLE
roles/owner
```

#### If permissions are missing

If your account is not the project owner and the required roles are absent, someone with Owner or IAM Admin access on the project must grant them. The minimum set can be granted via the GCP Console (**IAM & Admin > IAM > Grant Access**) or via `gcloud`:

```bash
# Run as project owner / IAM admin, substituting the account that needs access
gcloud projects add-iam-policy-binding xdriplooker \
  --member="user:DEPLOYER_EMAIL@gmail.com" \
  --role="roles/cloudfunctions.developer"

gcloud projects add-iam-policy-binding xdriplooker \
  --member="user:DEPLOYER_EMAIL@gmail.com" \
  --role="roles/run.admin"

gcloud projects add-iam-policy-binding xdriplooker \
  --member="user:DEPLOYER_EMAIL@gmail.com" \
  --role="roles/iam.serviceAccountUser"

gcloud projects add-iam-policy-binding xdriplooker \
  --member="user:DEPLOYER_EMAIL@gmail.com" \
  --role="roles/artifactregistry.writer"
```

Once all three steps above are confirmed, proceed to 5.4.

### 5.4 Deploy to GCP

Before running this command, verify that `gcp-key.json` is listed in `.gcloudignore` (or `.gitignore` — gcloud respects both). The `--source=.` flag uploads the entire current directory; you do not want the service account key bundled into the deployment artifact.

```bash
gcloud functions deploy xdrip-listener \
--gen2 \
--runtime=python312 \
--region=us-central1 \
--source=. \
--entry-point=process_xdrip_payload \
--trigger-http \
--allow-unauthenticated \
--service-account=xdriplooker@xdriplooker.iam.gserviceaccount.com
```

**Line-by-line notes:**

- **`deploy xdrip-listener`** — The public-facing resource name in GCP. Does not need to match anything in the code.

- **`--gen2`** — Generation 2 Cloud Functions run on Cloud Run infrastructure. Better cold-start performance, longer request timeouts (up to 60 min vs. 9 min for Gen 1), and concurrency support. Gen 2 is the current standard.

- **`--runtime=python312`** — GCP Cloud Functions does not yet support Python 3.14, which is what the local `xdriplooker` conda environment uses. `python312` (3.12) is the newest runtime GCP currently offers. The code here uses no 3.13/3.14-specific features, so this is safe. When GCP adds a newer runtime, this is the only flag that needs updating.

- **`--region=us-central1`** — Must match the region of your BigQuery dataset (also `us-central1`, set in Phase 1.2). Mismatched regions can introduce latency and cross-region egress costs.

- **`--source=.`** — Uploads the current directory as the deployment package. See the `.gcloudignore` note above.

- **`--entry-point=process_xdrip_payload`** — The Python function GCP invokes on each HTTP request. Must match the function name in `main.py` exactly.

- **`--trigger-http`** — Makes this an HTTP-triggered function. xDrip+ POSTs directly to a URL, so HTTP is the correct trigger type.

- **`--allow-unauthenticated`** — Allows any device to POST to this URL without a GCP identity token. This is intentional: the xDrip+ app running on your phone has no GCP credentials and no mechanism to sign requests, so authenticated endpoints are not compatible with it. The risk is bounded — the endpoint only writes data, returns nothing sensitive, and the service account can only reach `cgm_data`. The worst-case outcome of someone discovering the URL is junk rows in your CGM table. If that becomes a concern, a lightweight mitigation is to add a shared-secret check in the handler (a hardcoded token xDrip+ can be configured to include as a custom header or body field).

- **`--service-account=xdriplooker@xdriplooker.iam.gserviceaccount.com`** — Binds the function's *runtime* identity to the dedicated SA from Phase 1, not the deploying identity. This enforces least privilege: once deployed, the function can only do what BigQuery Data Editor allows, nothing else in the project.

---

## Phase 6: xDrip+ Configuration & Analytics Filtering

### 6.1 Configure xDrip+ on your Phone
1. Open xDrip+ and navigate to **Settings > Cloud Upload > REST API**.
2. Enter the trigger URL provided by GCP after deployment (e.g., `https://us-central1-your-project.cloudfunctions.net/xdrip-listener`).
3. Enable the upload.

### 6.2 Looker Studio Configuration
To ensure test data is ignored in your live household dashboard:
1. Add BigQuery as your Data Source in Looker Studio.
2. Select **Custom Query** instead of the raw table.
3. Use the following SQL to filter out CI/CD and local testing records:

```sql
SELECT 
  timestamp, 
  glucose_value, 
  direction 
FROM `xdriplooker.health_metrics.cgm_data`
WHERE is_test = FALSE
ORDER BY timestamp DESC
```