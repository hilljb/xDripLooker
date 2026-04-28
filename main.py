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