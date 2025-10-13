from flask import Flask
import json
import os

# Load environment variables from .flaskenv BEFORE creating app
from dotenv import load_dotenv
load_dotenv('.flaskenv')

app = Flask(__name__, instance_relative_config=True)

# --- Explicitly load all required configuration from environment variables ---
app.config['CORE_SERVICE_URL'] = os.environ.get('CORE_SERVICE_URL')
app.config['SERVICE_NAME'] = os.environ.get('SERVICE_NAME', 'knowledgetree')

if not app.config['CORE_SERVICE_URL']:
    raise ValueError("CORE_SERVICE_URL must be set in the .flaskenv file.")

# Load database connection from config file
import configparser
try:
    os.makedirs(app.instance_path)
except OSError:
    pass

config_path = os.path.join(app.instance_path, 'knowledgetree.conf')
config = configparser.RawConfigParser()
config.read(config_path)
app.config['KT_CONFIG'] = config

# Database configuration (load from config if available)
app.config['NEO4J_URI'] = config.get('database', 'neo4j_uri',
    fallback='bolt://localhost:7687')
app.config['NEO4J_USER'] = config.get('database', 'neo4j_user',
    fallback='neo4j')
app.config['NEO4J_PASSWORD'] = config.get('database', 'neo4j_password',
    fallback='neo4j')

# Upload folder
app.config['UPLOAD_FOLDER'] = os.path.join(app.instance_path, 'uploads')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Load services configuration for service-to-service calls
try:
    with open('services.json') as f:
        services_config = json.load(f)
        app.config['SERVICES'] = services_config
except FileNotFoundError:
    print("WARNING: services.json not found. Service-to-service calls will not work.")
    app.config['SERVICES'] = {}

# Initialize Neo4j driver lazily (only if config exists and has real credentials)
neo4j_driver = None
if config.has_section('database'):
    try:
        from neo4j import GraphDatabase, basic_auth
        neo4j_driver = GraphDatabase.driver(
            app.config['NEO4J_URI'],
            auth=basic_auth(app.config['NEO4J_USER'], app.config['NEO4J_PASSWORD'])
        )
        app.config['NEO4J_DRIVER'] = neo4j_driver

        # Ensure root node exists
        def ensure_root_exists(tx):
            tx.run("""
                MERGE (r:ContextItem {id: 'root', name: 'KnowledgeTree Root'})
                ON CREATE SET r.content = '# Welcome to KnowledgeTree',
                              r.is_folder = true,
                              r.is_attached = false,
                              r.read_only = false
            """)

        def prime_database_schema(tx):
            """Creates and deletes dummy nodes to prime the schema."""
            tx.run("""
                MERGE (dummy_parent:ContextItem {id: 'schema_primer_parent'})
                CREATE (dummy_file:File {id: 'schema_primer_file', filename: 'dummy.txt'})
                CREATE (dummy_parent)-[:HAS_FILE]->(dummy_file)
                DETACH DELETE dummy_parent, dummy_file
            """)

        with neo4j_driver.session() as session:
            session.write_transaction(ensure_root_exists)
            session.write_transaction(prime_database_schema)

        print("✓ Connected to Neo4j and initialized schema")
    except Exception as e:
        print(f"WARNING: Could not connect to Neo4j: {e}")
        print("This is normal during initial setup. Run init_db.py to configure.")
        app.config['NEO4J_DRIVER'] = None
else:
    print("WARNING: Neo4j not configured. Run init_db.py to set up the database.")
    app.config['NEO4J_DRIVER'] = None

# Apply middleware to handle URL prefix when behind Nexus proxy
from app.middleware import PrefixMiddleware
app.wsgi_app = PrefixMiddleware(app.wsgi_app, prefix=f'/{app.config["SERVICE_NAME"]}')

# Initialize Helm logger for centralized logging
app.config["SERVICE_NAME"] = os.environ.get("SERVICE_NAME", "knowledgetree")
app.config["HELM_SERVICE_URL"] = os.environ.get("HELM_SERVICE_URL", "http://localhost:5004")

from app.helm_logger import init_helm_logger
helm_logger = init_helm_logger(
    app.config["SERVICE_NAME"],
    app.config["HELM_SERVICE_URL"]
)

from app import routes

# Log service startup
helm_logger.info(f"{app.config["SERVICE_NAME"]} service started")
