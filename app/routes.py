from datetime import datetime
import json
import os
import uuid
from urllib.parse import unquote, quote
from flask import render_template, request, jsonify, send_from_directory, send_file, redirect, g, current_app, url_for
from app import app
from app.auth import token_required, admin_required
from app.service_client import call_service
import markdown

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

    driver, error = get_neo4j_driver()
    if error:
        return error

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
    driver, error = get_neo4j_driver()
    if error:
        return error

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
    driver, error = get_neo4j_driver()
    if error:
        return error

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
    driver, error = get_neo4j_driver()
    if error:
        return error

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
    if file:
        filename = file.filename
        file_id = str(uuid.uuid4())
        file.save(os.path.join(current_app.config['UPLOAD_FOLDER'], filename))

        driver, error = get_neo4j_driver()
        if error:
            return error

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
        'freshservice_domain': config.get('freshservice', 'domain', fallback='Not configured'),
        'freshservice_configured': bool(config.get('freshservice', 'domain', fallback=''))
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
        return jsonify({
            'success': False,
            'message': f'Error running sync: {str(e)}'
        }), 500

@app.route('/admin/sync/tickets', methods=['POST'])
@admin_required
def admin_sync_tickets():
    """Trigger Freshservice ticket sync."""
    import subprocess
    import sys

    config = current_app.config['KT_CONFIG']
    if not config.get('freshservice', 'domain', fallback=''):
        return jsonify({
            'success': False,
            'message': 'Freshservice is not configured'
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
        return jsonify({
            'success': False,
            'message': f'Error running sync: {str(e)}'
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
        return jsonify({'success': False, 'error': str(e)}), 500

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
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint for monitoring"""
    return {
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat()
    }
