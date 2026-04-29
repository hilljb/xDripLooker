# xDrip+ to BigQuery: Ingestion Pipeline Development Plan

## Architecture Overview
* **Listener:** Python Cloud Function (Generation 2, HTTP Trigger), exposing a Nightscout-compatible REST endpoint (`/api/v1/entries`) so xDrip+ requires no customization.
* **Storage:** BigQuery table schema aligned to the full xDrip+ entry payload.
* **Security:** Dedicated GCP Service Account (Least Privilege) + `Authorization: Basic` header authentication. xDrip+ sends the plaintext password via HTTP Basic Auth; the function hashes it with SHA256 and compares against a stored hash deployed as an environment variable. No client-side pre-hashing required.
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

> **🔨 WORK NEEDED — Schema migration required.** The table was initially created with a minimal schema. The xDrip+ payload (researched below) carries significantly more fields worth retaining. The existing `cgm_data` table will need to be altered or recreated. Altering a BigQuery table to add columns is non-destructive; existing rows receive `NULL` for new columns.

1. Create a dataset in BigQuery (e.g., `health_metrics`). Region: `us-central1`.
2. Create a table (e.g., `cgm_data`) with the following schema, aligned to the full xDrip+ Nightscout entry payload:

| Column | Type | Notes |
|---|---|---|
| `timestamp` | TIMESTAMP | Derived from xDrip+ `date` field (ms epoch ÷ 1000). Reflects the actual reading time, not server arrival time. |
| `glucose_value` | INTEGER | From `sgv` field. mg/dL. |
| `direction` | STRING | Trend arrow from CGM. Values: `DoubleUp`, `SingleUp`, `FortyFiveUp`, `Flat`, `FortyFiveDown`, `SingleDown`, `DoubleDown`, `NOT COMPUTABLE`, `RATE OUT OF RANGE`. |
| `entry_type` | STRING | From `type` field. Values: `sgv` (sensor glucose), `mbg` (meter blood glucose), `cal` (calibration). |
| `device` | STRING | From `device` field. Identifies the xDrip+ device/sensor source. |
| `noise` | INTEGER | Signal noise level at time of reading. xDrip+ scale: 0=none, 1=low, 2=high, 3=high_for_predict, 4=very_high, 5=extreme. |
| `filtered` | FLOAT | Raw filtered value directly from CGM transmitter. |
| `unfiltered` | FLOAT | Raw unfiltered value directly from CGM transmitter. |
| `rssi` | INTEGER | Signal strength from CGM transmitter. |
| `date_string` | STRING | ISO 8601 timestamp string from xDrip+ (`dateString` field). Kept alongside `timestamp` for debugging. |
| `raw_data` | JSON | Entire unmodified entry object. Useful for fields added by future xDrip+ versions. |
| `is_test` | BOOLEAN | **Crucial for filtering test data in Looker Studio.** Real xDrip+ traffic always sets this `FALSE`. Integration tests use a separate mechanism — see Phase 3.2. |

To add missing columns to an existing table without losing data, use `ALTER TABLE` in the BigQuery console or CLI:

```sql
ALTER TABLE `xdriplooker.health_metrics.cgm_data`
  ADD COLUMN IF NOT EXISTS entry_type STRING,
  ADD COLUMN IF NOT EXISTS device STRING,
  ADD COLUMN IF NOT EXISTS noise INT64,
  ADD COLUMN IF NOT EXISTS filtered FLOAT64,
  ADD COLUMN IF NOT EXISTS unfiltered FLOAT64,
  ADD COLUMN IF NOT EXISTS rssi INT64,
  ADD COLUMN IF NOT EXISTS date_string STRING;
```

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

> **🔨 WORK NEEDED** — `main.py` requires significant changes to align with the xDrip+ request format. The current implementation handles a simple POST to `/`, uses a placeholder payload shape, and has no authentication. All three need to change.

The listener uses the Functions Framework. `bq_client` is initialized at module level (outside the handler) so the connection is reused across requests — standard GCP guidance for Cloud Functions.

> **Note:** `PROJECT_ID` falls back to `bq_client.project`, which reads the project directly from `gcp-key.json`. No `GCP_PROJECT` env var is required locally.

**Required changes:**

1. **Path routing** — xDrip+ POSTs to `/api/v1/entries`, not `/`. Flask routing must be added to handle this path. Any other path should return 404.

2. **Authentication** — xDrip+ sends the plaintext password via `Authorization: Basic` header (the standard result of the `password@hostname` URL format). The function must:
   - Decode the Base64 `Authorization` header to extract the plaintext password
   - Hash it with SHA256: `hashlib.sha256(password.encode()).hexdigest()`
   - Compare against `API_SECRET_HASH`, an environment variable set at deploy time
   - Return 401 if the header is missing or the hashes do not match

   **Why this approach over the Nightscout SHA1 convention:** The connection is already HTTPS, so the plaintext password is encrypted in transit — there is no benefit to pre-hashing on the client. Hashing on the server with SHA256 (stronger than SHA1) means the plaintext secret never persists anywhere; only the hash is stored. This removes any dependency on GCP Secret Manager and is straightforwardly secure for a personal project.

   To pre-compute the hash to store at deploy time:
   ```bash
   python3 -c "import hashlib; print(hashlib.sha256(b'your_password_here').hexdigest())"
   ```

3. **Payload parsing** — xDrip+ sends a JSON **array** of entry objects. Each entry has a different shape depending on `type` (`sgv`, `mbg`, or `cal`). The function must iterate the array, extract the correct fields per entry, and derive `timestamp` from the `date` field (milliseconds since epoch ÷ 1000) rather than using server arrival time.

   **xDrip+ SGV entry shape** (the most common type — sensor glucose value):
   ```json
   [
     {
       "type": "sgv",
       "date": 1650000000000,
       "dateString": "2022-04-15T06:40:00.000Z",
       "sgv": 105,
       "direction": "FortyFiveUp",
       "noise": 1,
       "filtered": 192256,
       "unfiltered": 194944,
       "rssi": 100,
       "device": "xDrip LibreReceiver"
     }
   ]
   ```

4. **`is_test` handling** — Real xDrip+ traffic does not include `_is_test_record`. All live requests set `is_test = False`. Integration tests should use a distinct `device` value (e.g., `"xDrip-test"`) to identify test rows, but `is_test` itself will be `False` for all traffic through the Nightscout endpoint. The flag remains useful for any rows inserted via a separate test-only path if one is added later.

### 3.2 The Test Suite

> **🔨 WORK NEEDED** — Unit tests in `test_main.py` must be updated to cover the new path routing, authentication header checking, and xDrip+ payload format. The two-layer testing structure (unit tests + manual `curl` integration) remains correct; only the test cases need rewriting.

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

> **🔨 WORK NEEDED** — The curl command below reflects the real xDrip+ payload format and Nightscout-compatible path. This test will not pass until the `main.py` changes from Phase 3.1 are implemented (path routing and auth).

Once Phase 3.1 is complete, the correct integration test mimics what xDrip+ actually sends. xDrip+ uses HTTP Basic Auth — `curl`'s `-u` flag handles the Base64 encoding automatically, exactly as xDrip+ does:

```bash
curl -s -X POST http://localhost:8080/api/v1/entries \
  -u "your_password_here:" \
  -H "Content-Type: application/json" \
  -d '[{
    "type": "sgv",
    "date": 1650000000000,
    "dateString": "2022-04-15T06:40:00.000Z",
    "sgv": 105,
    "direction": "FortyFiveUp",
    "noise": 1,
    "filtered": 192256,
    "unfiltered": 194944,
    "rssi": 100,
    "device": "xDrip-test"
  }]'
```

A successful response looks like:
```json
{
  "inserted": 1,
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
2022-04-15 06:40:00+00:00           105             FortyFiveUp          False
```

Note that `timestamp` is now derived from the xDrip+ `date` field, not server arrival time, and `is_test` is `False` for real-shaped payloads.

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

#### Prerequisites

**`requirements.txt` must exist in the project root.** GCP Cloud Functions installs Python dependencies from this file at build time. The conda `environment.yml` is only for local development — GCP does not use it. The file should contain only the production runtime dependencies (not pytest or other dev tools):

```text
functions-framework==3.8.3
google-cloud-bigquery==3.41.0
```

Flask does not need to be listed explicitly — `functions-framework` declares it as a dependency and GCP will install it transitively.

**The `API_SECRET_HASH` environment variable must be set on the function.** The function receives the plaintext password from xDrip+ via HTTP Basic Auth, SHA256-hashes it, and compares against this stored value. Compute it locally before deploying:

```bash
python3 -c "import hashlib; print(hashlib.sha256(b'your_password_here').hexdigest())"
```

Pass it to the deploy command by appending `--set-env-vars API_SECRET_HASH=<hash>`. The hash is visible in the Cloud Console UI under the function's configuration tab, which is acceptable — the hash cannot be reversed to the original password and the endpoint is write-only.

**GCP APIs must be enabled on the project.** On a new GCP project, the Cloud Functions, Cloud Run, Cloud Build, and Artifact Registry APIs are disabled by default. Enable them all at once (only needs to be done once per project):

```bash
gcloud services enable \
  cloudfunctions.googleapis.com \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  --project=xdriplooker
```

**Verify `gcp-key.json` is excluded from the upload.** The `--source=.` flag packages the current directory. The `*.json` rule in `.gitignore` covers this — `gcloud` auto-generates a `.gcloudignore` from `.gitignore` on first deploy if one doesn't exist.

#### Deploy command

The `--project` flag is included explicitly so the command always targets `xdriplooker` regardless of what `gcloud config` is set to locally. This prevents accidentally deploying to a different active project:

```bash
gcloud functions deploy xdrip-listener \
  --project=xdriplooker \
  --gen2 \
  --runtime=python312 \
  --region=us-central1 \
  --source=. \
  --entry-point=process_xdrip_payload \
  --trigger-http \
  --allow-unauthenticated \
  --service-account=xdriplooker@xdriplooker.iam.gserviceaccount.com
```

A successful deploy takes roughly 2 minutes and ends with output like:

```
state: ACTIVE
url: https://us-central1-xdriplooker.cloudfunctions.net/xdrip-listener
```

**Line-by-line notes:**

- **`deploy xdrip-listener`** — The public-facing resource name in GCP. Does not need to match anything in the code.

- **`--project=xdriplooker`** — Explicitly targets this project. Without this flag, `gcloud` uses whatever project `gcloud config get-value project` returns, which may be something else entirely.

- **`--gen2`** — Generation 2 Cloud Functions run on Cloud Run infrastructure. Better cold-start performance, longer request timeouts (up to 60 min vs. 9 min for Gen 1), and concurrency support. Gen 2 is the current standard.

- **`--runtime=python312`** — GCP Cloud Functions does not yet support Python 3.14, which is what the local `xdriplooker` conda environment uses. `python312` (3.12) is the newest runtime GCP currently offers. The code here uses no 3.13/3.14-specific features, so this is safe. When GCP adds a newer runtime, this is the only flag that needs updating.

- **`--region=us-central1`** — Must match the region of your BigQuery dataset (also `us-central1`, set in Phase 1.2). Mismatched regions can introduce latency and cross-region egress costs.

- **`--source=.`** — Uploads the current directory as the deployment package.

- **`--entry-point=process_xdrip_payload`** — The Python function GCP invokes on each HTTP request. Must match the function name in `main.py` exactly.

- **`--trigger-http`** — Makes this an HTTP-triggered function. xDrip+ POSTs directly to a URL, so HTTP is the correct trigger type.

- **`--allow-unauthenticated`** — Allows any device to POST to this URL without a GCP identity token. This is intentional: the xDrip+ app running on your phone has no GCP credentials and no mechanism to sign requests, so authenticated endpoints are not compatible with it. The risk is bounded — the endpoint only writes data, returns nothing sensitive, and the service account can only reach `cgm_data`. The worst-case outcome of someone discovering the URL is junk rows in your CGM table. If that becomes a concern, a lightweight mitigation is to add a shared-secret check in the handler (a hardcoded token xDrip+ can be configured to include as a custom header or body field).

- **`--service-account=xdriplooker@xdriplooker.iam.gserviceaccount.com`** — Binds the function's *runtime* identity to the dedicated SA from Phase 1, not the deploying identity. This enforces least privilege: once deployed, the function can only do what BigQuery Data Editor allows, nothing else in the project.

#### Smoke test

Once deployed, verify the live endpoint responds correctly:

```bash
curl -s -X POST https://us-central1-xdriplooker.cloudfunctions.net/xdrip-listener \
  -H "Content-Type: application/json" \
  -d '{"sgv": 110, "direction": "Flat", "date": 1650000000000, "_is_test_record": true}'
```

Expected response:
```json
{"is_test": true, "status": "success"}
```

### 5.5 Updating and Recovering the Deployed Function

#### Updating the function (normal workflow)

Re-running the same `gcloud functions deploy` command with the same function name updates it in place. GCP builds the new version, waits for it to be healthy, then shifts traffic to it — the old revision stays alive and continues serving requests until the new one is confirmed. **There is no downtime.** The trigger URL never changes on an update.

#### If a deployment fails mid-way

If the new deployment fails (bad code, missing dependency, etc.), GCP does **not** automatically roll back, but the previous healthy revision continues serving traffic since Gen 2 keeps it alive until the new one is confirmed. A failed deploy leaves the function in a working state. Verify which revision is active:

```bash
gcloud run revisions list --service=xdrip-listener --region=us-central1 --project=xdriplooker
```

Fix the issue in your code, then re-run the deploy command.

#### Deleting and redeploying from scratch

Only do this if the function is in a corrupted state that a normal re-deploy cannot recover from (rare). **Important:** deleting the function permanently destroys the trigger URL. If xDrip+ is already configured to point at it, you will need to reconfigure the app on your phone with the new URL after redeployment.

```bash
# Delete the function
gcloud functions delete xdrip-listener --region=us-central1 --gen2 --project=xdriplooker

# Redeploy using the same command as 5.4
gcloud functions deploy xdrip-listener \
  --project=xdriplooker \
  --gen2 \
  --runtime=python312 \
  --region=us-central1 \
  --source=. \
  --entry-point=process_xdrip_payload \
  --trigger-http \
  --allow-unauthenticated \
  --service-account=xdriplooker@xdriplooker.iam.gserviceaccount.com
```

---

## Phase 6: xDrip+ Configuration & Analytics Filtering

### 6.1 Configure xDrip+ on your Phone
1. Open xDrip+ and navigate to **Settings > Cloud Upload > REST API**.
2. Enter the trigger URL: `https://us-central1-xdriplooker.cloudfunctions.net/xdrip-listener`
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