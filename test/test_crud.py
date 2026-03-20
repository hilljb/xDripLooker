"""
MongoDB full-cycle CRUD test for xDripLooker.

Uses only the older standard URI format (mongodb://) with explicit shard hosts —
the same format that xDrip+ and other legacy drivers use.

Cycle executed:
  1. Connect via standard URI
  2. Create a temporary test database + collection
  3. Insert a set of sample documents
  4. Verify every inserted document is retrievable
  5. Delete all inserted documents
  6. Verify the collection is empty
  7. Drop the test database
  8. Verify the database no longer appears in the server listing

Prerequisites:
  1. Copy test/config.json.example to test/config.json and fill in your credentials.
     config.json is gitignored and will never be committed.

Run all tests:
  pytest test/

Run directly (verbose output):
  python test/test_crud.py
"""

import json
import os
import uuid
from pymongo.mongo_client import MongoClient

# ---------------------------------------------------------------------------
# Load credentials from local config (not committed to version control)
# ---------------------------------------------------------------------------
config_path = os.path.join(os.path.dirname(__file__), "config.json")
with open(config_path) as f:
    config = json.load(f)["mongo"]

# --- Standard URI (older driver format) ---
# Lists each replica-set shard host explicitly — mirrors how xDrip+ connects.
shards_str = ",".join(f"{s}:{config['port']}" for s in config["shards"])
uri_standard = (
    f"mongodb://{config['username']}:{config['password']}"
    f"@{shards_str}/"
    f"?authSource={config['auth_source']}"
    f"&tls=true"
    f"&retryWrites=true"
    f"&w=majority"
)

# Use a unique database name so parallel test runs never collide.
TEST_DB_NAME = f"xdriplooker_test_{uuid.uuid4().hex[:8]}"
TEST_COLLECTION = "cycle_test"

# Sample documents to insert — realistic-ish glucose readings.
SAMPLE_DOCS = [
    {"device": "dexcom_g7", "glucose_mgdl": 95,  "trend": "Flat",          "source": "xdrip"},
    {"device": "dexcom_g7", "glucose_mgdl": 102, "trend": "FortyFiveUp",   "source": "xdrip"},
    {"device": "dexcom_g7", "glucose_mgdl": 88,  "trend": "FortyFiveDown", "source": "xdrip"},
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_client() -> MongoClient:
    return MongoClient(uri_standard)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_full_cycle():
    """
    Full CRUD cycle over the standard (older-driver) URI.

    Steps: connect → create db/collection → insert → verify → delete →
           verify empty → drop database → verify database gone.
    """
    print(f"\n--- Full-cycle CRUD test (standard URI) | db: {TEST_DB_NAME} ---")
    client = None
    try:
        # ------------------------------------------------------------------
        # 1. Connect
        # ------------------------------------------------------------------
        print("Step 1: Connecting via standard URI …")
        client = _make_client()
        client.admin.command("ping")
        print("        Connected.")

        db = client[TEST_DB_NAME]
        col = db[TEST_COLLECTION]

        # ------------------------------------------------------------------
        # 2. Insert documents
        # ------------------------------------------------------------------
        print(f"Step 2: Inserting {len(SAMPLE_DOCS)} documents …")
        result = col.insert_many(SAMPLE_DOCS)
        inserted_ids = result.inserted_ids
        assert len(inserted_ids) == len(SAMPLE_DOCS), (
            f"Expected {len(SAMPLE_DOCS)} inserted IDs, got {len(inserted_ids)}"
        )
        print(f"        Inserted IDs: {[str(i) for i in inserted_ids]}")

        # ------------------------------------------------------------------
        # 3. Verify each document is present
        # ------------------------------------------------------------------
        print("Step 3: Verifying inserted documents exist …")
        for doc_id in inserted_ids:
            found = col.find_one({"_id": doc_id})
            assert found is not None, f"Document {doc_id} not found after insert"
        count_after_insert = col.count_documents({})
        assert count_after_insert == len(SAMPLE_DOCS), (
            f"Expected {len(SAMPLE_DOCS)} documents, found {count_after_insert}"
        )
        print(f"        All {count_after_insert} documents verified.")

        # ------------------------------------------------------------------
        # 4. Delete documents
        # ------------------------------------------------------------------
        print("Step 4: Deleting all inserted documents …")
        del_result = col.delete_many({"_id": {"$in": inserted_ids}})
        assert del_result.deleted_count == len(SAMPLE_DOCS), (
            f"Expected {len(SAMPLE_DOCS)} deletions, got {del_result.deleted_count}"
        )
        print(f"        Deleted {del_result.deleted_count} documents.")

        # ------------------------------------------------------------------
        # 5. Verify collection is empty
        # ------------------------------------------------------------------
        print("Step 5: Verifying collection is empty …")
        count_after_delete = col.count_documents({})
        assert count_after_delete == 0, (
            f"Expected 0 documents after deletion, found {count_after_delete}"
        )
        print("        Collection is empty.")

        # ------------------------------------------------------------------
        # 6. Drop the test database
        # ------------------------------------------------------------------
        print("Step 6: Dropping test database …")
        client.drop_database(TEST_DB_NAME)
        print("        Database dropped.")

        # ------------------------------------------------------------------
        # 7. Verify database no longer exists
        # ------------------------------------------------------------------
        print("Step 7: Verifying database is gone …")
        db_list = client.list_database_names()
        assert TEST_DB_NAME not in db_list, (
            f"Database '{TEST_DB_NAME}' still present after drop"
        )
        print("        Database not found in server listing — confirmed gone.")

        print("\nSUCCESS: Full-cycle CRUD test passed.")

    except Exception as e:
        print(f"\nFAILED: {e}")
        raise
    finally:
        # Best-effort cleanup in case the test failed mid-way.
        if client is not None:
            try:
                client.drop_database(TEST_DB_NAME)
            except Exception:
                pass
            client.close()


if __name__ == "__main__":
    test_full_cycle()
