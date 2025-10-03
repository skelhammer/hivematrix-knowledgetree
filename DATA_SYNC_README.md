# HiveMatrix KnowledgeTree - Data Sync Architecture

## Overview

**KnowledgeTree is a knowledge management service that pulls all data from Codex via API.**

KnowledgeTree does NOT sync directly from external services (Freshservice, Datto RMM). All data comes from the Codex service.

## Architecture

```
Codex (Central Data Hub)
    ↓
KnowledgeTree (Knowledge Management)
    - Syncs companies, contacts, assets from Codex
    - Syncs tickets from Codex
    - Stores data in Neo4j graph database
    - Provides context for AI assistance
```

## Data Flow

1. **Codex** syncs from external sources (Freshservice, Datto)
2. **KnowledgeTree** pulls from Codex API endpoints
3. **Neo4j** stores structured knowledge graph
4. **Users** access knowledge through KnowledgeTree UI

## Sync Scripts

### Active Scripts

✅ **`sync_codex.py`** - Syncs companies, contacts, and assets
- Pulls from Codex `/api/companies` endpoints
- Creates knowledge tree structure:
  ```
  /Companies/
    /{Company Name}/
      /Users/
        /{User Name}/
          Contact.md
      /Assets/
        {hostname}.md
  ```
- **Runtime:** ~2-5 minutes depending on data size

✅ **`sync_tickets.py`** - Syncs support tickets
- Pulls from Codex `/api/companies/{account}/tickets`
- Creates ticket files under each company
- **Runtime:** ~5-15 minutes depending on ticket count

### Deprecated Scripts

❌ **`sync_tickets.py.deprecated`** - Old version that accessed Freshservice directly
- DO NOT USE - replaced with Codex-based version

## How to Sync Data

### Prerequisites

1. **Codex must be running** and have data synced
2. **Neo4j database** must be running
3. **KnowledgeTree config** must be set up

### Running Syncs

```bash
cd /path/to/hivematrix-knowledgetree
source pyenv/bin/activate

# Sync companies, contacts, and assets from Codex
python sync_codex.py

# Sync tickets from Codex
python sync_tickets.py
```

### Recommended Sync Order

1. First, ensure **Codex has fresh data**:
   - Log into Codex admin dashboard
   - Run Freshservice, Datto, and Ticket syncs

2. Then sync **KnowledgeTree**:
   ```bash
   python sync_codex.py      # Companies, contacts, assets
   python sync_tickets.py    # Tickets
   ```

## Configuration

### Required Config File: `instance/knowledgetree.conf`

```ini
[database]
neo4j_uri = bolt://localhost:7687
neo4j_user = neo4j
neo4j_password = your_neo4j_password
```

### Environment Variables: `.flaskenv`

```bash
FLASK_APP=run.py
FLASK_ENV=development
CORE_SERVICE_URL='http://localhost:5000'
SERVICE_NAME='knowledgetree'
```

### Service Configuration: `services.json`

```json
{
  "codex": {
    "url": "http://localhost:5001",
    "api_key": "your_api_key_here"
  }
}
```

## What Gets Synced

### From Codex Companies API
- Company name and account number
- Company metadata (description, billing plan, etc.)

### From Codex Contacts API
- Contact name, email, title
- Phone numbers (mobile, work)
- Employment status (active/inactive)
- Association with companies

### From Codex Assets API
- Hostname and device information
- Operating system and hardware type
- IP addresses (internal, external)
- Online status and last seen
- Domain and last logged in user

### From Codex Tickets API
- Ticket ID and subject
- Status and timestamps
- Hours spent
- Association with company

## Knowledge Tree Structure

KnowledgeTree creates a hierarchical structure in Neo4j:

```
/root
  /Companies
    /Acme Corporation
      /Users
        /John Doe
          Contact.md
          /Tickets (attached folder)
        /Jane Smith
          Contact.md
          /Tickets (attached folder)
      /Assets
        DESKTOP-001.md
        SERVER-001.md
      /Tickets
        Ticket_12345.md
        Ticket_12346.md
    /Another Company
      ...
```

## Benefits of Codex-Based Sync

✅ **Single source of truth** - All data originates from Codex
✅ **No duplicate API calls** - Codex handles rate limits and caching
✅ **Consistent data** - Same data across all HiveMatrix services
✅ **Simpler configuration** - Only need Codex URL, not Freshservice/Datto credentials
✅ **Better performance** - Codex optimizes bulk data fetching

## Troubleshooting

### Sync fails with "Cannot connect to Codex"

1. Verify Codex service is running: `http://localhost:5001`
2. Check `services.json` has correct Codex URL
3. Verify API key is correct
4. Check network connectivity

### No companies appear in KnowledgeTree

1. Check Codex has companies: Visit Codex dashboard
2. Verify Codex API endpoint works: `curl http://localhost:5001/codex/api/companies`
3. Run `sync_codex.py` again with debug output
4. Check Neo4j is running and accessible

### Tickets not syncing

1. Verify Codex has ticket data (run ticket sync in Codex first)
2. Check Codex tickets API: `/api/companies/{account}/tickets`
3. Ensure `sync_codex.py` ran successfully first (creates company structure)
4. Check Neo4j logs for any errors

### Old ticket data (from Freshservice direct sync)

The old `sync_tickets.py.deprecated` is no longer used. To clean up:

1. Delete old ticket nodes from Neo4j if needed
2. Run new `sync_tickets.py` to repopulate from Codex
3. Old tickets will not interfere with new ones

## Sync Schedule Recommendations

Since KnowledgeTree pulls from Codex, sync frequency depends on how often Codex updates:

### If Codex syncs daily:
- Run KnowledgeTree syncs daily, after Codex completes

### If Codex syncs hourly:
- Run KnowledgeTree syncs every few hours

### Setup Cron Job Example

```bash
# Sync KnowledgeTree every 6 hours (assuming Codex syncs more frequently)
0 */6 * * * cd /path/to/knowledgetree && source pyenv/bin/activate && python sync_codex.py && python sync_tickets.py
```

## Migration Notes

### Migrating from direct Freshservice access:

1. **Ensure Codex is syncing properly** - Verify data in Codex first
2. **Stop using old sync scripts** - `sync_tickets.py.deprecated`
3. **Clear old data if needed** - Optional, depends on your needs
4. **Run new syncs** - `sync_codex.py` then `sync_tickets.py`
5. **Update automation** - Change any scheduled jobs to use new scripts

### Data Cleanup (if needed)

If you have old data from direct Freshservice syncs and want a clean slate:

```cypher
// Connect to Neo4j and run:
MATCH (n:ContextItem)
WHERE n.id STARTS WITH 'ticket_'
DETACH DELETE n;
```

Then re-run the new sync scripts.

## Development

### Testing Codex connectivity

```bash
python -c "from app.service_client import call_service; from app import app; app.app_context().push(); print(call_service('codex', '/api/companies').json())"
```

### Debugging sync issues

Add debug output to scripts:
```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## Support

For issues or questions:
1. Verify Codex is running and has data
2. Check `services.json` configuration
3. Review Neo4j logs for database errors
4. Test Codex API endpoints manually with curl
