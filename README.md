# HiveMatrix KnowledgeTree

Knowledge management and relationship mapping system using Neo4j graph database.

## Overview

KnowledgeTree provides a hierarchical knowledge base that syncs data from Codex (companies, contacts, tickets) and allows browsing and managing relationships in a graph database.

## Requirements

- Python 3.8+
- Neo4j database (Community or Enterprise)
- HiveMatrix Core (for authentication)
- HiveMatrix Codex (optional, for data sync)

## Installation

### 1. Install via Helm Dashboard

The easiest way to install KnowledgeTree is through the Helm web interface:

1. Go to http://localhost:5004 (Helm Dashboard)
2. Navigate to the Modules/Apps section
3. Click "Install" next to KnowledgeTree
4. Wait for basic installation to complete
5. Follow the manual configuration steps below

### 2. Manual Installation

If you cloned the repo manually:

```bash
cd hivematrix-knowledgetree
./install.sh
```

This installs Python dependencies only. You still need to complete the manual configuration below.

## Manual Configuration Required

### Step 1: Install Neo4j

If Neo4j is not already installed:

**Ubuntu/Debian:**
```bash
wget -O - https://debian.neo4j.com/neotechnology.gpg.key | sudo apt-key add -
echo 'deb https://debian.neo4j.com stable latest' | sudo tee /etc/apt/sources.list.d/neo4j.list
sudo apt-get update
sudo apt-get install -y neo4j
```

**Or use Docker:**
```bash
docker run -d \
  -p 7474:7474 -p 7687:7687 \
  -e NEO4J_AUTH=neo4j/your_password \
  --name neo4j \
  neo4j:latest
```

### Step 2: Configure Neo4j Password

**For fresh Neo4j installation:**
```bash
# Stop Neo4j if running
sudo systemctl stop neo4j

# Set initial password
sudo neo4j-admin dbms set-initial-password "your_secure_password"

# Start Neo4j
sudo systemctl start neo4j
sudo systemctl enable neo4j
```

**For existing Neo4j installation:**

You need to either:
- Use the existing password
- Or reset via Neo4j browser at http://localhost:7474
- Or stop Neo4j, delete data, and set new password:
  ```bash
  sudo systemctl stop neo4j
  sudo rm -rf /var/lib/neo4j/data/databases/*
  sudo rm -rf /var/lib/neo4j/data/transactions/*
  sudo neo4j-admin dbms set-initial-password "your_secure_password"
  sudo systemctl start neo4j
  ```

### Step 3: Run init_db.py

Configure KnowledgeTree with your Neo4j credentials:

```bash
cd hivematrix-knowledgetree
source pyenv/bin/activate
python init_db.py
```

This will prompt you for:
- Neo4j URI (default: bolt://localhost:7687)
- Neo4j username (default: neo4j)
- Neo4j password
- Codex service URL (default: http://localhost:5010)

**What init_db.py does:**
1. Saves configuration to `instance/knowledgetree.conf`
2. **Automatically updates Helm's `master_config.json`** with your Neo4j password
3. **Automatically regenerates `.flaskenv`** with the correct credentials

This keeps all passwords in sync across Helm and KnowledgeTree.

### Step 4: Start KnowledgeTree

That's it! Configuration is complete. Now start the service.

## Starting KnowledgeTree

### Via Helm Dashboard (Recommended)

1. Go to http://localhost:5004
2. Click "Start" next to KnowledgeTree
3. Check status - should show "running" and "healthy"

### Manually

```bash
cd hivematrix-knowledgetree
source pyenv/bin/activate
python run.py
```

## Accessing KnowledgeTree

**Through Nexus (Recommended):**
- URL: https://your-server/knowledgetree
- Requires login via Keycloak

**Direct Access (for testing):**
- URL: http://localhost:5020
- Requires valid JWT token in Authorization header

## Syncing Data from Codex

KnowledgeTree pulls data from Codex. To sync:

```bash
# Sync company structure
python sync_codex.py

# Sync tickets
python sync_tickets.py
```

Add to cron for automated syncing.

## Troubleshooting

### "CORE_SERVICE_URL must be set" Error

The `.flaskenv` file is missing or incomplete. Generate it:
```bash
cd ../hivematrix-helm
python config_manager.py write-dotenv knowledgetree
```

### "Could not connect to Neo4j" Error

1. Check Neo4j is running: `sudo systemctl status neo4j`
2. Check password is correct in `instance/knowledgetree.conf`
3. Test connection: `cypher-shell -u neo4j -p your_password "RETURN 1;"`

### "NoneType object has no attribute 'session'" Error

Neo4j driver failed to initialize. This means:
- Neo4j authentication failed
- Neo4j is not running
- Wrong credentials in config

Fix:
1. Verify Neo4j is running
2. Run `python init_db.py` to reconfigure with correct password
3. Restart KnowledgeTree
