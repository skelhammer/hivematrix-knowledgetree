from app import app
from waitress import serve
import sys

if __name__ == "__main__":
    # Ensure unbuffered output for log capture
    sys.stdout.reconfigure(line_buffering=True)
    sys.stderr.reconfigure(line_buffering=True)

    # Configure Flask request logging to stdout
    @app.after_request
    def log_request(response):
        from flask import request
        print(f'{request.remote_addr} - - "{request.method} {request.path}" {response.status_code}', flush=True)
        return response

    # Security: Bind to localhost only - KnowledgeTree should not be exposed externally
    # Access via Nexus proxy at https://localhost:443/knowledgetree
    print("Starting KnowledgeTree on http://127.0.0.1:5020", flush=True)
    print("Access via Nexus at https://localhost:443/knowledgetree/", flush=True)
    serve(app, host='127.0.0.1', port=5020)
