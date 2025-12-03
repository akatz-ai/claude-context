"""Work chain management for session continuity.

Chains track related documents across sessions, enabling:
- Continue from where you left off
- Track parallel work streams
- Link related documents together
"""

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .index import ContextIndex


@dataclass
class Chain:
    """A work chain linking related documents."""
    chain_id: str
    name: Optional[str]
    description: Optional[str]
    root_doc_id: Optional[str]
    latest_doc_id: Optional[str]
    created_at: Optional[str]
    updated_at: Optional[str]
    status: str  # 'active', 'completed', 'abandoned'
    doc_count: int = 0
    root_title: Optional[str] = None
    latest_title: Optional[str] = None


@dataclass
class ChainDocument:
    """A document within a chain."""
    doc_id: str
    filename: str
    title: Optional[str]
    created_at: Optional[str]
    summary: Optional[str]
    parent_doc_id: Optional[str]


class ChainManager:
    """Manages work chains for a context store."""

    def __init__(self, index: "ContextIndex"):
        """Initialize with a context index.

        Args:
            index: The ContextIndex instance for database access
        """
        self.index = index
        self.conn = index.conn

    def create_chain(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None,
        root_doc_id: Optional[str] = None,
    ) -> str:
        """Create a new work chain.

        Args:
            name: Optional human-readable name
            description: Optional description
            root_doc_id: Optional first document in chain

        Returns:
            The new chain ID
        """
        chain_id = str(uuid.uuid4())
        now = datetime.now().isoformat()

        self.conn.execute("""
            INSERT INTO chains (chain_id, name, description, root_doc_id,
                               latest_doc_id, created_at, updated_at, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'active')
        """, (chain_id, name, description, root_doc_id, root_doc_id, now, now))

        # Update document's chain_id if provided
        if root_doc_id:
            self.conn.execute(
                "UPDATE documents SET chain_id = ? WHERE id = ?",
                (chain_id, root_doc_id)
            )

        self.conn.commit()
        return chain_id

    def add_document_to_chain(
        self,
        chain_id: str,
        doc_id: str,
        parent_doc_id: Optional[str] = None,
    ):
        """Add a document to an existing chain.

        Args:
            chain_id: The chain to add to
            doc_id: The document to add
            parent_doc_id: Optional parent document (for lineage)
        """
        now = datetime.now().isoformat()

        # Update document
        self.conn.execute("""
            UPDATE documents
            SET chain_id = ?, parent_doc_id = ?
            WHERE id = ?
        """, (chain_id, parent_doc_id, doc_id))

        # Update chain's latest_doc_id
        self.conn.execute("""
            UPDATE chains
            SET latest_doc_id = ?, updated_at = ?
            WHERE chain_id = ?
        """, (doc_id, now, chain_id))

        # Add doc_ref if parent specified
        if parent_doc_id:
            self.conn.execute("""
                INSERT OR IGNORE INTO doc_refs (source_doc_id, target_doc_id, ref_type)
                VALUES (?, ?, 'continues')
            """, (doc_id, parent_doc_id))

        self.conn.commit()

    def get_chain(self, chain_id: str) -> Optional[Chain]:
        """Get chain details by ID."""
        cursor = self.conn.execute("""
            SELECT c.*,
                   rd.title as root_title,
                   ld.title as latest_title,
                   (SELECT COUNT(*) FROM documents WHERE chain_id = c.chain_id) as doc_count
            FROM chains c
            LEFT JOIN documents rd ON c.root_doc_id = rd.id
            LEFT JOIN documents ld ON c.latest_doc_id = ld.id
            WHERE c.chain_id = ?
        """, (chain_id,))

        row = cursor.fetchone()
        if not row:
            return None

        return Chain(
            chain_id=row['chain_id'],
            name=row['name'],
            description=row['description'],
            root_doc_id=row['root_doc_id'],
            latest_doc_id=row['latest_doc_id'],
            created_at=row['created_at'],
            updated_at=row['updated_at'],
            status=row['status'],
            doc_count=row['doc_count'],
            root_title=row['root_title'],
            latest_title=row['latest_title'],
        )

    def list_chains(
        self,
        status: str = 'active',
        limit: int = 20,
    ) -> List[Chain]:
        """List work chains.

        Args:
            status: Filter by status ('active', 'completed', 'abandoned', 'all')
            limit: Maximum results

        Returns:
            List of Chain objects
        """
        sql = """
            SELECT c.*,
                   rd.title as root_title,
                   ld.title as latest_title,
                   (SELECT COUNT(*) FROM documents WHERE chain_id = c.chain_id) as doc_count
            FROM chains c
            LEFT JOIN documents rd ON c.root_doc_id = rd.id
            LEFT JOIN documents ld ON c.latest_doc_id = ld.id
        """
        params = []

        if status != 'all':
            sql += " WHERE c.status = ?"
            params.append(status)

        sql += " ORDER BY c.updated_at DESC LIMIT ?"
        params.append(limit)

        cursor = self.conn.execute(sql, params)
        chains = []

        for row in cursor:
            chains.append(Chain(
                chain_id=row['chain_id'],
                name=row['name'],
                description=row['description'],
                root_doc_id=row['root_doc_id'],
                latest_doc_id=row['latest_doc_id'],
                created_at=row['created_at'],
                updated_at=row['updated_at'],
                status=row['status'],
                doc_count=row['doc_count'],
                root_title=row['root_title'],
                latest_title=row['latest_title'],
            ))

        return chains

    def get_chain_documents(self, chain_id: str) -> List[ChainDocument]:
        """Get all documents in a chain, ordered by creation time.

        Args:
            chain_id: The chain ID

        Returns:
            List of ChainDocument objects
        """
        cursor = self.conn.execute("""
            SELECT id, filename, title, created_at, summary, parent_doc_id
            FROM documents
            WHERE chain_id = ?
            ORDER BY created_at ASC
        """, (chain_id,))

        docs = []
        for row in cursor:
            docs.append(ChainDocument(
                doc_id=row['id'],
                filename=row['filename'],
                title=row['title'],
                created_at=row['created_at'],
                summary=row['summary'],
                parent_doc_id=row['parent_doc_id'],
            ))

        return docs

    def get_latest_in_chain(
        self,
        chain_id: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> Optional[ChainDocument]:
        """Get the most recent document in a chain.

        Args:
            chain_id: Specific chain ID (or None for any chain)
            tags: Optional filter by tags

        Returns:
            The latest ChainDocument or None
        """
        sql = """
            SELECT d.id, d.filename, d.title, d.created_at, d.summary, d.parent_doc_id
            FROM documents d
            WHERE d.status = 'active'
        """
        params = []

        if chain_id:
            sql += " AND d.chain_id = ?"
            params.append(chain_id)
        else:
            sql += " AND d.chain_id IS NOT NULL"

        if tags:
            placeholders = ','.join('?' * len(tags))
            sql += f"""
                AND d.id IN (
                    SELECT doc_id FROM tags WHERE tag IN ({placeholders})
                )
            """
            params.extend(tags)

        sql += " ORDER BY d.created_at DESC LIMIT 1"

        cursor = self.conn.execute(sql, params)
        row = cursor.fetchone()

        if not row:
            return None

        return ChainDocument(
            doc_id=row['id'],
            filename=row['filename'],
            title=row['title'],
            created_at=row['created_at'],
            summary=row['summary'],
            parent_doc_id=row['parent_doc_id'],
        )

    def update_chain_status(self, chain_id: str, status: str):
        """Update chain status.

        Args:
            chain_id: The chain to update
            status: New status ('active', 'completed', 'abandoned')
        """
        now = datetime.now().isoformat()
        self.conn.execute("""
            UPDATE chains SET status = ?, updated_at = ?
            WHERE chain_id = ?
        """, (status, now, chain_id))
        self.conn.commit()

    def infer_chain_from_content(self, content: str, project_dir: Path) -> Optional[str]:
        """Infer chain membership from document content.

        Looks for references to other documents in the content:
        - @filename references
        - "Continue from" patterns
        - "See also" patterns
        - Explicit chain references

        Args:
            content: Document content
            project_dir: Project directory for resolving paths

        Returns:
            Chain ID if a reference to a chained document is found, else None
        """
        # Pattern 1: @filename references
        at_refs = re.findall(r'@([^\s\]]+\.md)', content)

        # Pattern 2: "Continue from" / "Continues from" patterns
        continue_refs = re.findall(
            r'[Cc]ontinues?\s+from[:\s]+["\']?([^"\')\s]+\.md)',
            content
        )

        # Pattern 3: "See also" / "Related" patterns
        see_also_refs = re.findall(
            r'(?:[Ss]ee\s+also|[Rr]elated)[:\s]+["\']?([^"\')\s]+\.md)',
            content
        )

        # Combine all references
        all_refs = set(at_refs + continue_refs + see_also_refs)

        # Look up each reference
        for ref in all_refs:
            # Try to find this document in the index
            cursor = self.conn.execute("""
                SELECT chain_id FROM documents
                WHERE filename LIKE ? AND chain_id IS NOT NULL
                LIMIT 1
            """, (f'%{ref}',))

            row = cursor.fetchone()
            if row and row['chain_id']:
                return row['chain_id']

        return None

    def auto_chain_document(
        self,
        doc_id: str,
        content: str,
        project_dir: Path,
    ) -> Optional[str]:
        """Automatically assign a document to a chain based on its content.

        Args:
            doc_id: Document ID to assign
            content: Document content for inference
            project_dir: Project directory

        Returns:
            Chain ID if assigned, None otherwise
        """
        # Try to infer chain from content
        chain_id = self.infer_chain_from_content(content, project_dir)

        if chain_id:
            # Find the latest doc in that chain to set as parent
            latest = self.get_latest_in_chain(chain_id)
            parent_id = latest.doc_id if latest else None

            self.add_document_to_chain(chain_id, doc_id, parent_id)
            return chain_id

        return None

    def get_chain_for_document(self, doc_id: str) -> Optional[Chain]:
        """Get the chain a document belongs to.

        Args:
            doc_id: Document ID

        Returns:
            Chain if document is in a chain, else None
        """
        cursor = self.conn.execute(
            "SELECT chain_id FROM documents WHERE id = ?",
            (doc_id,)
        )
        row = cursor.fetchone()

        if row and row['chain_id']:
            return self.get_chain(row['chain_id'])

        return None


def generate_chain_name(title: Optional[str], doc_type: str) -> str:
    """Generate a chain name from the first document.

    Args:
        title: Document title
        doc_type: Document type

    Returns:
        Generated chain name
    """
    if title:
        # Clean up title for chain name
        name = title[:50]
        # Remove common prefixes
        for prefix in ['Session:', 'Plan:', 'Design:', 'Bug:']:
            if name.startswith(prefix):
                name = name[len(prefix):].strip()
        return name

    # Fallback
    date_str = datetime.now().strftime('%Y-%m-%d')
    return f"{doc_type}-chain-{date_str}"
