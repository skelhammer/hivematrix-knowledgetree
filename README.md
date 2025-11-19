# HiveMatrix KnowledgeTree

Hierarchical knowledge base for documentation and procedures.

## Overview

KnowledgeTree organizes company knowledge in a filesystem-like structure (sections → categories → topics) with full-text search and Markdown support.

**Port:** 5040

## Features

- **Hierarchical Structure** - Sections, categories, and topics
- **Markdown Support** - Rich text formatting for articles
- **Full-Text Search** - Search across all knowledge articles
- **Graph Database** - Neo4j for relationship tracking
- **Ticket Integration** - Link knowledge to support tickets
- **Version History** - Track changes to articles

## Tech Stack

- Flask + Gunicorn
- Neo4j Graph Database

## Key Endpoints

- `GET /api/sections` - List all sections
- `GET /api/sections/<id>/categories` - List categories in section
- `GET /api/topics/<id>` - Get topic content
- `GET /api/search` - Search knowledge base
- `POST /api/topics` - Create new topic
- `PUT /api/topics/<id>` - Update topic

## Data Structure

```
Section (e.g., "Network")
  └── Category (e.g., "Firewalls")
        └── Topic (e.g., "Configuring VPN")
```

## Environment Variables

- `CORE_SERVICE_URL` - Core service URL
- `NEO4J_URI` - Neo4j connection URI
- `NEO4J_USER` - Neo4j username
- `NEO4J_PASSWORD` - Neo4j password

## Sync Tools

- `sync_tickets.py` - Sync tickets to knowledge folders

## Documentation

For complete installation, configuration, and architecture documentation:

**[HiveMatrix Documentation](https://skelhammer.github.io/hivematrix-docs/)**

## License

MIT License - See LICENSE file
