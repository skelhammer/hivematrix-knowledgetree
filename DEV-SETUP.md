# Development Setup

## Pre-commit Hooks (Code Quality)

This repository uses pre-commit hooks to maintain code quality and consistency.

### Installation

```bash
# Install pre-commit (one-time setup)
pip install pre-commit

# Install the git hooks (run in repository root)
pre-commit install
```

### Usage

Pre-commit hooks run automatically before each commit. They will:
- Format code with **black** (PEP 8 compliant)
- Sort imports with **isort**
- Lint code with **flake8**
- Remove trailing whitespace
- Ensure files end with newline
- Check for large files and merge conflicts

### Manual Execution

```bash
# Run on all files
pre-commit run --all-files

# Run on staged files only
pre-commit run

# Skip hooks for a commit (use sparingly)
git commit --no-verify -m "message"
```

### Configuration

- `.pre-commit-config.yaml` - Pre-commit hook configuration
- `setup.cfg` - Tool-specific settings (flake8, isort)
- Black uses 100 character line length
- Flake8 ignores E203, W503 (conflicts with black)

### First-Time Setup

When setting up pre-commit on this repository for the first time:

```bash
# Install dependencies
pip install pre-commit black isort flake8

# Install hooks
pre-commit install

# (Optional) Format all existing code
black .
isort .

# Run all hooks to verify
pre-commit run --all-files
```

Note: Pre-commit hooks are optional but highly recommended for maintaining code quality.
