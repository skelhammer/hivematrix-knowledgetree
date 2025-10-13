from app import app
from waitress import serve
import logging

if __name__ == "__main__":
    # Configure logging to stdout for log file capture
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        handlers=[logging.StreamHandler()]
    )

    # Security: Bind to localhost only - KnowledgeTree should not be exposed externally
    # Access via Nexus proxy at https://localhost:443/knowledgetree
    print("Starting KnowledgeTree on http://127.0.0.1:5020")
    print("Access via Nexus at https://localhost:443/knowledgetree/")

    # Serve with access logging enabled
    logger = logging.getLogger('waitress')
    logger.setLevel(logging.INFO)
    serve(app, host='127.0.0.1', port=5020)
