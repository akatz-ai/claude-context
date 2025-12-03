"""Git integration for linking code commits with context documents.

This module provides:
- ctx:// URI scheme for referencing context documents
- Bidirectional linking between commits and documents
- Tools to query commit<->document relationships
"""

import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .index import ContextIndex


@dataclass
class CtxUri:
    """Parsed ctx:// URI."""
    project_id: str
    doc_id: Optional[str] = None
    filename: Optional[str] = None

    def __str__(self) -> str:
        """Convert back to URI string."""
        if self.doc_id:
            return f"ctx://{self.project_id}/{self.doc_id}"
        elif self.filename:
            return f"ctx://{self.project_id}/file/{self.filename}"
        return f"ctx://{self.project_id}"


@dataclass
class CommitInfo:
    """Information about a git commit."""
    hash: str
    short_hash: str
    message: str
    author: str
    date: datetime
    repo_path: str


@dataclass
class CommitRef:
    """A reference between a document and a commit."""
    doc_id: str
    commit_hash: str
    repo_path: str
    ref_type: str  # 'informed_by', 'implements', 'documents'
    commit_message: Optional[str]
    created_at: Optional[str]
    # Joined document info
    doc_filename: Optional[str] = None
    doc_title: Optional[str] = None


def parse_ctx_uri(uri: str) -> Optional[CtxUri]:
    """Parse a ctx:// URI string.

    Supported formats:
    - ctx://<project-id>/<doc-id>
    - ctx://<project-id>/file/<filename>

    Args:
        uri: The URI string to parse

    Returns:
        CtxUri object or None if invalid
    """
    pattern = r'^ctx://([a-f0-9]+)(?:/(.+))?$'
    match = re.match(pattern, uri)
    if not match:
        return None

    project_id = match.group(1)
    remainder = match.group(2)

    if not remainder:
        return CtxUri(project_id=project_id)

    # Check for file path reference
    if remainder.startswith('file/'):
        filename = remainder[5:]  # Remove 'file/' prefix
        return CtxUri(project_id=project_id, filename=filename)

    # Assume it's a doc ID
    return CtxUri(project_id=project_id, doc_id=remainder)


def create_ctx_uri(project_id: str, doc_id: Optional[str] = None, filename: Optional[str] = None) -> str:
    """Create a ctx:// URI string.

    Args:
        project_id: The project hash
        doc_id: Optional document ID
        filename: Optional filename (alternative to doc_id)

    Returns:
        ctx:// URI string
    """
    uri = CtxUri(project_id=project_id, doc_id=doc_id, filename=filename)
    return str(uri)


class GitIntegration:
    """Handles git integration for commit<->context linking."""

    def __init__(self, index: "ContextIndex", project_id: str, project_dir: Path, repo_path: Path):
        """Initialize git integration.

        Args:
            index: The context index
            project_id: Project identifier hash
            project_dir: Path to context storage directory
            repo_path: Path to the code repository
        """
        self.index = index
        self.project_id = project_id
        self.project_dir = project_dir
        self.repo_path = repo_path

    def get_recent_commits(self, count: int = 10) -> List[CommitInfo]:
        """Get recent commits from the code repository.

        Args:
            count: Number of commits to retrieve

        Returns:
            List of CommitInfo objects
        """
        try:
            result = subprocess.run(
                ['git', 'log', f'-{count}', '--format=%H|%h|%s|%an|%aI'],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=True
            )

            commits = []
            for line in result.stdout.strip().split('\n'):
                if not line:
                    continue
                parts = line.split('|', 4)
                if len(parts) >= 5:
                    commits.append(CommitInfo(
                        hash=parts[0],
                        short_hash=parts[1],
                        message=parts[2],
                        author=parts[3],
                        date=datetime.fromisoformat(parts[4]),
                        repo_path=str(self.repo_path)
                    ))
            return commits
        except subprocess.CalledProcessError:
            return []

    def get_commit_info(self, commit_hash: str) -> Optional[CommitInfo]:
        """Get information about a specific commit.

        Args:
            commit_hash: Full or short commit hash

        Returns:
            CommitInfo or None if not found
        """
        try:
            result = subprocess.run(
                ['git', 'log', '-1', '--format=%H|%h|%s|%an|%aI', commit_hash],
                cwd=self.repo_path,
                capture_output=True,
                text=True,
                check=True
            )

            line = result.stdout.strip()
            if not line:
                return None

            parts = line.split('|', 4)
            if len(parts) >= 5:
                return CommitInfo(
                    hash=parts[0],
                    short_hash=parts[1],
                    message=parts[2],
                    author=parts[3],
                    date=datetime.fromisoformat(parts[4]),
                    repo_path=str(self.repo_path)
                )
            return None
        except subprocess.CalledProcessError:
            return None

    def link_commit_to_doc(
        self,
        doc_id: str,
        commit_hash: str,
        ref_type: str = 'documents',
        commit_message: Optional[str] = None
    ):
        """Link a commit to a context document.

        Args:
            doc_id: Document ID
            commit_hash: Git commit hash
            ref_type: Type of reference ('informed_by', 'implements', 'documents')
            commit_message: Optional commit message (first line)
        """
        # Get commit message if not provided
        if not commit_message:
            commit_info = self.get_commit_info(commit_hash)
            if commit_info:
                commit_message = commit_info.message

        self.index.conn.execute("""
            INSERT OR REPLACE INTO commit_refs (doc_id, commit_hash, repo_path, ref_type, commit_message)
            VALUES (?, ?, ?, ?, ?)
        """, (doc_id, commit_hash, str(self.repo_path), ref_type, commit_message))
        self.index.conn.commit()

    def get_commits_for_doc(self, doc_id: str) -> List[CommitRef]:
        """Get all commits linked to a document.

        Args:
            doc_id: Document ID

        Returns:
            List of CommitRef objects
        """
        cursor = self.index.conn.execute("""
            SELECT cr.*, d.filename as doc_filename, d.title as doc_title
            FROM commit_refs cr
            JOIN documents d ON cr.doc_id = d.id
            WHERE cr.doc_id = ?
            ORDER BY cr.created_at DESC
        """, (doc_id,))

        return [CommitRef(
            doc_id=row['doc_id'],
            commit_hash=row['commit_hash'],
            repo_path=row['repo_path'],
            ref_type=row['ref_type'],
            commit_message=row['commit_message'],
            created_at=row['created_at'],
            doc_filename=row['doc_filename'],
            doc_title=row['doc_title']
        ) for row in cursor]

    def get_docs_for_commit(self, commit_hash: str) -> List[CommitRef]:
        """Get all documents linked to a commit.

        Args:
            commit_hash: Git commit hash (full or prefix)

        Returns:
            List of CommitRef objects
        """
        # Support partial commit hash matching
        cursor = self.index.conn.execute("""
            SELECT cr.*, d.filename as doc_filename, d.title as doc_title
            FROM commit_refs cr
            JOIN documents d ON cr.doc_id = d.id
            WHERE cr.commit_hash LIKE ?
            ORDER BY cr.created_at DESC
        """, (f"{commit_hash}%",))

        return [CommitRef(
            doc_id=row['doc_id'],
            commit_hash=row['commit_hash'],
            repo_path=row['repo_path'],
            ref_type=row['ref_type'],
            commit_message=row['commit_message'],
            created_at=row['created_at'],
            doc_filename=row['doc_filename'],
            doc_title=row['doc_title']
        ) for row in cursor]

    def get_all_commit_refs(self, limit: int = 50) -> List[CommitRef]:
        """Get all commit references.

        Args:
            limit: Maximum number of results

        Returns:
            List of CommitRef objects
        """
        cursor = self.index.conn.execute("""
            SELECT cr.*, d.filename as doc_filename, d.title as doc_title
            FROM commit_refs cr
            JOIN documents d ON cr.doc_id = d.id
            ORDER BY cr.created_at DESC
            LIMIT ?
        """, (limit,))

        return [CommitRef(
            doc_id=row['doc_id'],
            commit_hash=row['commit_hash'],
            repo_path=row['repo_path'],
            ref_type=row['ref_type'],
            commit_message=row['commit_message'],
            created_at=row['created_at'],
            doc_filename=row['doc_filename'],
            doc_title=row['doc_title']
        ) for row in cursor]

    def generate_commit_message_footer(self, doc_ids: List[str]) -> str:
        """Generate a commit message footer with context references.

        Args:
            doc_ids: List of document IDs to reference

        Returns:
            Footer text for commit message
        """
        if not doc_ids:
            return ""

        lines = ["\n\nContext:"]
        for doc_id in doc_ids:
            # Get document info
            doc = self.index.get_document_by_filename_or_id(doc_id)
            if doc:
                uri = create_ctx_uri(self.project_id, doc_id=doc['id'])
                title = doc.get('title') or doc.get('filename')
                lines.append(f"  - {title}")
                lines.append(f"    {uri}")

        return "\n".join(lines)

    def find_recent_related_docs(self, since_hours: int = 24) -> List[str]:
        """Find documents created/modified recently (likely related to current work).

        Args:
            since_hours: Look back this many hours

        Returns:
            List of document IDs
        """
        from datetime import timedelta

        since = (datetime.now() - timedelta(hours=since_hours)).isoformat()

        cursor = self.index.conn.execute("""
            SELECT id FROM documents
            WHERE updated_at >= ? OR created_at >= ?
            ORDER BY updated_at DESC
            LIMIT 10
        """, (since, since))

        return [row['id'] for row in cursor]

    def resolve_ctx_uri(self, uri: str) -> Optional[dict]:
        """Resolve a ctx:// URI to document info.

        Args:
            uri: ctx:// URI string

        Returns:
            Document info dict or None if not found
        """
        parsed = parse_ctx_uri(uri)
        if not parsed:
            return None

        # Verify project ID matches
        if parsed.project_id != self.project_id:
            return None

        if parsed.doc_id:
            return self.index.get_document_by_filename_or_id(parsed.doc_id)
        elif parsed.filename:
            return self.index.get_document_by_filename(parsed.filename)

        return None

    def extract_ctx_uris_from_text(self, text: str) -> List[CtxUri]:
        """Extract all ctx:// URIs from text.

        Args:
            text: Text to search

        Returns:
            List of parsed CtxUri objects
        """
        pattern = r'ctx://[a-f0-9]+(?:/[^\s\)]+)?'
        matches = re.findall(pattern, text)

        uris = []
        for match in matches:
            parsed = parse_ctx_uri(match)
            if parsed:
                uris.append(parsed)

        return uris
