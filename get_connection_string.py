"""
Print MongoDB connection strings for the xDripLooker database.

Credentials are read from test/config.json (gitignored, never committed).

Two formats are printed:

  1. MULTI-HOST (standard Atlas format) — works with modern drivers and Python/pymongo,
     but BREAKS xDrip+ because Java's java.net.URI cannot parse comma-separated hosts,
     causing a NullPointerException in NightscoutUploader.java.

  2. SINGLE-SHARD (xDrip+ compatible) — connects to just the first shard replica.
     xDrip+ bundles mongo-java-driver-3.4.0, which requires a single-host mongodb://
     URI. Use this string in xDrip+ Settings → Cloud Upload → MongoDB.

Usage:
  python get_connection_string.py
"""

import json
import os

config_path = os.path.join(os.path.dirname(__file__), "test", "config.json")
with open(config_path) as f:
    config = json.load(f)["mongo"]

DATABASE = "xDripLooker"
port = config["port"]
user = config["username"]
password = config["password"]
auth_source = config["auth_source"]

# --- Format 1: multi-host (Atlas standard, NOT compatible with xDrip+) ---
shards_str = ",".join(f"{s}:{port}" for s in config["shards"])
multi_host = (
    f"mongodb://{user}:{password}"
    f"@{shards_str}"
    f"/{DATABASE}"
    f"?authSource={auth_source}"
    f"&tls=true"
    f"&retryWrites=true"
    f"&w=majority"
)

# --- Format 2: single-shard (xDrip+ compatible) ---
# Connects to the first shard only. Java's URI parser handles single-host URIs
# correctly; multi-host URIs return null from getHost(), crashing xDrip+.
# Uses ssl=true (the parameter name recognised by mongo-java-driver 3.4).
first_shard = config["shards"][0]
single_shard = (
    f"mongodb://{user}:{password}"
    f"@{first_shard}:{port}"
    f"/{DATABASE}"
    f"?authSource={auth_source}"
    f"&ssl=true"
)

print("=== Multi-host (Python / modern drivers — NOT for xDrip+) ===")
print(multi_host)
print()
print("=== Single-shard (xDrip+ compatible) ===")
print(single_shard)
