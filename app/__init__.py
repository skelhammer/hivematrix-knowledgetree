from flask import Flask
import json
import os

# Load environment variables from .flaskenv BEFORE creating app
from dotenv import load_dotenv
load_dotenv('.flaskenv')

app = Flask(__name__, instance_relative_config=True)

# Set maximum content length for incoming requests (50MB for file uploads)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

# Configure logging level from environment
import logging
log_level = os.environ.get('LOG_LEVEL', 'INFO').upper()
app.logger.setLevel(getattr(logging, log_level, logging.INFO))

# Enable structured JSON logging with correlation IDs
# Set ENABLE_JSON_LOGGING=false in environment to disable for development
enable_json = os.environ.get("ENABLE_JSON_LOGGING", "true").lower() in ("true", "1", "yes")
if enable_json:
    from app.structured_logger import setup_structured_logging
    setup_structured_logging(app, enable_json=True)

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

# Use ProxyFix to handle X-Forwarded headers from Nexus
# This sets SCRIPT_NAME based on X-Forwarded-Prefix header
from werkzeug.middleware.proxy_fix import ProxyFix
app.wsgi_app = ProxyFix(
    app.wsgi_app,
    x_for=1,  # Trust X-Forwarded-For
    x_proto=1,  # Trust X-Forwarded-Proto
    x_host=1,  # Trust X-Forwarded-Host
    x_prefix=1  # Trust X-Forwarded-Prefix (sets SCRIPT_NAME)
)

# Initialize rate limiter
from flask_limiter import Limiter
from app.rate_limit_key import get_user_id_or_ip

limiter = Limiter(
    app=app,
    key_func=get_user_id_or_ip,  # Per-user rate limiting
    default_limits=["10000 per hour", "500 per minute"],
    storage_uri="memory://"
)

# Initialize Helm logger for centralized logging
app.config["SERVICE_NAME"] = os.environ.get("SERVICE_NAME", "knowledgetree")
app.config["HELM_SERVICE_URL"] = os.environ.get("HELM_SERVICE_URL", "http://localhost:5004")

from app.helm_logger import init_helm_logger
helm_logger = init_helm_logger(
    app.config["SERVICE_NAME"],
    app.config["HELM_SERVICE_URL"]
)

from app.version import VERSION, SERVICE_NAME as VERSION_SERVICE_NAME

# Context processor to inject version into all templates
@app.context_processor
def inject_version():
    return {
        'app_version': VERSION,
        'app_service_name': VERSION_SERVICE_NAME
    }

# Register RFC 7807 error handlers for consistent API error responses
from app.error_responses import (
    internal_server_error,
    not_found,
    bad_request,
    unauthorized,
    forbidden,
    service_unavailable
)

@app.errorhandler(400)
def handle_bad_request(e):
    """Handle 400 Bad Request errors"""
    return bad_request(detail=str(e))

@app.errorhandler(401)
def handle_unauthorized(e):
    """Handle 401 Unauthorized errors"""
    return unauthorized(detail=str(e))

@app.errorhandler(403)
def handle_forbidden(e):
    """Handle 403 Forbidden errors"""
    return forbidden(detail=str(e))

@app.errorhandler(404)
def handle_not_found(e):
    """Handle 404 Not Found errors"""
    return not_found(detail=str(e))

@app.errorhandler(500)
def handle_internal_error(e):
    """Handle 500 Internal Server Error"""
    app.logger.error(f"Internal server error: {e}")
    return internal_server_error()

@app.errorhandler(503)
def handle_service_unavailable(e):
    """Handle 503 Service Unavailable errors"""
    return service_unavailable(detail=str(e))

@app.errorhandler(Exception)
def handle_unexpected_error(e):
    """Catch-all handler for unexpected exceptions"""
    app.logger.exception(f"Unexpected error: {e}")
    return internal_server_error(detail="An unexpected error occurred")

# Configure OpenAPI/Swagger documentation
from flasgger import Swagger

swagger_config = {
    "headers": [],
    "specs": [
        {
            "endpoint": 'apispec',
            "route": '/apispec.json',
            "rule_filter": lambda rule: True,
            "model_filter": lambda tag: True,
        }
    ],
    "static_url_path": "/flasgger_static",
    "swagger_ui": True,
    "specs_route": "/docs"
}

swagger_template = {
    "info": {
        "title": f"{app.config.get('SERVICE_NAME', 'HiveMatrix')} API",
        "description": "API documentation for HiveMatrix KnowledgeTree - Knowledge base with Neo4j graph database",
        "version": VERSION
    },
    "securityDefinitions": {
        "Bearer": {
            "type": "apiKey",
            "name": "Authorization",
            "in": "header",
            "description": "JWT Authorization header using the Bearer scheme. Example: 'Authorization: Bearer {token}'"
        }
    },
    "security": [
        {
            "Bearer": []
        }
    ]
}

Swagger(app, config=swagger_config, template=swagger_template)

from app import routes

# Log service startup
helm_logger.info(f"{app.config['SERVICE_NAME']} service started")
