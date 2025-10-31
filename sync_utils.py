"""
Shared utilities for sync scripts.

Provides common functionality for syncing data from external sources into KnowledgeTree.
"""

def ensure_node(session, parent_id, name, is_folder=True, is_attached=False, content='', read_only=True):
    """
    Creates or updates a node in Neo4j.

    This function intelligently handles node creation/updates by:
    1. First checking if a node with the same name already exists under the parent
    2. If found, reuses that node's ID (preserving manually created nodes)
    3. If not found, generates a new deterministic ID based on the path

    This prevents duplicate folders when syncing, especially important when:
    - Nodes were manually created via the UI (which uses UUIDs)
    - Nodes were created by previous sync runs

    Args:
        session: Neo4j session
        parent_id: ID of the parent node
        name: Name of the node to create/update
        is_folder: Whether this is a folder (True) or a file (False)
        is_attached: Whether this folder is attached (for special folders)
        content: Content for files (markdown, etc.)
        read_only: Whether the node should be read-only

    Returns:
        str: The ID of the created or updated node
    """
    # First, try to find an existing node with the same name under this parent
    existing = session.run("""
        MATCH (parent:ContextItem {id: $parent_id})-[:PARENT_OF]->(existing:ContextItem)
        WHERE existing.name = $name
        RETURN existing.id as id
    """, parent_id=parent_id, name=name).single()

    if existing:
        # Reuse the existing node's ID
        node_id = existing['id']
    else:
        # Generate a new deterministic ID based on the path
        node_id = f"{parent_id}_{name.replace(' ', '_').replace('/', '_')}"

    # Now MERGE using the found or generated ID
    result = session.run("""
        MATCH (parent:ContextItem {id: $parent_id})
        MERGE (parent)-[r:PARENT_OF]->(node:ContextItem {id: $node_id})
        ON CREATE SET node.name = $name,
                      node.is_folder = $is_folder,
                      node.is_attached = $is_attached,
                      node.content = $content,
                      node.read_only = $read_only
        ON MATCH SET  node.name = $name,
                      node.is_folder = $is_folder,
                      node.is_attached = $is_attached,
                      node.content = $content,
                      node.read_only = $read_only
        RETURN node.id as id
    """, parent_id=parent_id, node_id=node_id, name=name, is_folder=is_folder,
         is_attached=is_attached, content=content, read_only=read_only).single()

    return result['id']
