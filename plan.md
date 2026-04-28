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
python3 -m venv venv
source venv/bin/activate
echo "gcp-key.json" >> .gitignore
```

### 2.2 Install Dependencies - This needs work to align with current repo
Create a `requirements.txt` file containing the necessary production and testing libraries:

```text
functions-framework==3.*
google-cloud-bigquery==3.*
pytest==7.*
requests==2.*
```

Install them via `pip`:
```bash
pip install -r requirements.txt
```

### 2.3 Configure Local Authentication
Point your local environment to the Service Account key:

```bash
export GOOGLE_APPLICATION_CREDENTIALS="$(pwd)/gcp-key.json"
```

---

## Phase 3: Application Code & The Test Suite

### 3.1 The Cloud Function (`main.py`)
Write the listener using the Functions Framework. 

```python
import os
import json
from google.cloud import bigquery
from flask import Request, jsonify

# Initialize client outside the handler for connection pooling
bq_client = bigquery.Client()
PROJECT_ID = os.environ.get('GCP_PROJECT', 'your-project-id')
DATASET_ID = 'health_metrics'
TABLE_ID = 'cgm_data'
TABLE_REF = f"{PROJECT_ID}.{DATASET_ID}.{TABLE_ID}"

def process_xdrip_payload(request: Request):
    """HTTP Cloud Function to ingest xDrip+ data."""
    try:
        payload = request.get_json(silent=True)
        if not payload:
            return jsonify({"error": "Invalid JSON"}), 400

        # xDrip+ arrays often send multiple readings in a list
        if isinstance(payload, list):
            payload = payload[0]

        # Extract values (adapt keys based on actual xDrip+ REST format)
        glucose_value = payload.get('sgv')
        direction = payload.get('direction')
        
        # Identify if this is a test payload sent from our local suite
        is_test = payload.get('_is_test_record', False)

        rows_to_insert = [{
            "timestamp": "AUTO", 
            "glucose_value": glucose_value,
            "direction": direction,
            "raw_data": json.dumps(payload),
            "is_test": is_test
        }]

        errors = bq_client.insert_rows_json(TABLE_REF, rows_to_insert)
        
        if errors:
            return jsonify({"error": errors}), 500
            
        return jsonify({"status": "success", "is_test": is_test}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500
```

### 3.2 The Test Suite (`test_main.py`)
Use `pytest` and `unittest.mock` to validate logic without pinging GCP.

```python
import pytest
from unittest.mock import patch, MagicMock
from main import process_xdrip_payload
from flask import Request

@pytest.fixture
def mock_request():
    request = MagicMock(spec=Request)
    request.get_json.return_value = {
        "sgv": 120,
        "direction": "Flat",
        "_is_test_record": True
    }
    return request

@patch('main.bq_client.insert_rows_json')
def test_successful_payload_parsing(mock_insert, mock_request):
    mock_insert.return_value = [] # No errors from BigQuery
    
    response, status_code = process_xdrip_payload(mock_request)
    
    assert status_code == 200
    assert response.json['status'] == 'success'
    assert response.json['is_test'] is True
    mock_insert.assert_called_once()
```

---

## Phase 4: Local Simulation & Execution

### 4.1 Run the Local Server
Start the Functions Framework emulator to spin up a local listener on port 8080:

```bash
functions-framework --target=process_xdrip_payload --debug
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
*Verify in your BigQuery console that the row was inserted and `is_test` is `TRUE`.*

---

## Phase 5: Deployment to GCP

Once the test suite passes (`pytest test_main.py`), deploy the function using the `gcloud` CLI. Ensure you assign the Service Account created in Phase 1.

```bash
gcloud functions deploy xdrip-listener \
--gen2 \
--runtime=python311 \
--region=us-central1 \
--source=. \
--entry-point=process_xdrip_payload \
--trigger-http \
--allow-unauthenticated \
--service-account=xdrip-listener-sa@your-project-id.iam.gserviceaccount.com
```

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
FROM `your-project-id.health_metrics.cgm_data`
WHERE is_test = FALSE
ORDER BY timestamp DESC
```