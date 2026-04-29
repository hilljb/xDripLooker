"""
pytest configuration loaded before any test module is imported.

bigquery.Client() is called at module level in main.py (connection pooling
for Cloud Functions). The client constructor reads credentials immediately,
so GOOGLE_APPLICATION_CREDENTIALS must be set before main.py is imported —
i.e., here, not in a fixture (fixtures run after collection/import).

No real BigQuery calls are made during tests; insert_rows_json is mocked
in each test that exercises the handler.
"""
import os
from pathlib import Path

creds_path = Path(__file__).parent.parent / "gcp-key.json"
if creds_path.exists():
    os.environ.setdefault("GOOGLE_APPLICATION_CREDENTIALS", str(creds_path))
