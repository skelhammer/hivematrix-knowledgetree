import os
import uuid
from urllib.parse import unquote, quote
from flask import render_template, request, jsonify, send_from_directory, g, current_app, url_for
from app import app
from app.auth import token_required, admin_required
from app.service_client import call_service
import markdown

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
    return render_template('redirect.html', target_url=url_for('browse', path=''))

@app.route('/browse/', defaults={'path': ''})
@app.route('/browse/<path:path>')
@token_required
def browse(path):
    """Browse the knowledge tree."""
    if g.is_service_call:
        return {'error': 'This endpoint is for users only'}, 403

    driver = current_app.config['NEO4J_DRIVER']
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

    return render_template('index.html',
                           items=items,
                           breadcrumb_names=breadcrumb_names,
                           current_path=path,
                           current_node_id=node_id,
                           parent_path=parent_path,
                           user=g.user)

@app.route('/view/<node_id>')
@token_required
def view_node(node_id):
    """View a specific node."""
    if g.is_service_call:
        return {'error': 'This endpoint is for users only'}, 403

    driver = current_app.config['NEO4J_DRIVER']

    with driver.session() as session:
        path_query = """
            MATCH p = shortestPath((:ContextItem {id: 'root'})-[:PARENT_OF*..]->(:ContextItem {id: $node_id}))
            RETURN [n IN nodes(p) | n.name] AS names
        """
        result = session.run(path_query, node_id=node_id).single()

        parent_path = ''
        if result and result['names']:
            parent_path_parts = result['names'][1:-1]
            parent_path = "/".join([quote(name) for name in parent_path_parts])

    return render_template('view.html', node_id=node_id, parent_path=parent_path, user=g.user)

@app.route('/uploads/<filename>')
@token_required
def uploaded_file(filename):
    """Serve uploaded files."""
    return send_from_directory(current_app.config['UPLOAD_FOLDER'], filename)

# --- API Endpoints ---

@app.route('/api/search', methods=['GET'])
@token_required
def search_nodes():
    """Search for nodes in the tree."""
    query = request.args.get('query', '')
    start_node_id = request.args.get('start_node_id', 'root')

    if not query:
        return jsonify([])

    driver = current_app.config['NEO4J_DRIVER']

    with driver.session() as session:
        result = session.run("""
            MATCH (startNode:ContextItem {id: $start_node_id})-[:PARENT_OF*0..]->(node)
            WHERE toLower(node.name) CONTAINS toLower($query) OR toLower(node.content) CONTAINS toLower($query)
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
            folder_path = "/".join([quote(name) for name in path_list])
            record_dict['folder_path'] = folder_path
            processed_results.append(record_dict)

        return jsonify(processed_results)

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
    driver = current_app.config['NEO4J_DRIVER']

    with driver.session() as session:
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
    driver = current_app.config['NEO4J_DRIVER']

    with driver.session() as session:
        result = session.run("""
            MATCH (n:ContextItem {id: $node_id})
            OPTIONAL MATCH (n)-[:HAS_FILE]->(f:File)
            RETURN n.id AS id, n.name AS name, n.content AS content, n.is_folder AS is_folder,
                   n.is_attached as is_attached, n.read_only as read_only,
                   collect({id: f.id, filename: f.filename}) AS files
        """, node_id=node_id).single()

        if result:
            data = dict(result)
            content = data.get('content') or ''
            data['content_html'] = markdown.markdown(content, extensions=['fenced_code', 'tables'])
            data['files'] = [f for f in data.get('files', []) if f['id'] is not None]
            return jsonify(data)
        else:
            return jsonify({'error': 'Node not found'}), 404

@app.route('/api/node/<node_id>', methods=['PUT'])
@token_required
def update_node(node_id):
    """Update node details."""
    data = request.json
    driver = current_app.config['NEO4J_DRIVER']

    with driver.session() as session:
        if 'content' in data:
            session.run("MATCH (n:ContextItem {id: $id}) SET n.content = $content",
                        id=node_id, content=data['content'])
        if 'name' in data:
            session.run("MATCH (n:ContextItem {id: $id}) SET n.name = $name",
                        id=node_id, name=data['name'])

    return jsonify({'success': True})

@app.route('/api/node/<node_id>', methods=['DELETE'])
@token_required
def delete_node(node_id):
    """Delete a node and its children."""
    driver = current_app.config['NEO4J_DRIVER']

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
    if file:
        filename = file.filename
        file_id = str(uuid.uuid4())
        file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))

        driver = current_app.config['NEO4J_DRIVER']
        with driver.session() as session:
            session.run("""
                MATCH (n:ContextItem {id: $node_id})
                CREATE (f:File {id: $file_id, filename: $filename})
                CREATE (n)-[:HAS_FILE]->(f)
            """, node_id=node_id, file_id=file_id, filename=filename)

        return jsonify({'success': True, 'filename': filename})

    return jsonify({'error': 'File upload failed'}), 500

@app.route('/api/context/tree/<node_id>', methods=['GET'])
@token_required
def get_context_tree(node_id):
    """Get the context tree for a node (attached folders)."""
    driver = current_app.config['NEO4J_DRIVER']

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

    driver = current_app.config['NEO4J_DRIVER']
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
    driver = current_app.config['NEO4J_DRIVER']

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
