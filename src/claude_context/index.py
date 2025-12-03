"""SQLite index management for context documents with FTS5 search."""

import re
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any


@dataclass
class SearchResult:
    """A search result with document metadata and snippet."""
    id: str
    filename: str
    title: Optional[str]
    doc_type: Optional[str]
    snippet: str
    score: float
    created_at: Optional[datetime]
    tags: List[str]


@dataclass
class DocumentInfo:
    """Document metadata from index."""
    id: str
    filename: str
    title: Optional[str]
    doc_type: Optional[str]
    scope: str
    branch: Optional[str]
    status: str
    created_at: Optional[datetime]
    updated_at: Optional[datetime]
    tags: List[str]
    summary: Optional[str]


# Type inference patterns (order matters - first match wins)
TYPE_PATTERNS = {
    'session': [r'/notes/', r'SESSION', r'session[-_]', r'_session\.'],
    'plan': [r'/plans/', r'PLAN', r'[-_]plan\.'],
    'decision': [r'/decisions/', r'DECISION', r'[-_]decision\.'],
    'bug': [r'/bugs/', r'BUG', r'[-_]bug\.'],
    'knowledge': [r'/knowledge/', r'[-_]guide\.', r'[-_]reference\.'],
    'design': [r'/designs/', r'DESIGN', r'[-_]design\.'],
    'reference': [r'/api/', r'[-_]ref\.', r'quick[-_]ref[-_]'],
    'script': [r'/scripts/', r'\.sh$', r'\.py$'],
}


def infer_type_from_path(path: str) -> str:
    """Infer document type from file path."""
    for doc_type, patterns in TYPE_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, path, re.IGNORECASE):
                return doc_type
    return 'note'


def infer_scope_from_path(path: str) -> tuple[str, Optional[str]]:
    """Infer scope (shared/branch) and branch name from path."""
    if path.startswith('shared/') or '/shared/' in path:
        return 'shared', None

    match = re.search(r'branches/([^/]+)/', path)
    if match:
        return 'branch', match.group(1)

    return 'shared', None


def infer_category_from_path(path: str) -> Optional[str]:
    """Extract category (first directory) from path."""
    parts = Path(path).parts
    # Skip 'shared' or 'branches/<name>'
    if parts[0] == 'shared' and len(parts) > 1:
        return parts[1]
    elif parts[0] == 'branches' and len(parts) > 2:
        return parts[2]
    elif len(parts) > 0:
        return parts[0]
    return None


def extract_title(content: str) -> Optional[str]:
    """Extract title from markdown content (first # heading)."""
    for line in content.split('\n')[:20]:  # Check first 20 lines
        line = line.strip()
        if line.startswith('# '):
            return line[2:].strip()
    return None


def extract_summary(content: str) -> Optional[str]:
    """Extract a one-line summary from content."""
    # Try to find a ## Summary section
    match = re.search(r'^##\s*Summary\s*\n+(.+?)(?:\n\n|\n##|\Z)', content, re.MULTILINE | re.DOTALL)
    if match:
        summary = match.group(1).strip()
        # Take first line/sentence
        first_line = summary.split('\n')[0].strip()
        if first_line:
            return first_line[:200]

    # Fallback: first non-heading paragraph
    lines = content.split('\n')
    for line in lines:
        line = line.strip()
        if line and not line.startswith('#') and not line.startswith('*') and not line.startswith('-'):
            return line[:200]

    return None


def extract_tags_from_content(content: str, filename: str) -> List[str]:
    """Extract potential tags from content and filename."""
    tags = set()

    # From filename (split on - and _)
    basename = Path(filename).stem
    for part in re.split(r'[-_]', basename):
        if len(part) > 2 and part.lower() not in ('the', 'and', 'for'):
            tags.add(part.lower())

    # From frontmatter tags field
    match = re.search(r'^---\s*\n.*?^tags:\s*\[([^\]]+)\]', content, re.MULTILINE | re.DOTALL)
    if match:
        for tag in match.group(1).split(','):
            tag = tag.strip().strip('"\'')
            if tag:
                tags.add(tag.lower())

    return list(tags)[:10]  # Limit to 10 tags


class ContextIndex:
    """SQLite-based index for context documents with full-text search."""

    def __init__(self, db_path: Path):
        """Initialize the index.

        Args:
            db_path: Path to the SQLite database file
        """
        self.db_path = Path(db_path)
        self.conn = sqlite3.connect(str(self.db_path), timeout=30.0)

        # Configure for performance
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute("PRAGMA busy_timeout=30000")
        self.conn.execute("PRAGMA foreign_keys=ON")

        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        """Initialize database schema from SQL file."""
        schema_path = Path(__file__).parent / 'schema' / 'v2.sql'
        if schema_path.exists():
            schema_sql = schema_path.read_text()
            self.conn.executescript(schema_sql)
            self.conn.commit()

    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()

    def get_schema_version(self) -> Optional[str]:
        """Get the current schema version."""
        try:
            cursor = self.conn.execute(
                "SELECT value FROM schema_info WHERE key = 'version'"
            )
            row = cursor.fetchone()
            return row['value'] if row else None
        except sqlite3.OperationalError:
            return None

    def index_document(
        self,
        filename: str,
        content: str,
        project_dir: Path,
        doc_id: Optional[str] = None,
    ) -> str:
        """Index or re-index a document.

        Args:
            filename: Relative path from context root
            content: Full markdown content
            project_dir: Root directory of the context store
            doc_id: Optional existing document ID (for updates)

        Returns:
            Document ID
        """
        file_path = project_dir / filename

        # Generate or use provided ID
        if not doc_id:
            # Check if document already exists by filename
            cursor = self.conn.execute(
                "SELECT id FROM documents WHERE filename = ?",
                (filename,)
            )
            row = cursor.fetchone()
            doc_id = row['id'] if row else str(uuid.uuid4())

        # Extract metadata
        title = extract_title(content)
        doc_type = infer_type_from_path(filename)
        scope, branch = infer_scope_from_path(filename)
        category = infer_category_from_path(filename)
        summary = extract_summary(content)
        tags = extract_tags_from_content(content, filename)

        # Get file times
        now = datetime.now().isoformat()
        file_mtime = file_path.stat().st_mtime if file_path.exists() else None

        # Check if this is an update
        cursor = self.conn.execute(
            "SELECT created_at FROM documents WHERE id = ?",
            (doc_id,)
        )
        existing = cursor.fetchone()
        created_at = existing['created_at'] if existing else now

        # Upsert document
        self.conn.execute("""
            INSERT OR REPLACE INTO documents (
                id, filename, title, doc_type, original_category,
                scope, branch, status, created_at, updated_at, indexed_at,
                file_mtime, summary, full_content
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?)
        """, (
            doc_id, filename, title, doc_type, category,
            scope, branch, created_at, now, now,
            file_mtime, summary, content
        ))

        # Update tags (clear and re-add)
        self.conn.execute("DELETE FROM tags WHERE doc_id = ?", (doc_id,))
        for tag in tags:
            self.conn.execute(
                "INSERT OR IGNORE INTO tags (doc_id, tag, auto_generated) VALUES (?, ?, TRUE)",
                (doc_id, tag)
            )

        self.conn.commit()
        return doc_id

    def remove_document(self, filename: str):
        """Remove a document from the index."""
        self.conn.execute("DELETE FROM documents WHERE filename = ?", (filename,))
        self.conn.commit()

    def get_document_by_filename(self, filename: str) -> Optional[Dict[str, Any]]:
        """Get document metadata by filename."""
        cursor = self.conn.execute(
            "SELECT * FROM documents WHERE filename = ?",
            (filename,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_document_by_id(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """Get document metadata by ID."""
        cursor = self.conn.execute(
            "SELECT * FROM documents WHERE id = ?",
            (doc_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def get_document_by_filename_or_id(self, identifier: str) -> Optional[Dict[str, Any]]:
        """Get document by filename or ID (tries both).

        Args:
            identifier: Either a document ID (UUID) or filename

        Returns:
            Document dict or None
        """
        # Try as ID first (UUIDs have specific format)
        if len(identifier) == 36 and '-' in identifier:
            doc = self.get_document_by_id(identifier)
            if doc:
                return doc

        # Try as filename
        doc = self.get_document_by_filename(identifier)
        if doc:
            return doc

        # Try partial ID match
        cursor = self.conn.execute(
            "SELECT * FROM documents WHERE id LIKE ?",
            (f"{identifier}%",)
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    def ensure_fresh(self, project_dir: Path):
        """Check for stale documents and reindex as needed.

        Args:
            project_dir: Root directory of the context store
        """
        # Get all indexed documents
        cursor = self.conn.execute(
            "SELECT filename, file_mtime FROM documents"
        )
        indexed_docs = {row['filename']: row['file_mtime'] for row in cursor}

        # Scan for all files
        current_files = set()
        # Files to skip (internal files)
        skip_names = {'.gitkeep', '.ctx-meta', 'index.db', 'index.db-wal', 'index.db-shm', 'config.yaml'}

        for md_file in project_dir.rglob('*'):
            if md_file.is_file() and md_file.name not in skip_names:
                rel_path = str(md_file.relative_to(project_dir))

                # Skip hidden files and directories (check relative path only)
                rel_parts = Path(rel_path).parts
                if any(part.startswith('.') for part in rel_parts):
                    continue
                current_files.add(rel_path)

                # Check if needs reindexing
                current_mtime = md_file.stat().st_mtime
                indexed_mtime = indexed_docs.get(rel_path)

                if indexed_mtime is None or current_mtime > indexed_mtime:
                    # New or modified file
                    content = md_file.read_text(errors='replace')
                    self.index_document(rel_path, content, project_dir)

        # Remove deleted files from index
        for filename in indexed_docs:
            if filename not in current_files:
                self.remove_document(filename)

    def search(
        self,
        query: str,
        doc_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        scope: Optional[str] = None,
        branch: Optional[str] = None,
        status: str = 'active',
        since: Optional[str] = None,
        limit: int = 20,
    ) -> List[SearchResult]:
        """Full-text search with filters.

        Args:
            query: Search query (FTS5 syntax supported)
            doc_type: Filter by document type
            tags: Filter by tags (any match)
            scope: Filter by scope ('shared' or 'branch')
            branch: Filter by branch name
            status: Filter by status (default 'active', use 'all' for all)
            since: Filter by created_at date (ISO format)
            limit: Maximum results

        Returns:
            List of SearchResult objects
        """
        # Prepare query for FTS5
        if query:
            # Add wildcard for simple queries
            if not any(op in query for op in [' AND ', ' OR ', ' NOT ', '"', '*']):
                terms = query.split()
                fts_query = ' '.join(f'{term}*' for term in terms)
            else:
                fts_query = query
        else:
            fts_query = None

        # Build SQL query
        params = []

        if fts_query:
            sql = """
                SELECT
                    d.id, d.filename, d.title, d.doc_type, d.created_at,
                    snippet(doc_fts, 1, '**', '**', '...', 32) as snippet,
                    rank
                FROM doc_fts
                JOIN documents d ON doc_fts.rowid = d.rowid
                WHERE doc_fts MATCH ?
            """
            params.append(fts_query)
        else:
            sql = """
                SELECT
                    d.id, d.filename, d.title, d.doc_type, d.created_at,
                    SUBSTR(d.full_content, 1, 100) || '...' as snippet,
                    0 as rank
                FROM documents d
                WHERE 1=1
            """

        # Add filters
        if status != 'all':
            sql += " AND d.status = ?"
            params.append(status)

        if doc_type:
            sql += " AND d.doc_type = ?"
            params.append(doc_type)

        if scope:
            sql += " AND d.scope = ?"
            params.append(scope)

        if branch:
            sql += " AND d.branch = ?"
            params.append(branch)

        if since:
            sql += " AND d.created_at >= ?"
            params.append(since)

        if tags:
            placeholders = ','.join('?' * len(tags))
            sql += f"""
                AND d.id IN (
                    SELECT doc_id FROM tags WHERE tag IN ({placeholders})
                )
            """
            params.extend(tags)

        # Order and limit
        if fts_query:
            sql += " ORDER BY rank LIMIT ?"
        else:
            sql += " ORDER BY d.created_at DESC LIMIT ?"
        params.append(limit)

        # Execute
        cursor = self.conn.execute(sql, params)
        results = []

        for row in cursor:
            # Get tags for this document
            tag_cursor = self.conn.execute(
                "SELECT tag FROM tags WHERE doc_id = ?",
                (row['id'],)
            )
            doc_tags = [r['tag'] for r in tag_cursor]

            results.append(SearchResult(
                id=row['id'],
                filename=row['filename'],
                title=row['title'],
                doc_type=row['doc_type'],
                snippet=row['snippet'] or '',
                score=abs(row['rank']) if row['rank'] else 0,
                created_at=row['created_at'],
                tags=doc_tags
            ))

        return results

    def list_documents(
        self,
        doc_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        scope: Optional[str] = None,
        branch: Optional[str] = None,
        status: str = 'active',
        since: Optional[str] = None,
        limit: int = 100,
    ) -> List[DocumentInfo]:
        """List documents with filters.

        Args:
            doc_type: Filter by document type
            tags: Filter by tags (any match)
            scope: Filter by scope ('shared' or 'branch')
            branch: Filter by branch name
            status: Filter by status (default 'active', use 'all' for all)
            since: Filter by created_at date (ISO format)
            limit: Maximum results

        Returns:
            List of DocumentInfo objects
        """
        sql = """
            SELECT d.id, d.filename, d.title, d.doc_type, d.scope, d.branch,
                   d.status, d.created_at, d.updated_at, d.summary
            FROM documents d
            WHERE 1=1
        """
        params = []

        if status != 'all':
            sql += " AND d.status = ?"
            params.append(status)

        if doc_type:
            sql += " AND d.doc_type = ?"
            params.append(doc_type)

        if scope:
            sql += " AND d.scope = ?"
            params.append(scope)

        if branch:
            sql += " AND d.branch = ?"
            params.append(branch)

        if since:
            sql += " AND d.created_at >= ?"
            params.append(since)

        if tags:
            placeholders = ','.join('?' * len(tags))
            sql += f"""
                AND d.id IN (
                    SELECT doc_id FROM tags WHERE tag IN ({placeholders})
                )
            """
            params.extend(tags)

        sql += " ORDER BY d.created_at DESC LIMIT ?"
        params.append(limit)

        cursor = self.conn.execute(sql, params)
        results = []

        for row in cursor:
            # Get tags
            tag_cursor = self.conn.execute(
                "SELECT tag FROM tags WHERE doc_id = ?",
                (row['id'],)
            )
            doc_tags = [r['tag'] for r in tag_cursor]

            results.append(DocumentInfo(
                id=row['id'],
                filename=row['filename'],
                title=row['title'],
                doc_type=row['doc_type'],
                scope=row['scope'],
                branch=row['branch'],
                status=row['status'],
                created_at=row['created_at'],
                updated_at=row['updated_at'],
                tags=doc_tags,
                summary=row['summary']
            ))

        return results

    def get_stats(self) -> Dict[str, Any]:
        """Get index statistics."""
        stats = {}

        # Total documents
        cursor = self.conn.execute("SELECT COUNT(*) as count FROM documents")
        stats['total_documents'] = cursor.fetchone()['count']

        # By type
        cursor = self.conn.execute("""
            SELECT doc_type, COUNT(*) as count
            FROM documents
            WHERE status = 'active'
            GROUP BY doc_type
        """)
        stats['by_type'] = {row['doc_type']: row['count'] for row in cursor}

        # By scope
        cursor = self.conn.execute("""
            SELECT scope, COUNT(*) as count
            FROM documents
            WHERE status = 'active'
            GROUP BY scope
        """)
        stats['by_scope'] = {row['scope']: row['count'] for row in cursor}

        # Total tags
        cursor = self.conn.execute("SELECT COUNT(DISTINCT tag) as count FROM tags")
        stats['total_tags'] = cursor.fetchone()['count']

        # Schema version
        stats['schema_version'] = self.get_schema_version()

        return stats

    def get_all_tags(self) -> List[tuple[str, int]]:
        """Get all tags with document counts."""
        cursor = self.conn.execute("""
            SELECT tag, COUNT(*) as count
            FROM tags
            GROUP BY tag
            ORDER BY count DESC, tag
        """)
        return [(row['tag'], row['count']) for row in cursor]

    def add_tag(self, doc_id: str, tag: str, auto_generated: bool = False):
        """Add a tag to a document."""
        self.conn.execute(
            "INSERT OR IGNORE INTO tags (doc_id, tag, auto_generated) VALUES (?, ?, ?)",
            (doc_id, tag.lower(), auto_generated)
        )
        self.conn.commit()

    def remove_tag(self, doc_id: str, tag: str):
        """Remove a tag from a document."""
        self.conn.execute(
            "DELETE FROM tags WHERE doc_id = ? AND tag = ?",
            (doc_id, tag.lower())
        )
        self.conn.commit()
