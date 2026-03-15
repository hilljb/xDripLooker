import json
import os
from pymongo.mongo_client import MongoClient
from pymongo.server_api import ServerApi

# Load connection config from local config file (not committed to version control)
config_path = os.path.join(os.path.dirname(__file__), "config.json")
with open(config_path) as f:
    config = json.load(f)["mongo"]

uri = (
    f"mongodb+srv://{config['username']}:{config['password']}"
    f"@{config['host']}/?appName={config['app_name']}"
)

# Create a new client and connect to the server
client = MongoClient(uri, server_api=ServerApi('1'))
# Send a ping to confirm a successful connection
try:
    client.admin.command('ping')
    print("Pinged your deployment. You successfully connected to MongoDB!")
except Exception as e:
    print(e)
