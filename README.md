# HiveMatrix KnowledgeTree

**A Context-Aware Knowledge Graph for the HiveMatrix PSA Ecosystem**

KnowledgeTree is a HiveMatrix service for building hierarchical knowledge bases with full contextual awareness. It automatically syncs company structure from Codex and can pull ticket data from Freshservice, creating a unified knowledge repository.

## Overview

KnowledgeTree is a standalone HiveMatrix module that:
- Maintains a Neo4j graph database of hierarchical knowledge
- Syncs company/user/asset structure from Codex service
- Optionally syncs support tickets from Freshservice
- Provides "context export" - complete contextual snapshots for AI tools
- Offers a file-manager style interface for organizing knowledge
- Supports attached folders for cross-referencing information

**Port:** 5020 (standard)

## Architecture

KnowledgeTree follows the HiveMatrix monolithic service pattern:
- **Authentication:** Uses Core service for JWT-based authentication
- **Database:** Neo4j graph database (owns all knowledge nodes)
- **Styling:** Unstyled HTML using BEM classes, styled by Nexus proxy
- **Integration:** Pulls data from Codex via service-to-service calls

## Key Features

### Context Engine
The core feature is the ability to generate a complete contextual snapshot for any article:
- **Full Ancestry**: Content from every article in the direct path from root to current location
- **Complete Sibling Data**: Content of all articles at the same level
- **Attached Folder Content**: Information from linked folders seamlessly included
- **File Attachments**: List of files attached to the article

### Automated Data Sync
- **Codex Integration**: Automatically pulls companies, users, and assets from Codex
- **Freshservice Tickets**: Optional ticket sync to keep support history up-to-date
- **Read-Only Protection**: Synced data is marked read-only to prevent accidental changes

### Intuitive Interface
- Classic file-browser navigation (single-click select, double-click open)
- Right-click context menu for all operations
- Full-text search across the knowledge tree
- Attached folders (📎) for linking related context

## Setup and Installation

### 1. Prerequisites

- Python 3.8+
- Neo4j 5.x
- HiveMatrix Core service running on port 5000
- HiveMatrix Codex service running on port 5010 (for company sync)
- (Optional) Freshservice account for ticket syncing

### 2. Install Neo4j

**On Ubuntu:**
```bash
# Add Neo4j repository
wget -O - https://debian.neo4j.com/neotechnology.gpg.key | sudo apt-key add -
echo 'deb https://debian.neo4j.com stable 5' | sudo tee /etc/apt/sources.list.d/neo4j.list

# Install Neo4j and Java
sudo apt-get update
sudo apt-get install neo4j openjdk-17-jdk -y

# Configure Java
export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
echo 'export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64' >> ~/.bashrc

# Start Neo4j
sudo systemctl start neo4j
sudo systemctl enable neo4j

# Set initial password
cypher-shell -u neo4j -p neo4j
# Follow prompts to set new password
```

### 3. Create Virtual Environment

```bash
python3 -m venv pyenv
source pyenv/bin/activate  # On Windows: .\pyenv\Scripts\activate
```

### 4. Install Dependencies

```bash
pip install -r requirements.txt
```

### 5. Configure Environment

Create `.flaskenv`:
```bash
FLASK_APP=run.py
FLASK_ENV=development
CORE_SERVICE_URL='http://localhost:5000'
SERVICE_NAME='knowledgetree'
```

### 6. Initialize Database

Run the interactive setup:
```bash
python init_db.py
```

This will prompt for:
- Neo4j connection details (URI, user, password)
- Codex service URL
- (Optional) Freshservice API credentials

### 7. Sync Company Structure

Pull companies, users, and assets from Codex:
```bash
python sync_codex.py
```

This creates:
```
/Companies/
  /{Company Name}/
    /Users/
      /{User Name}/
        Contact.md
        /Tickets/ (attached folder)
    /Assets/
      {hostname}.md
```

### 8. (Optional) Sync Tickets

If you configured Freshservice, sync tickets:
```bash
python sync_tickets.py
```

Run with `overwrite` flag to refresh all tickets:
```bash
python sync_tickets.py overwrite
```

### 9. Run the Service

**Development mode:**
```bash
flask run --port=5020
```

**Production mode (with Waitress):**
```bash
python run.py
```

The service will be available at `http://localhost:5020`.

**Access via Nexus:** `http://localhost:8000/knowledgetree/`

## Usage

### Creating Knowledge

1. **Right-click** in any folder to create:
   - New Folder (regular organization)
   - New Attached Folder (📎 linked context)
   - New Article (knowledge document)

2. **Double-click** folders to navigate, articles to edit

3. **Edit articles** with the WYSIWYG editor or Markdown

### Exporting Context

1. Navigate to any article
2. Click **"Export Context"** button
3. Select which attached folders to include
4. Click **"Generate & Copy Context"**
5. Context is automatically copied to clipboard

The exported context includes:
- All ancestor article content (full path to root)
- All sibling articles at each level
- Content from selected attached folders
- List of attached files

### Attached Folders

Attached folders (📎) create context links:
- They appear in context exports but don't clutter the main tree
- Perfect for linking tickets, assets, or related documentation
- Can be selectively included/excluded when exporting context

### Search

Use the search box to find articles across the entire tree:
- Searches article names and content
- Shows full path to each result
- Click to navigate directly to the item

## Automation

### Cron Jobs

Set up automatic syncing:

```bash
# Edit crontab
crontab -e

# Sync from Codex daily at 2 AM
0 2 * * * cd /path/to/hivematrix-knowledgetree && /path/to/pyenv/bin/python sync_codex.py

# Sync tickets every hour
0 * * * * cd /path/to/hivematrix-knowledgetree && /path/to/pyenv/bin/python sync_tickets.py
```

## API Endpoints

All endpoints require JWT authentication via `Authorization: Bearer <token>` header.

### Browse & View
- `GET /browse/` - Browse root
- `GET /browse/<path>` - Browse specific path
- `GET /view/<node_id>` - View article details

### Node Operations
- `POST /api/node` - Create new node
- `GET /api/node/<node_id>` - Get node details
- `PUT /api/node/<node_id>` - Update node
- `DELETE /api/node/<node_id>` - Delete node

### Context & Search
- `GET /api/search?query=<term>` - Search articles
- `GET /api/context/tree/<node_id>` - Get attached folders
- `POST /api/context/<node_id>` - Get full context (with exclusions)

### Files
- `POST /api/upload/<node_id>` - Upload file to node
- `GET /uploads/<filename>` - Download uploaded file

## Service-to-Service Communication

KnowledgeTree calls Codex APIs to sync data:

```python
from app.service_client import call_service

# Get companies from Codex
response = call_service('codex', '/api/companies')
companies = response.json()
```

The service client automatically:
1. Requests a service token from Core
2. Makes the authenticated request
3. Returns the response

## Data Model

### Neo4j Schema

**Nodes:**
- `ContextItem`: Knowledge articles and folders
  - Properties: `id`, `name`, `content`, `is_folder`, `is_attached`, `read_only`
- `File`: Attached files
  - Properties: `id`, `filename`

**Relationships:**
- `PARENT_OF`: Hierarchical tree structure
- `HAS_FILE`: File attachments

### Read-Only Protection

Synced data from Codex and Freshservice is marked `read_only: true`:
- Prevents accidental editing through the UI
- Can only be updated by re-running sync scripts
- User-created content is `read_only: false`

## Configuration Files

### instance/knowledgetree.conf

```ini
[database]
neo4j_uri = bolt://localhost:7687
neo4j_user = neo4j
neo4j_password = your_password

[codex]
url = http://localhost:5010

[freshservice]
domain = your-domain.freshservice.com
api_key = your_api_key
```

### services.json

```json
{
  "codex": {
    "url": "http://localhost:5010"
  },
  "knowledgetree": {
    "url": "http://localhost:5020"
  }
}
```

## Troubleshooting

**Neo4j connection fails:**
- Verify Neo4j is running: `sudo systemctl status neo4j`
- Check credentials in `instance/knowledgetree.conf`
- Test connection: `cypher-shell -u neo4j -p your_password`

**Codex sync fails:**
- Ensure Codex service is running on port 5010
- Verify `CORE_SERVICE_URL` in `.flaskenv`
- Check that Core's JWKS endpoint is accessible

**Context export is empty:**
- Ensure you've run `sync_codex.py` to populate data
- Check that articles have content
- Verify attached folders are properly linked

**Authentication errors:**
- Ensure Core service is running on port 5000
- Verify JWT token is being passed by Nexus
- Check Core's JWKS endpoint: `curl http://localhost:5000/.well-known/jwks.json`

## Development

### Adding New Features

1. Follow HiveMatrix architecture patterns (see ARCHITECTURE.md)
2. Use `@token_required` for all protected routes
3. Use BEM classes for all HTML (no CSS in this service)
4. Update this README with new functionality

### Database Queries

Access Neo4j directly for debugging:

```bash
cypher-shell -u neo4j -p your_password

# View all nodes
MATCH (n:ContextItem) RETURN n.name, n.id LIMIT 10;

# View tree structure
MATCH path = (root:ContextItem {id: 'root'})-[:PARENT_OF*..5]->(child)
RETURN [n IN nodes(path) | n.name] AS path;

# Find read-only nodes
MATCH (n:ContextItem {read_only: true})
RETURN n.name, n.id;
```

## Production Deployment

### Using Waitress

```bash
python run.py
```

### Using Caddy

Add to Caddyfile:
```
knowledgetree.your-domain.com {
    reverse_proxy 127.0.0.1:5020
}
```

Restart Caddy:
```bash
sudo systemctl restart caddy
```

### Update Nexus

Add KnowledgeTree to Nexus's `services.json`:
```json
{
  "knowledgetree": {
    "url": "http://localhost:5020"
  }
}
```

## Related Modules

- **HiveMatrix Core** (Port 5000): Authentication and identity management
- **HiveMatrix Nexus** (Port 8000): UI composition and routing proxy
- **HiveMatrix Codex** (Port 5010): CRM data source for company structure

## License

MIT License - See LICENSE file for details

## Contributing

When adding features:
1. Follow HiveMatrix architecture patterns
2. Use `@token_required` for all protected routes
3. Use BEM classes for all HTML (no CSS)
4. Test service-to-service communication
5. Update this README

For questions, refer to `ARCHITECTURE.md` in the main HiveMatrix repository.
