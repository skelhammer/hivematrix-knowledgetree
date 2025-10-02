# HiveMatrix KnowledgeTree - Project Structure

## Complete Directory Layout

```
hivematrix-knowledgetree/
├── app/
│   ├── __init__.py           # Flask app initialization with Neo4j
│   ├── auth.py               # @token_required, @admin_required decorators
│   ├── middleware.py         # URL prefix middleware for Nexus proxy
│   ├── routes.py             # All routes (browse, view, API endpoints)
│   ├── service_client.py     # Service-to-service communication helper
│   └── templates/
│       ├── index.html        # File browser interface (BEM styled)
│       ├── view.html         # Article view/edit page (BEM styled)
│       └── redirect.html     # Simple redirect template
├── instance/                 # Created by init_db.py
│   ├── knowledgetree.conf    # Database and API credentials (not in git)
│   └── uploads/              # Uploaded files storage
├── .flaskenv                 # Flask environment configuration (not in git)
├── .gitignore               # Git ignore patterns
├── init_db.py               # Interactive database setup script
├── sync_codex.py            # Sync companies/users/assets from Codex
├── sync_tickets.py          # Sync support tickets from Freshservice
├── requirements.txt         # Python dependencies
├── run.py                   # Production entry point (Waitress)
├── services.json            # Service discovery configuration
├── README.md                # Comprehensive documentation
├── PROJECT_STRUCTURE.md     # This file
└── LICENSE                  # MIT License

```

## File Purposes

### Core Application Files

**app/__init__.py**
- Initializes Flask application
- Loads configuration from environment variables
- Connects to Neo4j database
- Ensures root node and schema exist
- Applies URL prefix middleware for Nexus integration
- Imports routes

**app/auth.py**
- `@token_required` decorator for JWT verification
- `@admin_required` decorator for admin-only routes
- Handles both user tokens and service tokens
- Fetches Core's public key via JWKS

**app/middleware.py**
- `PrefixMiddleware` class for URL path handling
- Allows Flask to work behind Nexus proxy
- Adjusts SCRIPT_NAME and PATH_INFO in WSGI environment

**app/service_client.py**
- `call_service()` function for service-to-service calls
- Automatically requests service token from Core
- Adds Authorization header
- Returns response object

**app/routes.py**
- `/` - Redirect to browse
- `/browse/` - Browse root folder
- `/browse/<path>` - Browse specific path
- `/view/<node_id>` - View/edit article
- `/uploads/<filename>` - Serve uploaded files
- `/api/search` - Search articles
- `/api/node` - CRUD operations on nodes
- `/api/upload/<node_id>` - Upload files
- `/api/context/tree/<node_id>` - Get attached folders
- `/api/context/<node_id>` - Export full context
- `/admin/wipe` - Wipe database (admin only)

### Templates

**app/templates/index.html**
- File browser interface
- Breadcrumb navigation
- Search functionality
- Context menu (right-click)
- Uses BEM classes (no inline styles)

**app/templates/view.html**
- Article content display
- Toast UI Editor for editing
- File attachment management
- Context export modal
- Uses BEM classes (no inline styles)

**app/templates/redirect.html**
- Simple meta refresh redirect
- Used by index route

### Configuration Files

**.flaskenv** (not in git)
```
FLASK_APP=run.py
FLASK_ENV=development
CORE_SERVICE_URL='http://localhost:5000'
SERVICE_NAME='knowledgetree'
```

**instance/knowledgetree.conf** (not in git, created by init_db.py)
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

**services.json**
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

### Sync Scripts

**init_db.py**
- Interactive database setup
- Prompts for Neo4j credentials
- Prompts for Codex URL
- Prompts for optional Freshservice credentials
- Tests connections
- Saves configuration to instance/knowledgetree.conf

**sync_codex.py**
- Calls Codex service APIs to get companies, users, assets
- Creates folder structure in Neo4j:
  - /Companies/{Company Name}/Users/{User Name}/Contact.md
  - /Companies/{Company Name}/Users/{User Name}/Tickets/ (attached)
  - /Companies/{Company Name}/Assets/{hostname}.md
- Marks all synced data as read_only
- Uses consistent IDs for idempotent syncing

**sync_tickets.py**
- Fetches tickets from Freshservice API
- Finds user by email in KnowledgeTree
- Creates ticket markdown files under user's /Tickets/ folder
- Includes ticket details, description, and conversations
- Supports incremental sync (default) or full overwrite
- Run with `python sync_tickets.py overwrite` for full refresh

### Entry Points

**run.py**
- Production entry point
- Uses Waitress WSGI server
- Binds to 0.0.0.0:5020

## Data Flow

### Authentication Flow
1. User requests protected resource via Nexus
2. Nexus checks session, redirects to Core for login if needed
3. Core authenticates with Keycloak
4. Core mints HiveMatrix JWT with user info and permission level
5. Nexus stores JWT in session
6. Nexus proxies request to KnowledgeTree with Authorization header
7. KnowledgeTree validates JWT using Core's public key
8. KnowledgeTree processes request

### Service-to-Service Flow (Codex Sync)
1. sync_codex.py calls `call_service('codex', '/api/companies')`
2. service_client requests service token from Core
3. Core mints short-lived service token
4. service_client makes request to Codex with service token
5. Codex validates service token
6. Codex returns company data
7. sync_codex.py creates/updates nodes in Neo4j

### Context Export Flow
1. User clicks "Export Context" on article
2. Frontend calls `/api/context/tree/<node_id>` to get attached folders
3. User selects which attached folders to include
4. Frontend calls `/api/context/<node_id>` with exclusion list
5. Backend queries Neo4j for:
   - All ancestor nodes and their child articles
   - All sibling articles at each level
   - Content from non-excluded attached folders
6. Backend assembles markdown with hierarchical headers
7. Backend returns context as JSON
8. Frontend auto-copies to clipboard

## Neo4j Schema

### Node Types

**ContextItem** (Knowledge articles and folders)
- Properties:
  - `id` (string, unique): Generated ID or UUID
  - `name` (string): Display name
  - `content` (string): Markdown content (for articles)
  - `is_folder` (boolean): True for folders
  - `is_attached` (boolean): True for attached folders
  - `read_only` (boolean): True for synced data

**File** (Attached files)
- Properties:
  - `id` (string, unique): UUID
  - `filename` (string): Original filename

### Relationships

**PARENT_OF**: Hierarchical tree structure
- From: ContextItem (folder)
- To: ContextItem (folder or article)

**HAS_FILE**: File attachments
- From: ContextItem (article)
- To: File

## API Endpoints Summary

### User Endpoints (require user JWT)

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Redirect to browse root |
| GET | `/browse/` | Browse root folder |
| GET | `/browse/<path>` | Browse specific path |
| GET | `/view/<node_id>` | View article |
| GET | `/uploads/<filename>` | Download file |
| GET | `/api/search` | Search articles |
| POST | `/api/node` | Create node |
| GET | `/api/node/<node_id>` | Get node details |
| PUT | `/api/node/<node_id>` | Update node |
| DELETE | `/api/node/<node_id>` | Delete node |
| POST | `/api/upload/<node_id>` | Upload file |
| GET | `/api/context/tree/<node_id>` | Get attached folders |
| POST | `/api/context/<node_id>` | Export context |

### Admin Endpoints (require admin JWT)

| Method | Path | Description |
|--------|------|-------------|
| POST | `/admin/wipe` | Wipe database |

## Integration Points

### With Core (Port 5000)
- JWT verification via JWKS endpoint
- Service token minting
- User authentication

### With Nexus (Port 8000)
- Receives proxied requests with user JWT
- Gets CSS injection via Nexus
- URL prefix handling via middleware

### With Codex (Port 5010)
- `/api/companies` - Get all companies
- `/api/companies/<account_number>/users` - Get company users
- `/api/companies/<account_number>/assets` - Get company assets

### With Freshservice (External)
- `/api/v2/tickets` - List tickets
- `/api/v2/tickets/<id>` - Get ticket details
- `/api/v2/tickets/<id>/conversations` - Get ticket conversations
- `/api/v2/requesters/<id>` - Get requester details

## Development Workflow

### Initial Setup
```bash
# 1. Create virtual environment
python3 -m venv pyenv
source pyenv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .flaskenv.example .flaskenv  # Edit as needed

# 4. Initialize database
python init_db.py

# 5. Sync data from Codex
python sync_codex.py

# 6. (Optional) Sync tickets
python sync_tickets.py

# 7. Run development server
flask run --port=5020
```

### Adding New Features

1. **New Routes**: Add to `app/routes.py`
2. **New Templates**: Add to `app/templates/` (use BEM classes only)
3. **New APIs**: Follow `@token_required` pattern
4. **Service Calls**: Use `call_service()` from service_client.py

### Testing Service-to-Service Calls

```python
# In sync_codex.py or any script
from app.service_client import call_service

with app.app_context():
    response = call_service('codex', '/api/companies')
    companies = response.json()
    print(f"Found {len(companies)} companies")
```

### Debugging Neo4j

```bash
# Connect to Neo4j shell
cypher-shell -u neo4j -p your_password

# View all nodes
MATCH (n:ContextItem) RETURN n.name, n.id LIMIT 10;

# View tree structure
MATCH path = (root:ContextItem {id: 'root'})-[:PARENT_OF*..5]->(child)
RETURN [n IN nodes(path) | n.name] AS path;

# Find read-only nodes
MATCH (n:ContextItem {read_only: true})
RETURN n.name, n.id;

# Delete everything (careful!)
MATCH (n) DETACH DELETE n;
```

## Deployment Checklist

- [ ] Neo4j installed and running
- [ ] Database credentials configured
- [ ] Core service accessible at configured URL
- [ ] Codex service accessible at configured URL
- [ ] Initial sync completed (`python sync_codex.py`)
- [ ] Nexus configured with knowledgetree service entry
- [ ] Production server running (`python run.py`)
- [ ] (Optional) Cron jobs configured for automated syncing
- [ ] (Optional) Caddy/nginx configured for HTTPS

## Common Issues

**"Neo4j connection failed"**
- Check Neo4j is running: `sudo systemctl status neo4j`
- Verify credentials in instance/knowledgetree.conf
- Test with: `cypher-shell -u neo4j -p your_password`

**"Service token request failed"**
- Ensure Core is running on configured URL
- Check Core's `/service-token` endpoint
- Verify services.json has correct URLs

**"User not found in KnowledgeTree"**
- Run `python sync_codex.py` to sync users from Codex
- Check that user exists in Codex first

**"Context export is empty"**
- Ensure articles have content
- Check attached folders are properly linked
- Verify read_only flag isn't preventing content display

## Architecture Compliance

✅ **Follows HiveMatrix patterns:**
- Uses Core for authentication
- Works behind Nexus proxy
- URL prefix middleware implemented
- Service-to-service via Core tokens
- BEM classes only (no CSS)
- Token decorators for all protected routes
- Separate database (Neo4j)
- RESTful JSON APIs

✅ **Security:**
- No direct credential handling
- JWT verification on all protected routes
- Service tokens for inter-service calls
- Read-only protection for synced data

✅ **Maintainability:**
- Small, focused service
- Explicit configuration
- Simple, predictable patterns
- Comprehensive documentation
