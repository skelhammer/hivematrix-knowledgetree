from app import app
from waitress import serve

if __name__ == "__main__":
    # Security: Bind to localhost only - KnowledgeTree should not be exposed externally
    # Access via Nexus proxy at https://localhost:443/knowledgetree
    print("Starting KnowledgeTree on http://127.0.0.1:5020")
    print("Access via Nexus at https://localhost:443/knowledgetree/")
    serve(app, host='127.0.0.1', port=5020)
