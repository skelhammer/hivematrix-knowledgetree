from dotenv import load_dotenv
import os
from pathlib import Path

# Load .flaskenv before importing app
load_dotenv('.flaskenv')

from app import app

if __name__ == "__main__":
    # Collect all template files for auto-reload
    extra_files = []

    # Add all HTML templates
    templates_dir = Path('app/templates')
    if templates_dir.exists():
        for template_file in templates_dir.rglob('*.html'):
            extra_files.append(str(template_file))

    # Add all Python files in app directory
    app_dir = Path('app')
    if app_dir.exists():
        for py_file in app_dir.rglob('*.py'):
            extra_files.append(str(py_file))

    print("Starting KnowledgeTree on http://127.0.0.1:5020", flush=True)
    print("Access via Nexus at https://localhost:443/knowledgetree/", flush=True)
    print("Auto-reload enabled - templates and Python files will reload on change", flush=True)

    # Security: Bind to localhost only - KnowledgeTree should not be exposed externally
    app.run(
        host='127.0.0.1',
        port=5020,
        debug=True,
        extra_files=extra_files
    )
