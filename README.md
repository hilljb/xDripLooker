# xDripLooker
Visualizing xDrip+ Data in Looker

## Main Idea
As a type-1 diabetic, I want a site where others (my wife, my doctors, etc.) can view my glucose levels over time. It would also be nice to have my values over time stored in a database where I can analyze the data myself.

I use xDrip+ on my phone to hijack my Dexcom glucometer's Bluetooth signal. The open-source app is just better, IMO, than the Dexcom software. I also have customized a watchface that works well with this setup.

This repo may end up being just documentation.

Just getting this working and then will improve whatever needs improving. While I'd rather use InfluxDB, it would currently be more challenging to run and also to get connected to Looker. I wish there were a PostgreSQL option in xDrip, but there isn't. So, we'll use MongoDB because there are easy (and free) instances, and connecting to Looker is easy.

## Project Structure

```
xDripLooker/
├── environment.yml           # Conda environment definition (preferred install method)
├── requirements.txt          # Pip fallback for core dependencies
├── requirements-notebook.txt # Pip fallback for notebook extras
├── pyproject.toml            # Project metadata and pytest configuration
├── test/
│   ├── config.json.example   # Template — copy this to config.json and fill in your values
│   ├── config.json           # Your local credentials (gitignored, never committed)
│   └── test_connection.py    # Connection tests for both SRV and standard URI formats
└── README.md
```

## Set Up MongoDB

- Visit [cloud.mongodb.com](http://cloud.mongodb.com), set up an account or log in to an existing account.
- My "organization" and "project" seems to have been set up automatically with generic names: `Jason's Org - 2026-03-09` and `Project 0`. You may need to set these up yourself.
- Go into your organization and project, click on "Clusters" in the side menu. Click on "Build a Cluster."
- I'm going to try using the free level cluster. As of writing this, it has a 512 MiB storage limit with shared vCPU and RAM. My cluster is named `Cluster0`. I'm going to preload the sample dataset for testing. I'm running on GCP with the region set to Iowa (us-central1). (The location is important because we will want to use the same region later for Looker so we save on costs.)
- After saving the configuration, I was asked to create a database user and password. I placed those into my password manager and created the user.
- Choose a connection method. I am using the MongoDB drivers. I will allow xDrip+ to use its existing drivers, but will use Python for testing.

### Connection string limitations in xDrip+

xDrip+ bundles `mongo-java-driver-3.4.0` (circa 2016). This old driver has two hard
limitations that prevent it from using standard Atlas connection strings:

| String format | What happens in xDrip+ |
|---|---|
| `mongodb+srv://…` | Driver rejects it: *"Connection strings must start with 'mongodb://'"* |
| `mongodb://host1,host2,host3/…` | Java's `URI.getHost()` returns `null` for multi-host authority strings → `NullPointerException` in `NightscoutUploader.java` |

**The fix:** use a *single-shard* `mongodb://` string. Run:

```bash
python get_connection_string.py
```

Copy the **"Single-shard (xDrip+ compatible)"** string from the output.

In xDrip+ go to **Settings → Cloud Upload → MongoDB** and enter:
- **URI**: the single-shard connection string (contains only one host, uses `ssl=true`)
- **Collection**: `entries`
- **Device status collection**: `devicestatus`

### Network access

During Atlas cluster setup, only your current IP address is added to the allow-list.
Since your phone's IP changes constantly, you must allow access from anywhere:

1. In Atlas go to **Security → Network Access**.
2. Click **Edit** on your existing entry → **Allow Access from Anywhere** → **Confirm**.

This sets the CIDR to `0.0.0.0/0`.

## Setting Up Your Environment

All packages are available on conda-forge. Conda is the **preferred** install method
because it handles platform-specific binary wheels (e.g. for pymongo's C-extensions)
more reliably across macOS, Linux, and Windows.

### Create the conda environment

```bash
conda env create -f environment.yml
conda activate xdrip
```

This creates an environment named `xdrip` with Python 3.12 and all required packages
installed from `conda-forge`.

### Updating the environment after changes to environment.yml

```bash
conda env update -f environment.yml --prune
```

### Pip fallback (if conda is unavailable)

```bash
pip install -r requirements.txt          # core dependencies
pip install -r requirements-notebook.txt # optional: Jupyter notebook support
```

## Configuration File

Connection credentials are stored in `test/config.json`, which is **gitignored and
never committed**. This keeps secrets out of the public repository.

### Setup

Copy the example file and fill in your values:

```bash
cp test/config.json.example test/config.json
```

Then edit `test/config.json`:

```json
{
  "mongo": {
    "username": "your_mongo_username",
    "password": "your_mongo_password",
    "host": "yourcluster.mongodb.net",
    "app_name": "Cluster0",
    "shards": [
      "yourcluster-shard-00-00.mongodb.net",
      "yourcluster-shard-00-01.mongodb.net",
      "yourcluster-shard-00-02.mongodb.net"
    ],
    "port": 27017,
    "auth_source": "admin"
  }
}
```

### Field reference

| Field         | Description |
|---------------|-------------|
| `username`    | The database user created in MongoDB Atlas. |
| `password`    | The database user's password. Store this in a password manager. |
| `host`        | The SRV hostname shown in Atlas under "Connect → Drivers". Looks like `clustername.xxxxxx.mongodb.net`. |
| `app_name`    | The Atlas cluster/app name (usually `Cluster0`). |
| `shards`      | The three individual shard hostnames for the older standard connection string. Found in Atlas under "Connect → Drivers" when you choose the non-SRV format, or visible in any SSL connection error output. Pattern: `clustername-shard-00-0N.xxxxxx.mongodb.net`. |
| `port`        | MongoDB port — always `27017` for Atlas. |
| `auth_source` | Authentication database — always `admin` for Atlas. |

### Where to find shard hostnames

In MongoDB Atlas, go to **Clusters → Connect → Drivers** and select a driver/version
that does *not* show the `mongodb+srv://` prefix. The resulting connection string will
list all three shard hosts explicitly. Alternatively, the shard hostnames appear in
the error output if you attempt a standard connection without specifying them correctly.

## Running Tests

```bash
# Via pytest (recommended)
pytest test/ -v

# Or run the script directly
python test/test_connection.py
```

Tests exercise both connection URI formats:
- **SRV** (`mongodb+srv://`) — used by modern drivers
- **Standard** (`mongodb://`) — used by older drivers, such as some mobile SDKs (e.g. xDrip+)
