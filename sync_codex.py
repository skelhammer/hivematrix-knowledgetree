#!/usr/bin/env python
"""
Syncs company structure from Codex into KnowledgeTree.

Creates:
  /Companies/
    /{Company Name}/
      /Users/
        /{User Name}/
          Contact.md
      /Assets/
        {hostname}.md
"""

import os
import sys
import configparser
from neo4j import GraphDatabase, basic_auth
from dotenv import load_dotenv

load_dotenv('.flaskenv')
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import app
from app.service_client import call_service
from sync_utils import ensure_node

def get_config():
    """Loads configuration from knowledgetree.conf."""
    instance_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'instance')
    config_path = os.path.join(instance_path, 'knowledgetree.conf')

    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found at {config_path}. Run init_db.py first.")

    config = configparser.RawConfigParser()
    config.read(config_path)
    return config

def sync_companies(driver):
    """Syncs all companies from Codex."""
    print("\n--- Syncing Companies from Codex ---")

    with app.app_context():
        # Get companies from Codex
        response = call_service('codex', '/api/companies')
        companies = response.json()

        print(f"Found {len(companies)} companies in Codex")

        with driver.session() as session:
            # Ensure Companies root folder exists
            companies_root_id = ensure_node(session, 'root', 'Companies', is_folder=True, read_only=False)

            for company_data in companies:
                company_name = company_data['name']
                account_number = company_data['account_number']

                print(f"\n  Processing: {company_name} ({account_number})")

                # Create company folder
                company_id = ensure_node(session, companies_root_id, company_name, is_folder=True)

                # Create Users subfolder
                users_folder_id = ensure_node(session, company_id, 'Users', is_folder=True)

                # Get users for this company from Codex
                users_response = call_service('codex', f'/api/companies/{account_number}/users')
                users = users_response.json()

                print(f"    → Found {len(users)} users")

                for user_data in users:
                    user_name = user_data['name']

                    # Create user folder
                    user_folder_id = ensure_node(session, users_folder_id, user_name, is_folder=True)

                    # Create Contact.md with user details
                    contact_content = f"""# Contact Information for {user_name}

- **Email:** {user_data.get('email', 'N/A')}
- **Title:** {user_data.get('title', 'N/A')}
- **Mobile Phone:** {user_data.get('mobile_phone_number', 'N/A')}
- **Work Phone:** {user_data.get('work_phone_number', 'N/A')}
- **Active:** {'Yes' if user_data.get('active') else 'No'}
"""

                    ensure_node(session, user_folder_id, 'Contact.md',
                              is_folder=False, content=contact_content)

                    # Create Tickets attached folder (will be populated by sync_tickets.py)
                    ensure_node(session, user_folder_id, 'Tickets',
                              is_folder=True, is_attached=True)

                # Create Assets subfolder
                assets_folder_id = ensure_node(session, company_id, 'Assets', is_folder=True)

                # Get assets for this company from Codex
                assets_response = call_service('codex', f'/api/companies/{account_number}/assets')
                assets = assets_response.json() if assets_response.status_code == 200 else []

                print(f"    → Found {len(assets)} assets")

                for asset_data in assets:
                    hostname = asset_data['hostname']

                    # Create asset markdown file
                    asset_content = f"""# Computer Information: {hostname}

- **Operating System:** {asset_data.get('operating_system', 'N/A')}
- **Hardware Type:** {asset_data.get('hardware_type', 'N/A')}
- **Internal IP:** {asset_data.get('int_ip_address', 'N/A')}
- **External IP:** {asset_data.get('ext_ip_address', 'N/A')}
- **Last Logged In User:** {asset_data.get('last_logged_in_user', 'N/A')}
- **Status:** {'✓ Online' if asset_data.get('online') else '✗ Offline'}
- **Last Seen:** {asset_data.get('last_seen', 'N/A')}
- **Domain:** {asset_data.get('domain', 'N/A')}
"""

                    ensure_node(session, assets_folder_id, f"{hostname}.md",
                              is_folder=False, content=asset_content)

    print("\n✓ Codex sync complete!")

if __name__ == "__main__":
    print("--- KnowledgeTree Codex Sync ---")

    try:
        config = get_config()

        # Connect to Neo4j
        neo4j_uri = config.get('database', 'neo4j_uri')
        neo4j_user = config.get('database', 'neo4j_user')
        neo4j_password = config.get('database', 'neo4j_password')

        driver = GraphDatabase.driver(neo4j_uri, auth=basic_auth(neo4j_user, neo4j_password))

        # Sync companies
        sync_companies(driver)

        driver.close()
        print("\n--- Sync Successful ---")

    except Exception as e:
        print(f"\nAn unexpected error occurred: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
