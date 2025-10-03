#!/usr/bin/env python
"""
Syncs support tickets from Codex into KnowledgeTree.

Creates tickets under each user's /Tickets/ attached folder.
Pulls ticket data from Codex (which syncs from Freshservice).
"""

import os
import sys
import time
import re
import configparser
from neo4j import GraphDatabase, basic_auth
from dotenv import load_dotenv
from markdownify import markdownify as md

load_dotenv('.flaskenv')
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import app
from app.service_client import call_service

def get_config():
    """Loads configuration from knowledgetree.conf."""
    instance_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance')
    config_path = os.path.join(instance_path, 'knowledgetree.conf')

    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found at {config_path}")

    config = configparser.RawConfigParser()
    config.read(config_path)
    return config

def ensure_node(session, parent_id, name, is_folder=True, is_attached=False, content='', read_only=True):
    """Creates or updates a node in Neo4j."""
    node_id = f"{parent_id}_{name.replace(' ', '_').replace('/', '_')}"

    result = session.run("""
        MATCH (parent:ContextItem {id: $parent_id})
        MERGE (parent)-[r:PARENT_OF]->(node:ContextItem {id: $node_id})
        ON CREATE SET node.name = $name,
                      node.is_folder = $is_folder,
                      node.is_attached = $is_attached,
                      node.content = $content,
                      node.read_only = $read_only
        ON MATCH SET  node.name = $name,
                      node.is_folder = $is_folder,
                      node.is_attached = $is_attached,
                      node.content = $content,
                      node.read_only = $read_only
        RETURN node.id as id
    """, parent_id=parent_id, node_id=node_id, name=name, is_folder=is_folder,
         is_attached=is_attached, content=content, read_only=read_only).single()

    return result['id']

def get_user_node_id(session, user_email):
    """Find the KnowledgeTree node ID for a user by email."""
    # Try to find user node by searching for Contact.md that contains the email
    result = session.run("""
        MATCH (contact:ContextItem)
        WHERE contact.name = 'Contact.md'
          AND contact.content CONTAINS $email
        MATCH (user_folder:ContextItem)-[:PARENT_OF]->(contact)
        RETURN user_folder.id as id
    """, email=user_email).single()

    return result['id'] if result else None

def sync_tickets_from_codex(driver):
    """Syncs tickets from Codex for all companies."""
    print("\n--- Syncing Tickets from Codex ---")

    with app.app_context():
        # Get all companies from Codex
        companies_response = call_service('codex', '/api/companies')
        if companies_response.status_code != 200:
            print("ERROR: Failed to fetch companies from Codex")
            return

        companies = companies_response.json()
        print(f"Found {len(companies)} companies")

        total_tickets_synced = 0

        for company in companies:
            account_number = company['account_number']
            company_name = company['name']

            print(f"\n  Processing tickets for: {company_name} ({account_number})")

            # Get tickets for this company from Codex
            tickets_response = call_service('codex', f'/api/companies/{account_number}/tickets')
            if tickets_response.status_code != 200:
                print(f"    → Skipping - no tickets endpoint available")
                continue

            tickets = tickets_response.json()
            print(f"    → Found {len(tickets)} tickets")

            if not tickets:
                continue

            # Get contacts for this company to map ticket requesters
            contacts_response = call_service('codex', f'/api/companies/{account_number}/contacts')
            contacts = contacts_response.json() if contacts_response.status_code == 200 else []

            # Create email to name mapping
            email_to_name = {c['email']: c['name'] for c in contacts if c.get('email')}

            with driver.session() as session:
                for ticket in tickets:
                    ticket_id = ticket.get('ticket_id') or ticket.get('ticket_number')
                    subject = ticket.get('subject', 'No Subject')
                    description = ticket.get('description_text', 'No description')
                    status = ticket.get('status', 'Closed')
                    priority = ticket.get('priority', 'Medium')
                    requester_name = ticket.get('requester_name', 'Unknown')
                    requester_email = ticket.get('requester_email', 'N/A')

                    # Build full conversation history
                    conversations = ticket.get('conversations', [])
                    notes = ticket.get('notes', [])

                    # Create rich ticket content with full context
                    ticket_content = f"""# Ticket #{ticket_id}: {subject}

## Ticket Information
- **Requester:** {requester_name} ({requester_email})
- **Status:** {status}
- **Priority:** {priority}
- **Created:** {ticket.get('created_at', 'N/A')}
- **Last Updated:** {ticket.get('last_updated_at', 'N/A')}
- **Closed:** {ticket.get('closed_at', 'N/A')}
- **Hours Spent:** {ticket.get('total_hours_spent', 0):.2f} hours

## Description
{description}

"""

                    # Add conversation history
                    if conversations:
                        ticket_content += "## Conversation History\n\n"
                        for i, conv in enumerate(conversations, 1):
                            from_email = conv.get('from_email', 'Unknown')
                            created_at = conv.get('created_at', 'N/A')
                            body = conv.get('body', 'No content')
                            direction = "→ Incoming" if conv.get('incoming') else "← Outgoing"

                            ticket_content += f"""### Message {i} - {direction}
**From:** {from_email}
**Date:** {created_at}

{body}

---

"""

                    # Add internal notes
                    if notes:
                        ticket_content += "## Internal Notes\n\n"
                        for i, note in enumerate(notes, 1):
                            from_email = note.get('from_email', 'Unknown')
                            created_at = note.get('created_at', 'N/A')
                            body = note.get('body', 'No content')

                            ticket_content += f"""### Note {i}
**From:** {from_email}
**Date:** {created_at}

{body}

---

"""

                    ticket_content += "\n*Ticket data synced from Codex/Freshservice*\n"

                    # Create ticket in the database
                    # For simplicity, store under Companies/{Company}/Tickets/
                    companies_root_id = f"root_Companies"
                    company_id = f"{companies_root_id}_{company_name.replace(' ', '_')}"
                    tickets_folder_id = f"{company_id}_Tickets"

                    # Ensure Tickets folder exists
                    try:
                        ensure_node(session, company_id, 'Tickets', is_folder=True, is_attached=True)
                    except:
                        # Company folder might not exist yet - skip this ticket
                        continue

                    # Create ticket markdown file
                    ticket_filename = f"Ticket_{ticket_id}.md"
                    ensure_node(
                        session,
                        tickets_folder_id,
                        ticket_filename,
                        is_folder=False,
                        content=ticket_content,
                        read_only=True
                    )

                    total_tickets_synced += 1

                    if total_tickets_synced % 50 == 0:
                        print(f"    → Synced {total_tickets_synced} tickets so far...")

        print(f"\n✓ Synced {total_tickets_synced} total tickets from Codex")

if __name__ == "__main__":
    print("--- KnowledgeTree Ticket Sync (from Codex) ---")

    try:
        config = get_config()

        # Connect to Neo4j
        neo4j_uri = config.get('database', 'neo4j_uri')
        neo4j_user = config.get('database', 'neo4j_user')
        neo4j_password = config.get('database', 'neo4j_password')

        driver = GraphDatabase.driver(neo4j_uri, auth=basic_auth(neo4j_user, neo4j_password))

        # Sync tickets from Codex
        sync_tickets_from_codex(driver)

        driver.close()
        print("\n--- Ticket Sync Successful ---")

    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
