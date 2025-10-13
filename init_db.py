import os
import sys
import configparser
import argparse
from getpass import getpass
from neo4j import GraphDatabase, basic_auth
from dotenv import load_dotenv

load_dotenv('.flaskenv')
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import app

def get_neo4j_credentials(config, non_interactive=False):
    """Prompts the user for Neo4j connection details or uses existing config."""

    defaults = {
        'uri': os.environ.get('NEO4J_URI', 'bolt://localhost:7687'),
        'user': os.environ.get('NEO4J_USER', 'neo4j'),
        'password': os.environ.get('NEO4J_PASSWORD', '')
    }

    if config.has_section('database'):
        defaults['uri'] = config.get('database', 'neo4j_uri', fallback=defaults['uri'])
        defaults['user'] = config.get('database', 'neo4j_user', fallback=defaults['user'])
        defaults['password'] = config.get('database', 'neo4j_password', fallback=defaults['password'])

    # In non-interactive mode, use existing configuration
    if non_interactive:
        if not defaults['password']:
            print("ERROR: Neo4j password not found in configuration or environment", file=sys.stderr)
            sys.exit(1)
        return defaults

    # Interactive mode - prompt for values
    print("\n--- Neo4j Database Configuration ---")

    uri = input(f"Neo4j URI [{defaults['uri']}]: ") or defaults['uri']
    user = input(f"Neo4j User [{defaults['user']}]: ") or defaults['user']

    if defaults['password'] and defaults['password'] not in ['', 'neo4j']:
        password_prompt = f"Neo4j Password [****{defaults['password'][-4:]}]: "
    else:
        password_prompt = "Neo4j Password: "

    password_input = getpass(password_prompt)
    password = password_input if password_input else defaults['password']

    return {
        'uri': uri,
        'user': user,
        'password': password
    }

def test_neo4j_connection(creds):
    """Tests the Neo4j connection."""
    try:
        driver = GraphDatabase.driver(creds['uri'], auth=basic_auth(creds['user'], creds['password']))
        with driver.session() as session:
            session.run("RETURN 1")
        driver.close()
        print("\n✓ Neo4j connection successful!")
        return True
    except Exception as e:
        print(f"\n✗ Connection failed: {e}", file=sys.stderr)
        return False

def get_codex_config(config, non_interactive=False):
    """Prompts for Codex service configuration or uses existing config."""
    defaults = {
        'url': os.environ.get('CODEX_SERVICE_URL', 'http://localhost:5010')
    }

    if config.has_section('codex') or config.has_section('services'):
        section = 'services' if config.has_section('services') else 'codex'
        defaults['url'] = config.get(section, 'codex_url', fallback=defaults['url'])

    # In non-interactive mode, use existing configuration
    if non_interactive:
        return defaults

    # Interactive mode - prompt for values
    print("\n--- Codex Integration Configuration ---")
    print("KnowledgeTree syncs all data from Codex (companies, contacts, tickets, etc.)")

    url = input(f"Codex Service URL [{defaults['url']}]: ") or defaults['url']

    return {'url': url}

def init_db(non_interactive=False):
    """Configures and initializes the database."""
    instance_path = app.instance_path
    config_path = os.path.join(instance_path, 'knowledgetree.conf')

    config = configparser.RawConfigParser()

    config_exists = os.path.exists(config_path)
    if config_exists:
        config.read(config_path)
        if not non_interactive:
            print(f"\n✓ Existing configuration found: {config_path}")
            print("Press Enter to keep existing values, or type new values to update.")
    else:
        if not non_interactive:
            print(f"\n→ No existing configuration found. Creating new config: {config_path}")

    # Neo4j configuration
    while True:
        creds = get_neo4j_credentials(config, non_interactive)

        # In non-interactive mode, only test connection once
        connection_ok = test_neo4j_connection(creds)

        if connection_ok:
            if not config.has_section('database'):
                config.add_section('database')
            config.set('database', 'neo4j_uri', creds['uri'])
            config.set('database', 'neo4j_user', creds['user'])
            config.set('database', 'neo4j_password', creds['password'])
            break
        else:
            if non_interactive:
                # In non-interactive mode, don't fail - just warn
                print("WARNING: Could not connect to Neo4j: {}", file=sys.stderr)
                print("This is normal during initial setup. Run init_db.py to configure.", file=sys.stderr)
                # Still save the config for later
                if not config.has_section('database'):
                    config.add_section('database')
                config.set('database', 'neo4j_uri', creds['uri'])
                config.set('database', 'neo4j_user', creds['user'])
                config.set('database', 'neo4j_password', creds['password'])
                break
            else:
                retry = input("\nWould you like to try again? (y/n): ").lower()
                if retry != 'y':
                    sys.exit("Database configuration aborted.")

    # Codex configuration
    codex_config = get_codex_config(config, non_interactive)
    if not config.has_section('services'):
        config.add_section('services')
    config.set('services', 'codex_url', codex_config['url'])
    config.set('services', 'core_url', os.environ.get('CORE_SERVICE_URL', 'http://localhost:5000'))

    # Note: KnowledgeTree pulls all data from Codex, not external services
    if not non_interactive:
        print("\n" + "="*70)
        print("IMPORTANT: KnowledgeTree pulls data from Codex, not external services")
        print("="*70)
        print("Codex syncs from Freshservice/Datto and provides data to KnowledgeTree")
        print("Configure Codex connection above, then run sync scripts:")
        print("  - sync_codex.py (company structure)")
        print("  - sync_tickets.py (ticket data from Codex)")
        print("="*70)

    # Save configuration
    with open(config_path, 'w') as configfile:
        config.write(configfile)

    if not non_interactive:
        print(f"\n✓ Configuration saved to: {config_path}")

        print("\n" + "="*70)
        print(" 🎉 KnowledgeTree Initialization Complete!")
        print("="*70)
        print("\nNext steps:")
        print("  1. Sync company structure from Codex:")
        print("     → python sync_codex.py")
        print("  2. Sync tickets from Codex:")
        print("     → python sync_tickets.py")
        print("  3. Start the KnowledgeTree service:")
        print("     → flask run --port=5020         # Development")
        print("     → python run.py                 # Production (Waitress)")
        print("\n  Access at: http://localhost:5020")
        print("  (Login via Core/Nexus gateway at http://localhost:8000/knowledgetree/)")
        print("="*70)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Initialize KnowledgeTree database')
    parser.add_argument('--non-interactive', action='store_true',
                        help='Run in non-interactive mode using existing config/environment')
    args = parser.parse_args()

    init_db(non_interactive=args.non_interactive)
