"""Migration tools for upgrading context storage between versions.

This module provides:
- Version detection (v1 = files only, v2 = files + index)
- Backup functionality
- Non-destructive migration from v1 to v2
"""

import shutil
import tarfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .index import ContextIndex


@dataclass
class MigrationResult:
    """Result of a migration operation."""
    success: bool
    version_before: str
    version_after: str
    files_indexed: int
    chains_created: int
    errors: List[str]
    warnings: List[str]


@dataclass
class BackupResult:
    """Result of a backup operation."""
    success: bool
    backup_path: Path
    size_bytes: int
    file_count: int


def detect_version(project_dir: Path) -> str:
    """Detect context storage format version.

    Args:
        project_dir: Path to the context storage directory

    Returns:
        'v2' if index.db exists
        'v1' if shared/ or branches/ exists but no index
        'uninitialized' if neither exists
    """
    if not project_dir.exists():
        return "uninitialized"

    if (project_dir / "index.db").exists():
        return "v2"

    if (project_dir / "shared").exists() or (project_dir / "branches").exists():
        return "v1"

    return "uninitialized"


def get_storage_stats(project_dir: Path) -> dict:
    """Get statistics about the context storage.

    Args:
        project_dir: Path to the context storage directory

    Returns:
        Dict with file counts, size, etc.
    """
    stats = {
        "total_files": 0,
        "total_size_bytes": 0,
        "by_extension": {},
        "by_directory": {},
    }

    if not project_dir.exists():
        return stats

    skip_names = {'.git', 'index.db', 'index.db-wal', 'index.db-shm'}

    for file_path in project_dir.rglob('*'):
        if file_path.is_file():
            # Skip internal files
            if file_path.name in skip_names:
                continue
            if any(part.startswith('.') for part in file_path.relative_to(project_dir).parts):
                continue

            stats["total_files"] += 1
            stats["total_size_bytes"] += file_path.stat().st_size

            # By extension
            ext = file_path.suffix or "(none)"
            stats["by_extension"][ext] = stats["by_extension"].get(ext, 0) + 1

            # By top-level directory
            rel_path = file_path.relative_to(project_dir)
            if len(rel_path.parts) > 1:
                top_dir = rel_path.parts[0]
            else:
                top_dir = "(root)"
            stats["by_directory"][top_dir] = stats["by_directory"].get(top_dir, 0) + 1

    return stats


class MigrationManager:
    """Handles migration operations for context storage."""

    def __init__(self, project_dir: Path):
        """Initialize migration manager.

        Args:
            project_dir: Path to the context storage directory
        """
        self.project_dir = Path(project_dir)

    def create_backup(self, output_path: Optional[Path] = None, compress: bool = True) -> BackupResult:
        """Create a backup of the context storage.

        Args:
            output_path: Where to save the backup. If None, creates in parent dir.
            compress: If True, creates a .tar.gz. If False, copies directory.

        Returns:
            BackupResult with backup details
        """
        if not self.project_dir.exists():
            return BackupResult(
                success=False,
                backup_path=Path(""),
                size_bytes=0,
                file_count=0
            )

        # Generate backup name
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        project_name = self.project_dir.name

        if output_path is None:
            if compress:
                output_path = self.project_dir.parent / f"{project_name}_backup_{timestamp}.tar.gz"
            else:
                output_path = self.project_dir.parent / f"{project_name}_backup_{timestamp}"

        # Get stats before backup
        stats = get_storage_stats(self.project_dir)

        try:
            if compress:
                # Create tar.gz
                with tarfile.open(output_path, "w:gz") as tar:
                    tar.add(self.project_dir, arcname=project_name)
                size = output_path.stat().st_size
            else:
                # Copy directory
                shutil.copytree(self.project_dir, output_path)
                size = sum(f.stat().st_size for f in output_path.rglob('*') if f.is_file())

            return BackupResult(
                success=True,
                backup_path=output_path,
                size_bytes=size,
                file_count=stats["total_files"]
            )

        except Exception as e:
            return BackupResult(
                success=False,
                backup_path=output_path,
                size_bytes=0,
                file_count=0
            )

    def migrate(self, dry_run: bool = False, verbose: bool = False) -> MigrationResult:
        """Migrate context storage from v1 to v2.

        This is a non-destructive migration that:
        1. Creates the index.db if it doesn't exist
        2. Indexes all existing documents
        3. Infers chains from document cross-references

        Args:
            dry_run: If True, only report what would be done
            verbose: If True, print progress

        Returns:
            MigrationResult with details
        """
        errors = []
        warnings = []

        version_before = detect_version(self.project_dir)

        if version_before == "uninitialized":
            return MigrationResult(
                success=False,
                version_before=version_before,
                version_after=version_before,
                files_indexed=0,
                chains_created=0,
                errors=["Context storage not initialized. Run 'ctx init' first."],
                warnings=[]
            )

        if version_before == "v2":
            warnings.append("Already at v2. Re-indexing existing documents.")

        # Get list of files to index
        files_to_index = []
        skip_names = {'.gitkeep', '.ctx-meta', 'index.db', 'index.db-wal', 'index.db-shm', 'config.yaml'}

        for file_path in self.project_dir.rglob('*'):
            if file_path.is_file() and file_path.name not in skip_names:
                rel_path = file_path.relative_to(self.project_dir)
                # Skip hidden files/directories
                if any(part.startswith('.') for part in rel_path.parts):
                    continue
                files_to_index.append(file_path)

        if verbose or dry_run:
            print(f"Found {len(files_to_index)} files to index")

        if dry_run:
            # Just report what would be done
            from .index import infer_type_from_path, infer_scope_from_path

            for file_path in files_to_index:
                rel_path = str(file_path.relative_to(self.project_dir))
                doc_type = infer_type_from_path(rel_path)
                scope, branch = infer_scope_from_path(rel_path)

                if verbose:
                    print(f"  Would index: {rel_path}")
                    print(f"    Type: {doc_type}, Scope: {scope}")
                    if branch:
                        print(f"    Branch: {branch}")

            return MigrationResult(
                success=True,
                version_before=version_before,
                version_after="v2",
                files_indexed=len(files_to_index),
                chains_created=0,
                errors=[],
                warnings=warnings + ["DRY RUN - no changes made"]
            )

        # Actually perform migration
        from .index import ContextIndex

        index = ContextIndex(self.project_dir / 'index.db')

        indexed_count = 0
        for file_path in files_to_index:
            try:
                rel_path = str(file_path.relative_to(self.project_dir))
                content = file_path.read_text(errors='replace')
                index.index_document(rel_path, content, self.project_dir)
                indexed_count += 1

                if verbose:
                    print(f"  Indexed: {rel_path}")

            except Exception as e:
                errors.append(f"Failed to index {file_path}: {e}")

        # Infer chains from cross-references
        chains_created = self._infer_chains(index, verbose)

        index.close()

        version_after = detect_version(self.project_dir)

        return MigrationResult(
            success=len(errors) == 0,
            version_before=version_before,
            version_after=version_after,
            files_indexed=indexed_count,
            chains_created=chains_created,
            errors=errors,
            warnings=warnings
        )

    def _infer_chains(self, index: "ContextIndex", verbose: bool = False) -> int:
        """Infer work chains from document cross-references.

        Looks for @filename references in document content and creates
        chains linking related documents.

        Args:
            index: The context index
            verbose: Print progress

        Returns:
            Number of chains created
        """
        import re
        from .chains import ChainManager

        chains = ChainManager(index)
        chains_created = 0

        # Get all documents
        cursor = index.conn.execute(
            "SELECT id, filename, full_content FROM documents WHERE chain_id IS NULL"
        )
        docs = cursor.fetchall()

        for doc in docs:
            content = doc['full_content'] or ''

            # Look for @filename references
            refs = re.findall(r'@([^\s\]]+\.md)', content)
            if not refs:
                continue

            # Find referenced documents
            for ref in refs:
                # Try to find the referenced document
                ref_doc = index.get_document_by_filename(ref)
                if not ref_doc:
                    # Try partial match
                    cursor = index.conn.execute(
                        "SELECT id, chain_id FROM documents WHERE filename LIKE ?",
                        (f"%{ref}",)
                    )
                    ref_doc = cursor.fetchone()

                if ref_doc and ref_doc['chain_id']:
                    # Add current doc to existing chain
                    try:
                        chains.add_document_to_chain(ref_doc['chain_id'], doc['id'])
                        if verbose:
                            print(f"  Added {doc['filename']} to existing chain")
                    except Exception:
                        pass

        return chains_created

    def restore_backup(self, backup_path: Path) -> bool:
        """Restore from a backup.

        Args:
            backup_path: Path to backup file (.tar.gz) or directory

        Returns:
            True if successful
        """
        if not backup_path.exists():
            return False

        # Remove current storage
        if self.project_dir.exists():
            shutil.rmtree(self.project_dir)

        try:
            if backup_path.suffix == '.gz' or str(backup_path).endswith('.tar.gz'):
                # Extract tar.gz
                with tarfile.open(backup_path, "r:gz") as tar:
                    # Extract to parent directory
                    tar.extractall(self.project_dir.parent)
            else:
                # Copy directory
                shutil.copytree(backup_path, self.project_dir)

            return True
        except Exception:
            return False
