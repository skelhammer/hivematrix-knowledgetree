#!/bin/bash
#
# HiveMatrix KnowledgeTree - Installation Script
# Handles setup of knowledge management system with Neo4j
#

set -e  # Exit on error

APP_NAME="knowledgetree"
APP_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PARENT_DIR="$(dirname "$APP_DIR")"
HELM_DIR="$PARENT_DIR/hivematrix-helm"

echo "=========================================="
echo "  Installing HiveMatrix KnowledgeTree"
echo "=========================================="
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# Parse command line arguments
NEO4J_URI="bolt://localhost:7687"
NEO4J_USER="neo4j"
NEO4J_PASSWORD=""
CODEX_URL="http://localhost:5010"
INSTALL_NEO4J=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --neo4j-uri)
            NEO4J_URI="$2"
            shift 2
            ;;
        --neo4j-user)
            NEO4J_USER="$2"
            shift 2
            ;;
        --neo4j-password)
            NEO4J_PASSWORD="$2"
            shift 2
            ;;
        --codex-url)
            CODEX_URL="$2"
            shift 2
            ;;
        --install-neo4j)
            INSTALL_NEO4J=true
            shift
            ;;
        *)
            shift
            ;;
    esac
done

# Generate Neo4j password if not provided
if [ -z "$NEO4J_PASSWORD" ]; then
    NEO4J_PASSWORD=$(openssl rand -base64 24 | tr -d "=+/" | cut -c1-24)
fi

# Check Python version
echo -e "${YELLOW}Checking Python...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}✗ Python 3 not found${NC}"
    echo "Please install Python 3.8 or higher"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | awk '{print $2}')
echo -e "${GREEN}✓ Found Python $PYTHON_VERSION${NC}"
echo ""

# Check Neo4j
echo -e "${YELLOW}Checking Neo4j...${NC}"
if ! command -v neo4j &> /dev/null; then
    echo -e "${YELLOW}⚠ Neo4j not found${NC}"

    if [ "$INSTALL_NEO4J" = true ]; then
        echo "Installing Neo4j..."

        # Install Neo4j on Ubuntu
        wget -O - https://debian.neo4j.com/neotechnology.gpg.key | sudo apt-key add -
        echo 'deb https://debian.neo4j.com stable latest' | sudo tee /etc/apt/sources.list.d/neo4j.list
        sudo apt-get update
        sudo apt-get install -y neo4j

        # Set initial password
        sudo neo4j-admin set-initial-password "$NEO4J_PASSWORD"

        # Start Neo4j
        sudo systemctl enable neo4j
        sudo systemctl start neo4j

        echo -e "${GREEN}✓ Neo4j installed and started${NC}"
    else
        echo ""
        echo -e "${YELLOW}WARNING: Neo4j is required for KnowledgeTree${NC}"
        echo "Options:"
        echo "  1. Install manually: https://neo4j.com/docs/operations-manual/current/installation/"
        echo "  2. Run this script with --install-neo4j flag"
        echo "  3. Use Docker: docker run -p 7474:7474 -p 7687:7687 neo4j"
        echo ""
        echo "Continuing installation without Neo4j..."
        echo "You can configure it later in instance/knowledgetree.conf"
        echo ""
    fi
else
    echo -e "${GREEN}✓ Neo4j found${NC}"
fi
echo ""

# Create virtual environment
echo -e "${YELLOW}Creating virtual environment...${NC}"
if [ -d "pyenv" ]; then
    echo "  Virtual environment already exists"
else
    python3 -m venv pyenv
    echo -e "${GREEN}✓ Virtual environment created${NC}"
fi
echo ""

# Activate virtual environment
source pyenv/bin/activate

# Upgrade pip
echo -e "${YELLOW}Upgrading pip...${NC}"
pip install --upgrade pip > /dev/null 2>&1
echo -e "${GREEN}✓ pip upgraded${NC}"
echo ""

# Install dependencies
if [ -f "requirements.txt" ]; then
    echo -e "${YELLOW}Installing Python dependencies...${NC}"
    pip install -r requirements.txt
    echo -e "${GREEN}✓ Dependencies installed${NC}"
    echo ""
fi

# Create instance directory if needed
if [ ! -d "instance" ]; then
    echo -e "${YELLOW}Creating instance directory...${NC}"
    mkdir -p instance
    echo -e "${GREEN}✓ Instance directory created${NC}"
    echo ""
fi

# === KNOWLEDGETREE-SPECIFIC SETUP ===
echo -e "${YELLOW}Running KnowledgeTree-specific setup...${NC}"

# 1. Create configuration files
echo "Creating configuration files..."

# Create .flaskenv
cat > .flaskenv <<EOF
FLASK_APP=run.py
FLASK_ENV=development
SERVICE_NAME=knowledgetree

# Services
CORE_SERVICE_URL=http://localhost:5000
CODEX_SERVICE_URL=$CODEX_URL

# Keycloak
KEYCLOAK_URL=http://localhost:8080
KEYCLOAK_REALM=hivematrix
KEYCLOAK_CLIENT_ID=core-client

# Neo4j
NEO4J_URI=$NEO4J_URI
NEO4J_USER=$NEO4J_USER
EOF

# Create instance config
cat > instance/knowledgetree.conf <<EOF
[database]
neo4j_uri = $NEO4J_URI
neo4j_user = $NEO4J_USER
neo4j_password = $NEO4J_PASSWORD

[services]
codex_url = $CODEX_URL
core_url = http://localhost:5000
EOF

echo -e "${GREEN}✓ Configuration files created${NC}"
echo ""

# 2. Test Neo4j connection and initialize
if command -v neo4j &> /dev/null; then
    echo "Testing Neo4j connection..."

    # Try to connect with Python
    python -c "
from neo4j import GraphDatabase
try:
    driver = GraphDatabase.driver('$NEO4J_URI', auth=('$NEO4J_USER', '$NEO4J_PASSWORD'))
    with driver.session() as session:
        result = session.run('RETURN 1')
        result.single()
    print('✓ Neo4j connection successful')
    driver.close()
except Exception as e:
    print(f'⚠ Neo4j connection failed: {e}')
    print('You may need to configure Neo4j credentials manually')
" 2>/dev/null || echo "Note: Install neo4j Python driver with: pip install neo4j"
    echo ""

    # Initialize database schema if script exists
    if [ -f "init_db.py" ]; then
        echo "Initializing Neo4j schema..."
        NEO4J_PASSWORD="$NEO4J_PASSWORD" python init_db.py --non-interactive || echo "Note: Schema may already be initialized"
        echo -e "${GREEN}✓ Neo4j schema initialized${NC}"
        echo ""
    fi
fi

# 3. Sync configuration from Helm (if Helm is installed)
if [ -d "$HELM_DIR" ] && [ -f "$HELM_DIR/config_manager.py" ]; then
    echo "Syncing configuration from Helm..."
    cd "$HELM_DIR"
    source pyenv/bin/activate 2>/dev/null || true

    # Update Helm's master config with KnowledgeTree settings
    python -c "
from config_manager import ConfigManager
cm = ConfigManager()
cm.update_app_config('knowledgetree', {
    'database': 'neo4j',
    'sections': {
        'database': {
            'neo4j_uri': '$NEO4J_URI',
            'neo4j_user': '$NEO4J_USER',
            'neo4j_password': '$NEO4J_PASSWORD'
        },
        'services': {
            'codex_url': '$CODEX_URL',
            'core_url': 'http://localhost:5000'
        }
    }
})
" 2>/dev/null || true

    # Write updated config back to KnowledgeTree
    python config_manager.py write-dotenv knowledgetree 2>/dev/null || true
    python config_manager.py write-conf knowledgetree 2>/dev/null || true

    cd "$APP_DIR"
    echo -e "${GREEN}✓ Configuration synced${NC}"
    echo ""
fi

echo -e "${GREEN}✓ KnowledgeTree-specific setup complete${NC}"
echo ""

echo "=========================================="
echo -e "${GREEN}  KnowledgeTree installed successfully!${NC}"
echo "=========================================="
echo ""
echo "Neo4j Configuration:"
echo "  URI: $NEO4J_URI"
echo "  User: $NEO4J_USER"
echo "  Password: $NEO4J_PASSWORD"
echo ""
echo "Service Configuration:"
echo "  Codex URL: $CODEX_URL"
echo "  Core URL: http://localhost:5000"
echo ""
if ! command -v neo4j &> /dev/null; then
    echo -e "${YELLOW}WARNING: Neo4j is not installed${NC}"
    echo "Install Neo4j before starting KnowledgeTree:"
    echo "  - Manual: https://neo4j.com/docs/operations-manual/current/installation/"
    echo "  - Docker: docker run -p 7474:7474 -p 7687:7687 -e NEO4J_AUTH=neo4j/$NEO4J_PASSWORD neo4j"
    echo "  - Auto: ./install.sh --install-neo4j"
    echo ""
fi
echo "Next steps:"
echo "  1. Ensure Codex and Neo4j are running"
echo "  2. Start KnowledgeTree: python run.py"
echo "  3. Or use Helm to start all services"
echo "  4. Run sync scripts to pull data from Codex"
echo "  5. Access Neo4j browser: http://localhost:7474"
echo ""
