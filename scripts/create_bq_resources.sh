#!/usr/bin/env bash
# Creates the BigQuery dataset and cgm_data table for xDripLooker.
#
# Prerequisites:
#   - gcloud is installed and authenticated (gcloud auth list)
#   - bq CLI is available (ships with the Google Cloud SDK)
#
# Usage (from project root):
#   bash scripts/create_bq_resources.sh
#
# The script is idempotent: re-running it is safe if the dataset or table
# already exist.

set -euo pipefail

PROJECT_ID="xdriplooker"
DATASET_ID="health_metrics"
TABLE_ID="cgm_data"
REGION="us-central1"

echo "==> Project : ${PROJECT_ID}"
echo "==> Dataset : ${DATASET_ID}  (region: ${REGION})"
echo "==> Table   : ${TABLE_ID}"
echo ""

# ---------------------------------------------------------------------------
# 1. Create the dataset
# ---------------------------------------------------------------------------
if bq show --project_id="${PROJECT_ID}" "${PROJECT_ID}:${DATASET_ID}" \
     > /dev/null 2>&1; then
  echo "[skip] Dataset '${DATASET_ID}' already exists."
else
  echo "[create] Creating dataset '${DATASET_ID}' in ${REGION}..."
  bq mk \
    --dataset \
    --location="${REGION}" \
    --project_id="${PROJECT_ID}" \
    "${PROJECT_ID}:${DATASET_ID}"
  echo "[ok] Dataset created."
fi

# ---------------------------------------------------------------------------
# 2. Create the table
# ---------------------------------------------------------------------------
if bq show --project_id="${PROJECT_ID}" \
     "${PROJECT_ID}:${DATASET_ID}.${TABLE_ID}" \
     > /dev/null 2>&1; then
  echo "[skip] Table '${TABLE_ID}' already exists."
else
  echo "[create] Creating table '${TABLE_ID}'..."

  # Write schema to a temp file so each field can be documented clearly.
  SCHEMA_FILE=$(mktemp)
  trap 'rm -f "${SCHEMA_FILE}"' EXIT

  cat > "${SCHEMA_FILE}" << 'EOF'
[
  {
    "name": "timestamp",
    "type": "TIMESTAMP",
    "mode": "NULLABLE",
    "description": "Reading time derived from xDrip+ date field (ms epoch / 1000). Reflects actual sensor time, not server arrival time."
  },
  {
    "name": "glucose_value",
    "type": "INTEGER",
    "mode": "NULLABLE",
    "description": "Sensor glucose value in mg/dL. From xDrip+ sgv field."
  },
  {
    "name": "direction",
    "type": "STRING",
    "mode": "NULLABLE",
    "description": "CGM trend arrow. Values: DoubleUp, SingleUp, FortyFiveUp, Flat, FortyFiveDown, SingleDown, DoubleDown, NOT COMPUTABLE, RATE OUT OF RANGE."
  },
  {
    "name": "entry_type",
    "type": "STRING",
    "mode": "NULLABLE",
    "description": "From xDrip+ type field. Values: sgv (sensor glucose), mbg (meter blood glucose), cal (calibration)."
  },
  {
    "name": "device",
    "type": "STRING",
    "mode": "NULLABLE",
    "description": "xDrip+ device/sensor source identifier."
  },
  {
    "name": "noise",
    "type": "INTEGER",
    "mode": "NULLABLE",
    "description": "Signal noise level. xDrip+ scale: 0=none, 1=low, 2=high, 3=high_for_predict, 4=very_high, 5=extreme."
  },
  {
    "name": "filtered",
    "type": "FLOAT",
    "mode": "NULLABLE",
    "description": "Raw filtered value directly from CGM transmitter."
  },
  {
    "name": "unfiltered",
    "type": "FLOAT",
    "mode": "NULLABLE",
    "description": "Raw unfiltered value directly from CGM transmitter."
  },
  {
    "name": "rssi",
    "type": "INTEGER",
    "mode": "NULLABLE",
    "description": "Signal strength from CGM transmitter."
  },
  {
    "name": "date_string",
    "type": "STRING",
    "mode": "NULLABLE",
    "description": "ISO 8601 timestamp string from xDrip+ dateString field. Stored alongside timestamp for debugging."
  },
  {
    "name": "raw_data",
    "type": "JSON",
    "mode": "NULLABLE",
    "description": "Entire unmodified xDrip+ entry object. Captures any fields added by future xDrip+ versions."
  },
  {
    "name": "is_test",
    "type": "BOOLEAN",
    "mode": "NULLABLE",
    "description": "True only for rows inserted via a test-only code path. Real xDrip+ traffic always sets this FALSE. Filter WHERE is_test = FALSE in Looker Studio."
  }
]
EOF

  bq mk \
    --table \
    --project_id="${PROJECT_ID}" \
    --schema="${SCHEMA_FILE}" \
    --time_partitioning_type=DAY \
    --time_partitioning_field=timestamp \
    --clustering_fields=timestamp \
    "${PROJECT_ID}:${DATASET_ID}.${TABLE_ID}"

  echo "[ok] Table created."
fi

echo ""
echo "Done. Verify in the BigQuery console:"
echo "  https://console.cloud.google.com/bigquery?project=${PROJECT_ID}"
