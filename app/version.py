"""
Version utility for HiveMatrix KnowledgeTree.
Reads git information to generate version string.
Falls back to VERSION file if git is unavailable.
"""

import subprocess
import os
from datetime import datetime

def get_version():
    """
    Get version string in format: YYYY.MM.DD-<short_hash>
    Example: 2024.11.19-c7f7c81

    Tries git first, falls back to VERSION file if git fails.
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_dir = os.path.dirname(script_dir)  # Go up to repo root
    version_file = os.path.join(repo_dir, 'VERSION')

    # Try git first
    version = _get_version_from_git(repo_dir)

    if version and version != 'unknown':
        # Write to VERSION file for fallback
        try:
            with open(version_file, 'w') as f:
                f.write(version)
        except Exception:
            pass  # Ignore write errors (read-only filesystem, etc.)
        return version

    # Fallback: read from VERSION file
    if os.path.exists(version_file):
        try:
            with open(version_file, 'r') as f:
                return f.read().strip()
        except Exception:
            pass

    return "unknown"

def _get_version_from_git(repo_dir):
    """Try to get version from git."""
    try:
        # Get short git commit hash
        result = subprocess.run(
            ['git', 'rev-parse', '--short', 'HEAD'],
            capture_output=True,
            text=True,
            cwd=repo_dir
        )
        if result.returncode != 0:
            return None
        commit_hash = result.stdout.strip()

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
        return None

def get_service_name():
    """Get the service name for display."""
    return "KnowledgeTree"

# Cache the version at module load time
VERSION = get_version()
SERVICE_NAME = get_service_name()
