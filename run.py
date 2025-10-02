from app import app
from waitress import serve

if __name__ == "__main__":
    print("Starting KnowledgeTree on http://0.0.0.0:5020")
    print("Access via Nexus at http://localhost:8000/knowledgetree/")
    serve(app, host='0.0.0.0', port=5020)
