from datetime import datetime
import json
import os
import sys
import uuid
from urllib.parse import unquote, quote
from flask import render_template, request, jsonify, send_from_directory, send_file, redirect, g, current_app, url_for
from werkzeug.utils import secure_filename
from app import app, limiter
from app.auth import token_required, admin_required
from app.service_client import call_service
import markdown
import bleach

# HTML sanitization settings for editor content (prevents XSS)
ALLOWED_TAGS = [
    'p', 'br', 'strong', 'em', 'u', 's', 'del', 'i', 'b',
    'code', 'pre', 'kbd', 'mark', 'sub', 'sup',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'ul', 'ol', 'li', 'blockquote', 'a', 'img', 'figure', 'figcaption',
    'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td', 'caption', 'colgroup', 'col',
    'hr', 'span', 'div', 'label', 'input'
]
ALLOWED_ATTRIBUTES = {
    'a': ['href', 'title', 'target', 'rel'],
    'img': ['src', 'alt', 'title', 'width', 'height', 'style'],
    'code': ['class'],
    'pre': ['class', 'data-language'],
    'span': ['class', 'style'],
    'div': ['class', 'style'],
    'p': ['style'],
    'th': ['align', 'style', 'colspan', 'rowspan', 'scope'],
    'td': ['align', 'style', 'colspan', 'rowspan'],
    'table': ['class', 'style'],
    'figure': ['class', 'style'],
    'li': ['class'],  # For todo list items
    'label': ['class'],
    'input': ['type', 'checked', 'disabled'],  # For checkboxes in todo lists
}

# File upload security settings
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'md', 'doc', 'docx', 'xls', 'xlsx', 'csv', 'json', 'xml'}
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB


def allowed_file(filename):
    """Check if file extension is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Health check library
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from health_check import HealthChecker

# --- Helper Functions ---
def get_neo4j_driver():
    """Get Neo4j driver or return None with error response"""
    driver = current_app.config['NEO4J_DRIVER']
    if driver is None:
        error_response = render_template('error.html',
                                         error_title="Database Not Configured",
                                         error_message="Neo4j database is not configured. Please contact your administrator or run init_db.py to set up the database.",
                                         user=g.get('user')), 503
        return None, error_response
    return driver, None

# --- URL Generation Helper ---
@app.template_filter('quote_plus')
def quote_plus_filter(s):
    return quote(s)

# --- Main Routes ---

@app.route('/')
@token_required
def index():
    """Redirect to browse root."""
    if g.is_service_call:
        return {'error': 'This endpoint is for users only'}, 403
    return redirect(url_for('browse', path=''))

@app.route('/browse/', defaults={'path': ''})
@app.route('/browse/<path:path>')
@token_required
def browse(path):
    """Browse the knowledge tree."""
    if g.is_service_call:
        return {'error': 'This endpoint is for users only'}, 403

    driver, error = get_neo4j_driver()
    if error:
        return error

    path_parts = [p for p in path.split('/') if p]
    parent_path = "/".join([quote(part) for part in path_parts[:-1]])

    with driver.session() as session:
        query = "MATCH (n0:ContextItem {id: 'root'})"
        match_clauses, where_clauses, params = [], [], {}

        for i, part in enumerate(path_parts):
            prev_node, curr_node = f"n{i}", f"n{i+1}"
            param_name = f"part_{i}"
            match_clauses.append(f"MATCH ({prev_node})-[:PARENT_OF]->({curr_node})")
            where_clauses.append(f"{curr_node}.name = ${param_name}")
            params[param_name] = unquote(part)

        full_query = "\n".join([query] + match_clauses)
        if where_clauses:
            full_query += "\nWHERE " + " AND ".join(where_clauses)
        full_query += f"\nRETURN n{len(path_parts)}.id as id"

        result = session.run(full_query, params).single()
        node_id = result['id'] if result else 'root'

        children_query = """
            MATCH (:ContextItem {id: $parent_id})-[:PARENT_OF]->(child)
            RETURN DISTINCT child.id AS id, child.name AS name, child.is_folder AS is_folder,
                   child.is_attached as is_attached, child.read_only as read_only
            ORDER BY child.is_folder DESC, child.name
        """
        children_result = session.run(children_query, parent_id=node_id)
        items = [dict(record) for record in children_result]

        path_query = """
            MATCH path = (:ContextItem {id: 'root'})-[:PARENT_OF*0..]->(:ContextItem {id: $node_id})
            RETURN [n in nodes(path) | n.name] AS names
        """
        path_result = session.run(path_query, node_id=node_id).single()
        breadcrumb_names = path_result['names'] if path_result else ["KnowledgeTree Root"]

    # Check for article query parameter (for direct article links)
    open_article_id = request.args.get('article', '')

    return render_template('index.html',
                           items=items,
                           breadcrumb_names=breadcrumb_names,
                           current_path=path,
                           current_node_id=node_id,
                           parent_path=parent_path,
                           open_article_id=open_article_id,
                           user=g.user)

@app.route('/view/<node_id>')
@token_required
def view_node(node_id):
    """Redirect to browse page with article parameter for inline viewing."""
    if g.is_service_call:
        return {'error': 'This endpoint is for users only'}, 403

    driver, error = get_neo4j_driver()
    if error:
        return error

    with driver.session() as session:
        # Get the parent folder path for this node
        path_query = """
            MATCH p = shortestPath((:ContextItem {id: 'root'})-[:PARENT_OF*..]->(:ContextItem {id: $node_id}))
            RETURN [n IN nodes(p) | n.name] AS names
        """
        result = session.run(path_query, node_id=node_id).single()

        parent_path = ''
        if result and result['names']:
            parent_path_parts = result['names'][1:-1]
            parent_path = "/".join([quote(name) for name in parent_path_parts])

    # Redirect to browse page with article query parameter
    return redirect(url_for('browse', path=parent_path, article=node_id))

@app.route('/uploads/<filename>')
@token_required
def uploaded_file(filename):
    """Serve uploaded files."""
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], filename)

# --- API Endpoints ---

@app.route('/api/search', methods=['GET'])
@token_required
def search_nodes():
    """Search for knowledge base articles and folders.
    ---
    tags:
      - Knowledge Base
    summary: Search knowledge base
    description: |
      Searches the knowledge base graph for nodes (articles, folders) matching the query.
      Searches both node names and content for matches.

      Returns up to 15 results with full path information for navigation.
    security:
      - Bearer: []
    parameters:
      - name: query
        in: query
        type: string
        required: true
        description: Search query string (case-insensitive)
        example: "email configuration"
      - name: start_node_id
        in: query
        type: string
        required: false
        default: "root"
        description: Node ID to start search from (for scoped searches)
        example: "root"
    responses:
      200:
        description: Search results returned successfully
        schema:
          type: array
          items:
            type: object
            properties:
              id:
                type: string
                example: "kb-article-123"
              name:
                type: string
                example: "Email Configuration Guide"
              is_folder:
                type: boolean
                example: false
              folder_path:
                type: string
                description: Human-readable path to the node
                example: "IT Documentation / Email / Configuration"
              url_path:
                type: string
                description: URL-encoded path for navigation
                example: "IT%20Documentation/Email/Configuration"
      401:
        description: Unauthorized - Invalid or missing JWT token
    """
    query = request.args.get('query', '')
    start_node_id = request.args.get('start_node_id', 'root')

    if not query:
        return jsonify([])

    driver, error = get_neo4j_driver()
    if error:
        return error

    with driver.session() as session:
        result = session.run("""
            MATCH (startNode:ContextItem {id: $start_node_id})-[:PARENT_OF*0..]->(node)
            WHERE toLower(node.name) CONTAINS toLower($query)
               OR (node.content IS NOT NULL AND toLower(node.content) CONTAINS toLower($query))
            WITH DISTINCT node
            MATCH p = (:ContextItem {id: 'root'})-[:PARENT_OF*..]->(node)
            RETURN node.id as id,
                   node.name as name,
                   node.is_folder as is_folder,
                   [n IN nodes(p) | n.name] AS path_names
            LIMIT 15
        """, {'start_node_id': start_node_id, 'query': query})

        processed_results = []
        for record in result:
            record_dict = dict(record)
            path_list = record_dict['path_names'][1:]
            # Display path (not URL encoded)
            display_path = " / ".join(path_list) if path_list else "root"
            # URL path (encoded for navigation)
            url_path = "/".join([quote(name) for name in path_list])
            record_dict['folder_path'] = display_path
            record_dict['url_path'] = url_path
            processed_results.append(record_dict)

        return jsonify(processed_results)

@app.route('/api/browse', methods=['GET'])
@token_required
def api_browse():
    """
    API endpoint for browsing the knowledge tree.
    This allows service-to-service calls.

    Query params:
        path: Path to browse (default: /)

    Returns:
        {
            "path": "/some/path",
            "categories": [{"name": "Folder", "path": "/some/path/Folder"}],
            "articles": [{"id": "node-123", "title": "Article Name", "summary": "..."}]
        }
    """
    path = request.args.get('path', '/')

    driver, error = get_neo4j_driver()
    if error:
        return jsonify({'error': 'Database not configured'}), 503

    # Remove leading/trailing slashes and split path
    path = path.strip('/')
    path_parts = [p for p in path.split('/') if p]

    with driver.session() as session:
        # Find the node at this path
        query = "MATCH (n0:ContextItem {id: 'root'})"
        match_clauses, where_clauses, params = [], [], {}

        for i, part in enumerate(path_parts):
            prev_node, curr_node = f"n{i}", f"n{i+1}"
            param_name = f"part_{i}"
            match_clauses.append(f"MATCH ({prev_node})-[:PARENT_OF]->({curr_node})")
            where_clauses.append(f"{curr_node}.name = ${param_name}")
            params[param_name] = unquote(part)

        full_query = "\n".join([query] + match_clauses)
        if where_clauses:
            full_query += "\nWHERE " + " AND ".join(where_clauses)
        full_query += f"\nRETURN n{len(path_parts)}.id as id"

        result = session.run(full_query, params).single()
        if not result:
            return jsonify({'error': 'Path not found', 'path': f'/{path}'}), 404

        node_id = result['id']

        # Get children
        children_query = """
            MATCH (:ContextItem {id: $parent_id})-[:PARENT_OF]->(child)
            RETURN DISTINCT child.id AS id, child.name AS name, child.is_folder AS is_folder,
                   child.content as content
            ORDER BY child.is_folder DESC, child.name
        """
        children_result = session.run(children_query, parent_id=node_id)

        categories = []
        articles = []

        for record in children_result:
            if record['is_folder']:
                child_path = f"/{path}/{record['name']}" if path else f"/{record['name']}"
                categories.append({
                    'name': record['name'],
                    'path': child_path
                })
            else:
                # Extract summary from content (first 200 chars)
                content = record['content'] or ''
                summary = content[:200] + '...' if len(content) > 200 else content
                articles.append({
                    'id': record['id'],
                    'title': record['name'],
                    'summary': summary
                })

        return jsonify({
            'path': f'/{path}' if path else '/',
            'current_node': {'id': node_id},
            'categories': categories,
            'articles': articles
        })

@app.route('/api/node', methods=['POST'])
@token_required
def create_node():
    """Create a new node."""
    data = request.json
    parent_id = data.get('parent_id')
    name = data.get('name')
    is_folder = data.get('is_folder', False)
    is_attached = data.get('is_attached', False)

    if not all([parent_id, name]):
        return jsonify({'error': 'parent_id and name are required'}), 400

    new_id = str(uuid.uuid4())
    driver, error = get_neo4j_driver()
    if error:
        return error

    with driver.session() as session:
        # Check for duplicate name in same parent
        duplicate_check = session.run("""
            MATCH (parent:ContextItem {id: $parent_id})-[:PARENT_OF]->(existing)
            WHERE existing.name = $name
            RETURN existing.id as existing_id
        """, parent_id=parent_id, name=name).single()

        if duplicate_check:
            return jsonify({
                'error': 'A node with this name already exists in this location',
                'existing_id': duplicate_check['existing_id']
            }), 409

        session.run("""
            MATCH (parent:ContextItem {id: $parent_id})
            CREATE (child:ContextItem {
                id: $id,
                name: $name,
                is_folder: $is_folder,
                content: '',
                is_attached: $is_attached,
                read_only: false
            })
            CREATE (parent)-[:PARENT_OF]->(child)
        """, parent_id=parent_id, id=new_id, name=name, is_folder=is_folder, is_attached=is_attached)

    return jsonify({'success': True, 'id': new_id})

@app.route('/api/node/<node_id>', methods=['GET'])
@token_required
def get_node(node_id):
    """Get node details."""
    driver, error = get_neo4j_driver()
    if error:
        return error

    with driver.session() as session:
        result = session.run("""
            MATCH (n:ContextItem {id: $node_id})
            OPTIONAL MATCH (n)-[:HAS_FILE]->(f:File)
            RETURN n.id AS id, n.name AS name, n.content AS content, n.is_folder AS is_folder,
                   n.is_attached as is_attached, n.read_only as read_only,
                   n.content_format as content_format,
                   collect({id: f.id, filename: f.filename}) AS files
        """, node_id=node_id).single()

        if result:
            data = dict(result)
            content = data.get('content') or ''
            content_format = data.get('content_format') or 'markdown'

            # If content is already HTML, just sanitize it
            if content_format == 'html':
                data['content_html'] = bleach.clean(content, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES)
            else:
                # Convert markdown to HTML for display
                import re
                markdown_content = content
                content = re.sub(r'~~(.*?)~~', r'<del>\1</del>', content)
                raw_html = markdown.markdown(content, extensions=['fenced_code', 'tables', 'nl2br'])
                data['content_html'] = bleach.clean(raw_html, tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES)
                # Also return raw markdown for editing
                data['content_markdown'] = markdown_content

            data['files'] = [f for f in data.get('files', []) if f['id'] is not None]
            return jsonify(data)
        else:
            return jsonify({'error': 'Node not found'}), 404

@app.route('/api/node/<node_id>', methods=['PUT'])
@token_required
def update_node(node_id):
    """Update node details."""
    data = request.json
    driver, error = get_neo4j_driver()
    if error:
        return error

    with driver.session() as session:
        # Handle HTML content from CKEditor (sanitize it first)
        if 'content_html' in data:
            sanitized_html = bleach.clean(data['content_html'], tags=ALLOWED_TAGS, attributes=ALLOWED_ATTRIBUTES)
            # Store the HTML directly in content field (no longer markdown)
            session.run("MATCH (n:ContextItem {id: $id}) SET n.content = $content, n.content_format = 'html'",
                        id=node_id, content=sanitized_html)
        # Handle markdown content (legacy/API usage)
        elif 'content' in data:
            session.run("MATCH (n:ContextItem {id: $id}) SET n.content = $content, n.content_format = 'markdown'",
                        id=node_id, content=data['content'])
        if 'name' in data:
            session.run("MATCH (n:ContextItem {id: $id}) SET n.name = $name",
                        id=node_id, name=data['name'])

    return jsonify({'success': True})

@app.route('/api/folders/tree', methods=['GET'])
@token_required
def get_folder_tree():
    """Get folder hierarchy as a tree structure (optimized single query)."""
    driver, error = get_neo4j_driver()
    if error:
        return error

    with driver.session() as session:
        # Single query to get all folders with their parent relationships
        result = session.run("""
            MATCH (parent:ContextItem)-[:PARENT_OF]->(child:ContextItem)
            WHERE child.is_folder = true
            RETURN parent.id as parent_id, child.id as id, child.name as name,
                   child.is_attached as is_attached
            ORDER BY child.name
        """)

        # Build lookup of children by parent_id
        children_by_parent = {}
        for record in result:
            parent_id = record['parent_id']
            if parent_id not in children_by_parent:
                children_by_parent[parent_id] = []
            children_by_parent[parent_id].append({
                'id': record['id'],
                'name': record['name'],
                'is_attached': record['is_attached'],
                'children': []  # Will be populated below
            })

        # Recursively build tree from lookup (no additional queries)
        def build_tree(parent_id):
            children = children_by_parent.get(parent_id, [])
            for child in children:
                child['children'] = build_tree(child['id'])
            return children

        root = {
            'id': 'root',
            'name': 'KnowledgeTree Root',
            'is_attached': False,
            'children': build_tree('root')
        }

    return jsonify(root)

@app.route('/api/node/<node_id>/children', methods=['GET'])
@token_required
def get_node_children(node_id):
    """Get immediate children of a node."""
    driver, error = get_neo4j_driver()
    if error:
        return error

    with driver.session() as session:
        result = session.run("""
            MATCH (:ContextItem {id: $parent_id})-[:PARENT_OF]->(child:ContextItem)
            RETURN child.id as id, child.name as name, child.is_folder as is_folder,
                   child.is_attached as is_attached, child.read_only as read_only
            ORDER BY child.is_folder DESC, child.name
        """, parent_id=node_id)

        children = [dict(record) for record in result]
        return jsonify(children)

@app.route('/api/node/<node_id>/browse', methods=['GET'])
@token_required
def api_browse_node(node_id):
    """Get folder contents and breadcrumb for AJAX navigation."""
    driver, error = get_neo4j_driver()
    if error:
        return error

    with driver.session() as session:
        # Get folder info
        node_result = session.run("""
            MATCH (n:ContextItem {id: $node_id})
            RETURN n.id as id, n.name as name, n.is_folder as is_folder
        """, node_id=node_id).single()

        if not node_result:
            return jsonify({'error': 'Node not found'}), 404

        if not node_result['is_folder']:
            return jsonify({'error': 'Not a folder'}), 400

        # Get children
        children_result = session.run("""
            MATCH (:ContextItem {id: $parent_id})-[:PARENT_OF]->(child:ContextItem)
            RETURN child.id as id, child.name as name, child.is_folder as is_folder,
                   child.is_attached as is_attached, child.read_only as read_only
            ORDER BY child.is_folder DESC, child.name
        """, parent_id=node_id)
        children = [dict(record) for record in children_result]

        # Get breadcrumb path
        path_result = session.run("""
            MATCH path = (:ContextItem {id: 'root'})-[:PARENT_OF*0..]->(:ContextItem {id: $node_id})
            RETURN [n in nodes(path) | {id: n.id, name: n.name}] AS breadcrumb
        """, node_id=node_id).single()

        breadcrumb = path_result['breadcrumb'] if path_result else [{'id': 'root', 'name': 'KnowledgeTree Root'}]

        # Build URL path from breadcrumb (excluding root)
        url_path = '/'.join([quote(b['name']) for b in breadcrumb[1:]]) if len(breadcrumb) > 1 else ''

        return jsonify({
            'id': node_id,
            'name': node_result['name'],
            'children': children,
            'breadcrumb': breadcrumb,
            'url_path': url_path
        })

@app.route('/api/node/<node_id>/move', methods=['POST'])
@token_required
def move_node(node_id):
    """Move node to a new parent folder."""
    data = request.json
    new_parent_id = data.get('new_parent_id')

    if not new_parent_id:
        return jsonify({'error': 'new_parent_id is required'}), 400

    driver, error = get_neo4j_driver()
    if error:
        return error

    with driver.session() as session:
        # Check if the node exists and is not root
        node_check = session.run("MATCH (n:ContextItem {id: $id}) RETURN n.id as id", id=node_id).single()
        if not node_check or node_id == 'root':
            return jsonify({'error': 'Cannot move root or non-existent node'}), 400

        # Check if new parent exists and is a folder
        parent_check = session.run(
            "MATCH (p:ContextItem {id: $id}) RETURN p.is_folder as is_folder",
            id=new_parent_id
        ).single()
        if not parent_check:
            return jsonify({'error': 'Parent folder not found'}), 404
        if not parent_check['is_folder']:
            return jsonify({'error': 'Target must be a folder'}), 400

        # Check if moving to itself or a descendant (would create a cycle)
        cycle_check = session.run("""
            MATCH path = (child:ContextItem {id: $child_id})-[:PARENT_OF*0..]->(parent:ContextItem {id: $parent_id})
            RETURN count(path) > 0 as would_cycle
        """, child_id=node_id, parent_id=new_parent_id).single()

        if cycle_check and cycle_check['would_cycle']:
            return jsonify({'error': 'Cannot move a folder into itself or its descendants'}), 400

        # Delete old parent relationship and create new one
        session.run("""
            MATCH (old_parent)-[r:PARENT_OF]->(node:ContextItem {id: $node_id})
            DELETE r
        """, node_id=node_id)

        session.run("""
            MATCH (new_parent:ContextItem {id: $parent_id})
            MATCH (node:ContextItem {id: $node_id})
            CREATE (new_parent)-[:PARENT_OF]->(node)
        """, parent_id=new_parent_id, node_id=node_id)

    return jsonify({'success': True})

@app.route('/api/node/<node_id>', methods=['DELETE'])
@token_required
def delete_node(node_id):
    """Delete a node and its children."""
    driver, error = get_neo4j_driver()
    if error:
        return error

    with driver.session() as session:
        session.run("""
            MATCH (n:ContextItem {id: $id})
            OPTIONAL MATCH (n)-[:PARENT_OF*0..]->(child)
            DETACH DELETE n, child
        """, id=node_id)

    return jsonify({'success': True})

@app.route('/api/upload/<node_id>', methods=['POST'])
@token_required
def upload_file_to_node(node_id):
    """Upload a file to a node."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400

    file = request.files['file']
    if not file or file.filename == '':
        return jsonify({'error': 'No file selected'}), 400

    # Sanitize filename to prevent path traversal attacks
    original_filename = secure_filename(file.filename)
    if not original_filename:
        return jsonify({'error': 'Invalid filename'}), 400

    # Validate file extension
    if not allowed_file(original_filename):
        return jsonify({'error': 'File type not allowed'}), 400

    # Check file size (read content length or seek to end)
    file.seek(0, 2)  # Seek to end
    file_size = file.tell()
    file.seek(0)  # Reset to beginning
    if file_size > MAX_FILE_SIZE:
        return jsonify({'error': f'File too large (max {MAX_FILE_SIZE // (1024*1024)}MB)'}), 413

    # Verify node exists before uploading
    driver, error = get_neo4j_driver()
    if error:
        return error

    with driver.session() as session:
        node_check = session.run(
            "MATCH (n:ContextItem {id: $id}) RETURN n.id",
            id=node_id
        ).single()
        if not node_check:
            return jsonify({'error': 'Node not found'}), 404

    # Use UUID-based filename to prevent any remaining traversal issues
    file_id = str(uuid.uuid4())
    file_ext = original_filename.rsplit('.', 1)[1].lower() if '.' in original_filename else ''
    safe_filename = f"{file_id}.{file_ext}" if file_ext else file_id

    try:
        file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], safe_filename))
    except Exception as e:
        current_app.logger.error(f"File save error: {e}")
        return jsonify({'error': 'Failed to save file'}), 500

    # Store file record in database with both safe and original filenames
    with driver.session() as session:
        session.run("""
            MATCH (n:ContextItem {id: $node_id})
            CREATE (f:File {id: $file_id, filename: $safe_filename, original_filename: $original_filename})
            CREATE (n)-[:HAS_FILE]->(f)
        """, node_id=node_id, file_id=file_id, safe_filename=safe_filename, original_filename=original_filename)

    return jsonify({'success': True, 'filename': original_filename, 'file_id': file_id})

@app.route('/api/context/tree/<node_id>', methods=['GET'])
@token_required
def get_context_tree(node_id):
    """Get the context tree for a node (attached folders)."""
    driver, error = get_neo4j_driver()
    if error:
        return error

    with driver.session() as session:
        result = session.run("""
            MATCH p = (:ContextItem {id: 'root'})-[:PARENT_OF*0..]->(:ContextItem {id: $node_id})
            WITH nodes(p) AS path_nodes
            UNWIND path_nodes as ancestor
            MATCH (ancestor)-[:PARENT_OF]->(attached:ContextItem {is_attached: true})
            RETURN DISTINCT attached.id as id, attached.name as name
        """, node_id=node_id)

        attached_folders = [dict(record) for record in result]
        return jsonify({'attached_folders': attached_folders})

@app.route('/api/context/<node_id>', methods=['GET', 'POST'])
@token_required
def get_context(node_id):
    """Get the full context for a node."""
    excluded_attached_ids = []
    if request.method == 'POST':
        data = request.json
        excluded_attached_ids = data.get('excluded_ids', [])

    driver, error = get_neo4j_driver()
    if error:
        return error
    all_context_blocks = []

    with driver.session() as session:
        path_query = """
            MATCH p = (:ContextItem {id: 'root'})-[:PARENT_OF*0..]->(:ContextItem {id: $node_id})
            RETURN nodes(p) AS path_nodes
        """
        result = session.run(path_query, node_id=node_id).single()

        if not result:
            return jsonify({'error': 'Node not found'}), 404

        path_nodes = result['path_nodes']

        for i, node in enumerate(path_nodes):
            articles_query = """
                MATCH (folder:ContextItem {id: $folder_id})-[:PARENT_OF]->(child)
                WHERE NOT child.is_folder AND (child.is_attached IS NULL OR child.is_attached = false)
                RETURN child.id as id, child.name AS name, child.content AS content, "" AS source_folder
                UNION
                MATCH (folder:ContextItem {id: $folder_id})-[:PARENT_OF]->(attached:ContextItem {is_attached: true})
                WHERE NOT attached.id IN $excluded_ids
                MATCH (attached)-[:PARENT_OF*..]->(article:ContextItem)
                WHERE NOT article.is_folder
                RETURN article.id as id, article.name AS name, article.content AS content, attached.name AS source_folder
            """
            articles_result = session.run(articles_query, folder_id=node['id'], excluded_ids=excluded_attached_ids)

            content_block_items = []
            for record in articles_result:
                file_header = f"File: {record['name']}"
                if record['source_folder']:
                    file_header += f" (from attached folder: {record['source_folder']})"
                content_block_items.append(f"{file_header}\n\n{record['content'] or '> No content.'}")

            if content_block_items:
                all_context_blocks.append({
                    "header": f"Context: {node['name']}",
                    "content": "\n\n".join(content_block_items),
                    "depth": i + 1
                })

        final_context_parts = []
        for block in sorted(all_context_blocks, key=lambda x: x['depth']):
            heading = '#' * block['depth']
            final_context_parts.append(f"{heading} {block['header']}")
            final_context_parts.append(block['content'])

        files_query = """
            OPTIONAL MATCH (:ContextItem {id: $node_id})-[:HAS_FILE]->(f:File)
            RETURN f.filename as filename
        """
        files_result = session.run(files_query, node_id=node_id)
        filenames = [record['filename'] for record in files_result if record['filename'] is not None]

        if filenames:
            final_context_parts.append(f"## Attached Files for {path_nodes[-1]['name']}")
            final_context_parts.append("\n".join([f"- {name}" for name in filenames]))

    full_context = "\n\n".join(final_context_parts)
    return jsonify({'context': full_context})

# --- Admin Routes ---

@app.route('/admin/wipe', methods=['POST'])
@admin_required
def admin_wipe():
    """Wipe the entire database (dangerous!)."""
    driver, error = get_neo4j_driver()
    if error:
        return error

    with driver.session() as session:
        session.run("MATCH (n) DETACH DELETE n")
        # Recreate root
        session.write_transaction(lambda tx: tx.run("""
            MERGE (r:ContextItem {id: 'root', name: 'KnowledgeTree Root'})
            ON CREATE SET r.content = '# Welcome to KnowledgeTree',
                          r.is_folder = true,
                          r.is_attached = false,
                          r.read_only = false
        """))

    return jsonify({'success': True, 'message': 'Database wiped and re-initialized.'})



@app.route('/admin/settings')
@admin_required
def admin_settings():
    """Admin settings page."""
    if g.is_service_call:
        return {'error': 'This endpoint is for users only'}, 403

    config = current_app.config['KT_CONFIG']

    # Get current configuration
    settings = {
        'neo4j_uri': config.get('database', 'neo4j_uri', fallback='Not configured'),
        'codex_url': config.get('codex', 'url', fallback='Not configured'),
        'codex_configured': bool(config.get('codex', 'url', fallback=''))
    }

    return render_template('admin/settings.html', settings=settings, user=g.user)

@app.route('/admin/sync/codex', methods=['POST'])
@admin_required
def admin_sync_codex():
    """Trigger Codex sync."""
    import subprocess
    import sys

    try:
        # Run sync_codex.py as a subprocess
        result = subprocess.run(
            [sys.executable, 'sync_codex.py'],
            capture_output=True,
            text=True,
            timeout=300  # 5 minute timeout
        )

        if result.returncode == 0:
            return jsonify({
                'success': True,
                'message': 'Codex sync completed successfully',
                'output': result.stdout
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Codex sync failed',
                'error': result.stderr
            }), 500

    except subprocess.TimeoutExpired:
        return jsonify({
            'success': False,
            'message': 'Sync timed out after 5 minutes'
        }), 500
    except Exception as e:
        current_app.logger.error(f'Error running codex sync: {str(e)}')
        return jsonify({
            'success': False,
            'message': 'Internal server error'
        }), 500

@app.route('/admin/sync/tickets', methods=['POST'])
@admin_required
def admin_sync_tickets():
    """Trigger ticket sync from Codex."""
    import subprocess
    import sys

    config = current_app.config['KT_CONFIG']
    if not config.get('codex', 'url', fallback=''):
        return jsonify({
            'success': False,
            'message': 'Codex is not configured'
        }), 400

    data = request.json or {}
    overwrite = data.get('overwrite', False)

    try:
        args = [sys.executable, 'sync_tickets.py']
        if overwrite:
            args.append('overwrite')

        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=600  # 10 minute timeout
        )

        if result.returncode == 0:
            return jsonify({
                'success': True,
                'message': 'Ticket sync completed successfully',
                'output': result.stdout
            })
        else:
            return jsonify({
                'success': False,
                'message': 'Ticket sync failed',
                'error': result.stderr
            }), 500

    except subprocess.TimeoutExpired:
        return jsonify({
            'success': False,
            'message': 'Sync timed out after 10 minutes'
        }), 500
    except Exception as e:
        current_app.logger.error(f'Error running ticket sync: {str(e)}')
        return jsonify({
            'success': False,
            'message': 'Internal server error'
        }), 500

@app.route('/admin/sync/status', methods=['GET'])
@admin_required
def admin_sync_status():
    """Get sync status information."""
    driver, error = get_neo4j_driver()
    if error:
        return error

    with driver.session() as session:
        # Count synced items
        stats = session.run("""
            MATCH (n:ContextItem {read_only: true})
            WITH n.id as id
            WHERE id STARTS WITH 'root_Companies'
            RETURN count(id) as company_items
        """).single()

        ticket_stats = session.run("""
            MATCH (n:ContextItem)
            WHERE n.id STARTS WITH 'ticket_'
            RETURN count(n) as ticket_count
        """).single()

        return jsonify({
            'company_items': stats['company_items'] if stats else 0,
            'ticket_count': ticket_stats['ticket_count'] if ticket_stats else 0
        })

@app.route('/admin/export', methods=['GET'])
@admin_required
def admin_export():
    """Export all user-created (non-read-only) data to JSON."""
    driver, error = get_neo4j_driver()
    if error:
        return error

    try:
        with driver.session() as session:
            result = session.run("""
                MATCH p = (:ContextItem {id:'root'})-[:PARENT_OF*..]->(n:ContextItem)
                WHERE ALL(node IN nodes(p)[1..] WHERE node.read_only IS NULL OR node.read_only = false)
                RETURN [node IN nodes(p) | node.name] AS path_parts,
                       n.content AS content,
                       n.is_folder AS is_folder,
                       n.is_attached AS is_attached
            """)

            export_data = []
            for record in result:
                # Skip the root node name from the path
                path = "/".join(record['path_parts'][1:])
                export_data.append({
                    "path": path,
                    "content": record['content'],
                    "is_folder": record['is_folder'],
                    "is_attached": record['is_attached']
                })

            # Save to temporary file
            export_file_path = os.path.join(current_app.instance_path, "knowledgetree_export.json")
            with open(export_file_path, 'w') as f:
                json.dump(export_data, f, indent=2)

            return send_file(export_file_path, as_attachment=True, download_name='knowledgetree_export.json')

    except Exception as e:
        current_app.logger.error(f'Error exporting data: {str(e)}')
        return jsonify({'success': False, 'error': 'Internal server error'}), 500

@app.route('/admin/import', methods=['POST'])
@admin_required
def admin_import():
    """Import data from a previously exported JSON file."""
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400

    file = request.files['file']
    if not file:
        return jsonify({'error': 'No file selected'}), 400

    try:
        import_data = json.load(file)
        # Sort by path so that parent directories are processed before their children
        import_data.sort(key=lambda x: x['path'])

        driver, error = get_neo4j_driver()
        if error:
            return error

        with driver.session() as session:
            with session.begin_transaction() as tx:
                for item in import_data:
                    path_parts = item['path'].split('/')
                    item_name = path_parts[-1]
                    parent_path_parts = path_parts[:-1]

                    # Find the parent node by traversing from the root
                    current_parent_id = 'root'
                    for folder_name in parent_path_parts:
                        result = tx.run(
                            "MATCH (parent:ContextItem {id: $parent_id})-[:PARENT_OF]->(child:ContextItem {name: $name}) RETURN child.id as id",
                            parent_id=current_parent_id, name=folder_name).single()

                        if result:
                            current_parent_id = result['id']
                        else:
                            raise Exception(f"Inconsistent data: parent folder '{folder_name}' not found for item '{item_name}'.")

                    # Create or update the item itself
                    is_folder = item.get('is_folder', False)
                    is_attached = item.get('is_attached', False) and is_folder
                    content = item.get('content', '') if not is_folder else ''

                    # MERGE on the relationship pattern to correctly find or create the node
                    tx.run("""
                        MATCH (parent:ContextItem {id: $parent_id})
                        MERGE (parent)-[r:PARENT_OF]->(item:ContextItem {name: $name})
                        ON CREATE SET item.id = $id,
                                      item.is_folder = $is_folder,
                                      item.is_attached = $is_attached,
                                      item.content = $content,
                                      item.read_only = false
                        ON MATCH SET  item.is_folder = $is_folder,
                                      item.is_attached = $is_attached,
                                      item.content = $content
                    """, parent_id=current_parent_id, name=item_name, id=str(uuid.uuid4()),
                         is_folder=is_folder, is_attached=is_attached, content=content)

        return jsonify({'success': True, 'message': 'Import successful.'})
    except Exception as e:
        current_app.logger.error(f'Error importing data: {str(e)}')
        return jsonify({'success': False, 'error': 'Internal server error'}), 500

@app.route('/health', methods=['GET'])
@limiter.exempt
def health_check():
    """
    Comprehensive health check endpoint.

    Checks:
    - Neo4j database connectivity
    - Disk space
    - Core and Codex service availability

    Returns:
        JSON: Detailed health status with HTTP 200 (healthy) or 503 (unhealthy/degraded)
    """
    # Get Neo4j driver
    neo4j_driver = current_app.config.get('NEO4J_DRIVER')

    # Initialize health checker
    health_checker = HealthChecker(
        service_name='knowledgetree',
        neo4j_driver=neo4j_driver,
        dependencies=[
            ('core', 'http://localhost:5000'),
            ('codex', 'http://localhost:5010')
        ]
    )

    return health_checker.get_health()
