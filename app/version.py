"""
Version utility for HiveMatrix KnowledgeTree.
Reads git information to generate version string.
"""

import subprocess
import os
from datetime import datetime

def get_version():
    """
    Get version string in format: YYYY.MM.DD-<short_hash>
    Example: 2024.11.19-c7f7c81
    """
    try:
        # Get the directory where this script is located
        script_dir = os.path.dirname(os.path.abspath(__file__))
        repo_dir = os.path.dirname(script_dir)  # Go up to repo root

        # Get short git commit hash
        result = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'],
            capture_output=True,
            text=True,
            cwd=repo_dir
        )
        commit_hash = result.stdout.strip() if result.returncode == 0 else 'unknown'

        # Get commit date
        result = subprocess.run(
            ['git', 'log', '-1', '--format=%ci'],
            capture_output=True,
            text=True,
            cwd=repo_dir
        )

        if result.returncode == 0:
            # Parse the date (format: 2024-11-19 14:30:00 -0500)
            date_str = result.stdout.strip().split()[0]
            date_obj = datetime.strptime(date_str, '%Y-%m-%d')
            date_formatted = date_obj.strftime('%Y.%m.%d')
        else:
            date_formatted = datetime.now().strftime('%Y.%m.%d')

        return f"{date_formatted}-{commit_hash}"

    except Exception:
        return "unknown"

def get_service_name():
    """Get the service name for display."""
    return "KnowledgeTree"

# Cache the version at module load time
VERSION = get_version()
SERVICE_NAME = get_service_name()
