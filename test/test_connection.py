"""
MongoDB connection tests for xDripLooker.

Tests both connection URI formats:
  - SRV format  (modern drivers, mongodb+srv://)
  - Standard format (older drivers, explicit shard hosts, mongodb://)

Prerequisites:
  1. Copy test/config.json.example to test/config.json and fill in your credentials.
     config.json is gitignored and will never be committed.

Run all tests:
  pytest test/

Run directly (also prints connection details):
  python test/test_connection.py
"""

import json
import os
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi

# ---------------------------------------------------------------------------
# Load credentials from local config (not committed to version control)
# ---------------------------------------------------------------------------
config_path = os.path.join(os.path.dirname(__file__), "config.json")
with open(config_path) as f:
    config = json.load(f)["mongo"]

# --- URI 1: Newer SRV format ---
# Used by most modern drivers; a single hostname, DNS resolves the replica set members.
uri_srv = (
    f"mongodb+srv://{config['username']}:{config['password']}"
    f"@{config['host']}/?appName={config['app_name']}"
)

# --- URI 2: Older standard format ---
# Used by drivers that do not support the +srv scheme (e.g. some mobile SDKs).
# Lists each replica-set shard host explicitly with its port.
shards_str = ",".join(f"{s}:{config['port']}" for s in config["shards"])
uri_standard = (
    f"mongodb://{config['username']}:{config['password']}"
    f"@{shards_str}/"
    f"?authSource={config['auth_source']}"
    f"&tls=true"
    f"&retryWrites=true"
    f"&w=majority"
)

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_srv():
    """Test connection using the modern mongodb+srv URI (pytest + direct run)."""
    print("\n--- Testing SRV connection (modern driver format) ---")
    print(f"Host: {config['host']}")
    client = None
    try:
        client = MongoClient(uri_srv, server_api=ServerApi("1"))
        client.admin.command("ping")
        print("SUCCESS: Pinged deployment via SRV URI.")
    except Exception as e:
        print(f"FAILED: {e}")
        raise
    finally:
        if client:
            client.close()


def test_standard():
    """Test connection using the older standard URI with explicit shard hosts (pytest + direct run)."""
    print("\n--- Testing standard connection (older driver format) ---")
    print(f"Shards: {config['shards']}")
    print(f"Port:   {config['port']}")
    client = None
    try:
        client = MongoClient(uri_standard)
        client.admin.command("ping")
        print("SUCCESS: Pinged deployment via standard URI.")
    except Exception as e:
        print(f"FAILED: {e}")
        raise
    finally:
        if client:
            client.close()


if __name__ == "__main__":
    test_srv()
    test_standard()
