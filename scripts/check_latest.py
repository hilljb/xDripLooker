"""Print the 5 most recent rows from cgm_data without running a query job.

Uses list_rows() (Storage read API) so the service account only needs
BigQuery Data Editor — no bigquery.jobs.create permission required.
"""
import os
from google.cloud import bigquery

if not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
    raise EnvironmentError(
        "GOOGLE_APPLICATION_CREDENTIALS is not set.\n"
        "Run: export GOOGLE_APPLICATION_CREDENTIALS=\"$(pwd)/gcp-key.json\""
    )

client = bigquery.Client()

table_ref = client.dataset("health_metrics").table("cgm_data")
fields = ["timestamp", "glucose_value", "direction", "is_test"]
schema = [bigquery.SchemaField(f, "STRING") for f in fields]

rows = list(
    client.list_rows(
        table_ref,
        selected_fields=[
            bigquery.SchemaField("timestamp", "TIMESTAMP"),
            bigquery.SchemaField("glucose_value", "INTEGER"),
            bigquery.SchemaField("direction", "STRING"),
            bigquery.SchemaField("is_test", "BOOLEAN"),
        ],
        max_results=500,
    )
)

if not rows:
    print("No rows found in cgm_data.")
else:
    rows.sort(key=lambda r: r["timestamp"], reverse=True)
    rows = rows[:5]
    header = f"{'timestamp':<35} {'glucose_value':<15} {'direction':<20} {'is_test'}"
    print(header)
    print("-" * len(header))
    for row in rows:
        print(f"{str(row['timestamp']):<35} {str(row['glucose_value']):<15} {str(row['direction']):<20} {row['is_test']}")
