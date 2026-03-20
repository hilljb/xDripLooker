"""
Print the MongoDB standard (non-SRV) connection string for the xDripLooker database.

Credentials are read from test/config.json (gitignored, never committed).

Usage:
  python get_connection_string.py
"""

import json
import os

config_path = os.path.join(os.path.dirname(__file__), "test", "config.json")
with open(config_path) as f:
    config = json.load(f)["mongo"]

DATABASE = "xDripLooker"

shards_str = ",".join(f"{s}:{config['port']}" for s in config["shards"])

connection_string = (
    f"mongodb://{config['username']}:{config['password']}"
    f"@{shards_str}"
    f"/{DATABASE}"
    f"?authSource={config['auth_source']}"
    f"&tls=true"
    f"&retryWrites=true"
    f"&w=majority"
)

print(connection_string)
