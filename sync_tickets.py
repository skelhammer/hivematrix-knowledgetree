#!/usr/bin/env python
"""
Syncs support tickets from Freshservice into KnowledgeTree.

Creates tickets under each user's /Tickets/ attached folder.
"""

import os
import sys
import requests
import base64
import time
import re
import configparser
from neo4j import GraphDatabase, basic_auth
from dotenv import load_dotenv
from markdownify import markdownify as md

load_dotenv('.flaskenv')
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import app

# Ticket status and priority mappings
STATUS_MAP = {2: "Open", 3: "Pending", 4: "Resolved", 5: "Closed"}
PRIORITY_MAP = {1: "Low", 2: "Medium", 3: "High", 4: "Urgent"}
STARTING_TICKET_ID = 550  # Adjust as needed

def get_config():
    """Loads configuration from knowledgetree.conf."""
    instance_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance')
    config_path = os.path.join(instance_path, 'knowledgetree.conf')

    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found at {config_path}")

    config = configparser.RawConfigParser()
    config.read(config_path)
    return config

def get_freshservice_api(domain, api_key, endpoint_with_params):
    """Generic function to handle GET requests to Freshservice API."""
    auth_str = f"{api_key}:X"
    encoded_auth = base64.b64encode(auth_str.encode()).decode()
    headers = {"Content-Type": "application/json", "Authorization": f"Basic {encoded_auth}"}
    url = f"https://{domain}{endpoint_with_params}"

    try:
        response = requests.get(url, headers=headers, timeout=30)
        if response.status_code == 429:
            retry_after = int(response.headers.get('Retry-After', 15))
            print(f"Rate limit hit. Waiting for {retry_after} seconds.")
            time.sleep(retry_after)
            return get_freshservice_api(domain, api_key, endpoint_with_params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching from {url}: {e}", file=sys.stderr)
        return None

def get_latest_stored_ticket_id(session):
    """Queries the database to find the highest ticket ID currently stored."""
    result = session.run("""
        MATCH (t:ContextItem)
        WHERE t.id STARTS WITH 'ticket_'
        RETURN toInteger(substring(t.id, 7)) AS ticket_num
        ORDER BY ticket_num DESC
        LIMIT 1
    """).single()
    return result['ticket_num'] if result else STARTING_TICKET_ID - 1

def get_new_ticket_ids_since(domain, api_key, latest_id):
    """Efficiently finds only ticket IDs newer than the latest one we have."""
    new_ids = []
    page = 1
    print(f"Database contains tickets up to #{latest_id}. Checking for newer ones...")

    while True:
        endpoint = f"/api/v2/tickets?page={page}&per_page=100&order_by=created_at&order_type=desc"
        data = get_freshservice_api(domain, api_key, endpoint)
        if not data or 'tickets' not in data or not data['tickets']:
            break

        found_older_ticket = False
        for ticket in data['tickets']:
            if ticket['id'] > latest_id:
                new_ids.append(ticket['id'])
            else:
                found_older_ticket = True
                break

        if found_older_ticket:
            break

        page += 1
        time.sleep(0.5)

    print(f"Found {len(new_ids)} new tickets to process.")
    return new_ids

def get_all_ticket_ids_for_overwrite(domain, api_key):
    """Gets all ticket IDs for a full refresh."""
    all_ids = []
    page = 1
    print("Overwrite enabled: fetching all ticket IDs since the beginning.")

    while True:
        endpoint = f"/api/v2/tickets?page={page}&per_page=100&order_by=created_at&order_type=asc"
        data = get_freshservice_api(domain, api_key, endpoint)
        if not data or 'tickets' not in data or not data['tickets']:
            break

        page_ids = [t['id'] for t in data['tickets'] if t['id'] >= STARTING_TICKET_ID]
        all_ids.extend(page_ids)

        if not page_ids or len(page_ids) < 100:
            break
        page += 1

    print(f"Found {len(all_ids)} total tickets to process for overwrite.")
    return all_ids

def sanitize_filename(name):
    """Removes invalid characters from a string so it can be used as a filename."""
    return re.sub(r'[<>:"/\\|?*]', '_', name)

def find_user_by_email(session, email):
    """Finds a user's folder ID by email."""
    result = session.run("""
        MATCH (user:ContextItem)
        WHERE user.id CONTAINS $email AND user.is_folder = true
        RETURN user.id as id
        LIMIT 1
    """, email=email.replace('@', '_').replace('.', '_')).single()
    return result['id'] if result else None

def ensure_node(session, parent_id, name, is_folder=False, is_attached=False, content='', read_only=True):
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
                      node.content = $content
        RETURN node.id as id
    """, parent_id=parent_id, node_id=node_id, name=name, is_folder=is_folder,
         is_attached=is_attached, content=content, read_only=read_only).single()

    return result['id']

def sync_tickets(driver, domain, api_key, overwrite=False):
    """Syncs tickets from Freshservice."""
    print("\n--- Syncing Tickets from Freshservice ---")

    with driver.session() as session:
        # Get ticket IDs to process
        if overwrite:
            ticket_ids_to_process = get_all_ticket_ids_for_overwrite(domain, api_key)
        else:
            latest_id = get_latest_stored_ticket_id(session)
            ticket_ids_to_process = get_new_ticket_ids_since(domain, api_key, latest_id)

        if not ticket_ids_to_process:
            print("No new tickets to sync.")
            return

        for ticket_id in sorted(ticket_ids_to_process):
            ticket_id_str = str(ticket_id)
            print(f"Processing Ticket #{ticket_id_str}...")

            # Get full ticket details
            ticket_data = get_freshservice_api(domain, api_key, f"/api/v2/tickets/{ticket_id_str}")
            if not ticket_data or 'ticket' not in ticket_data:
                print(f"  - FAILED to get full details for #{ticket_id_str}")
                continue

            ticket = ticket_data['ticket']

            # Get requester email
            requester_id = ticket.get('requester_id')
            if not requester_id:
                print(f"  - Skipping: No requester ID found.")
                continue

            # Get requester details
            requester_data = get_freshservice_api(domain, api_key, f"/api/v2/requesters/{requester_id}")
            if not requester_data or 'requester' not in requester_data:
                print(f"  - Skipping: Could not get requester details.")
                continue

            requester_email = requester_data['requester'].get('primary_email')
            if not requester_email:
                print(f"  - Skipping: No email for requester.")
                continue

            # Find user folder in KnowledgeTree
            user_folder_id = find_user_by_email(session, requester_email)
            if not user_folder_id:
                print(f"  - Skipping: User {requester_email} not found in KnowledgeTree.")
                continue

            # Ensure Tickets folder exists
            tickets_folder_id = f"{user_folder_id}_Tickets"
            session.run("""
                MATCH (user:ContextItem {id: $user_id})
                MERGE (user)-[:PARENT_OF]->(tickets:ContextItem {id: $tickets_id})
                ON CREATE SET tickets.name = 'Tickets',
                              tickets.is_folder = true,
                              tickets.is_attached = true,
                              tickets.read_only = true
            """, user_id=user_folder_id, tickets_id=tickets_folder_id)

            # Get conversations
            conversations_data = get_freshservice_api(domain, api_key, f"/api/v2/tickets/{ticket_id_str}/conversations")
            conversations = conversations_data.get('conversations', []) if conversations_data else []

            # Build ticket content
            ticket_subject = ticket.get('subject', 'No Subject')
            sanitized_subject = sanitize_filename(ticket_subject)
            ticket_filename = f"{ticket_id_str}_{sanitized_subject}.md"

            description_html = ticket.get('description', '> No description provided.')
            description_md = md(description_html, heading_style="ATX") if description_html else '> No description provided.'

            conversation_md_parts = []
            for conv in conversations:
                sender_name = conv.get('user', {}).get('name', 'Unknown')
                timestamp = conv.get('created_at', 'No Timestamp')
                body_html = conv.get('body', '> No content.')
                body_md = md(body_html, heading_style="ATX") if body_html else '> No content.'
                conversation_md_parts.append(f"### From: {sender_name} at `{timestamp}`\n\n{body_md}\n\n---")

            conversation_md = "\n".join(conversation_md_parts)

            status_name = STATUS_MAP.get(ticket.get('status'), 'N/A')
            priority_name = PRIORITY_MAP.get(ticket.get('priority'), 'N/A')
            agent_name = ticket.get('responder', {}).get('name', 'N/A')

            ticket_md_content = f"""# Ticket #{ticket_id}: {ticket_subject}

- **Status:** {status_name}
- **Priority:** {priority_name}
- **Source:** {ticket.get('source_name', 'N/A')}
- **Created At:** {ticket.get('created_at')}
- **Agent:** {agent_name}
- **Group:** {ticket.get('group', {}).get('name', 'N/A')}

## Description

{description_md}

## Conversations

{conversation_md if conversation_md else "> No conversations found."}
"""

            # Create/update ticket node
            ticket_node_id = f"ticket_{ticket_id_str}"
            ensure_node(session, tickets_folder_id, ticket_filename,
                       is_folder=False, content=ticket_md_content, read_only=True)

            print(f"  - Synced '{ticket_filename}' for {requester_email}")
            time.sleep(0.2)

    print("\n✓ Ticket sync complete!")

if __name__ == "__main__":
    print("--- KnowledgeTree Freshservice Ticket Sync ---")

    try:
        config = get_config()

        # Get Freshservice config
        fs_domain = config.get('freshservice', 'domain')
        fs_api_key = config.get('freshservice', 'api_key')

        if not fs_domain or not fs_api_key:
            print("Freshservice not configured. Run init_db.py to configure.")
            sys.exit(1)

        # Connect to Neo4j
        neo4j_uri = config.get('database', 'neo4j_uri')
        neo4j_user = config.get('database', 'neo4j_user')
        neo4j_password = config.get('database', 'neo4j_password')

        driver = GraphDatabase.driver(neo4j_uri, auth=basic_auth(neo4j_user, neo4j_password))

        # Check for overwrite flag
        should_overwrite = len(sys.argv) > 1 and sys.argv[1].lower() == 'overwrite'

        # Sync tickets
        sync_tickets(driver, fs_domain, fs_api_key, overwrite=should_overwrite)

        driver.close()
        print("\n--- Sync Successful ---")

    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
