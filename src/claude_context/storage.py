"""Context storage management with git backing"""

import json
import subprocess
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

from .project import (
    find_git_root,
    get_project_identifier,
    get_current_branch,
    sanitize_branch_name,
    get_git_remote_url
)

if TYPE_CHECKING:
    from .index import ContextIndex
    from .chains import ChainManager


class ContextStorage:
    """Manages context document storage for a project."""

    DEFAULT_CATEGORIES = ['plans', 'decisions', 'bugs', 'notes']

    def __init__(self):
        self.base_dir = Path.home() / '.claude-contexts'
        self.project_id, self.used_remote, self.warning = get_project_identifier()
        self.project_dir = self.base_dir / self.project_id
        self.git_root = find_git_root()
        self._index: Optional["ContextIndex"] = None
        self._chains: Optional["ChainManager"] = None

    @property
    def index(self) -> "ContextIndex":
        """Get or create the context index (lazy initialization)."""
        if self._index is None:
            from .index import ContextIndex
            self._index = ContextIndex(self.project_dir / 'index.db')
        return self._index

    @property
    def chains(self) -> "ChainManager":
        """Get or create the chain manager (lazy initialization)."""
        if self._chains is None:
            from .chains import ChainManager
            self._chains = ChainManager(self.index)
        return self._chains

    def _get_index_path(self) -> Path:
        """Get path to the SQLite index database."""
        return self.project_dir / 'index.db'

    def has_index(self) -> bool:
        """Check if the index database exists."""
        return self._get_index_path().exists()

    def _get_meta_path(self) -> Path:
        """Get path to metadata file."""
        return self.project_dir / '.ctx-meta'

    def _get_shared_dir(self) -> Path:
        """Get path to shared contexts directory."""
        return self.project_dir / 'shared'

    def _get_branch_dir(self, branch: Optional[str] = None) -> Path:
        """Get path to branch-specific contexts directory."""
        if branch is None:
            branch = get_current_branch()
        safe_branch = sanitize_branch_name(branch)
        return self.project_dir / 'branches' / safe_branch

    def _init_git(self):
        """Initialize git repository in project context directory."""
        if not (self.project_dir / '.git').exists():
            subprocess.run(
                ['git', 'init'],
                cwd=self.project_dir,
                capture_output=True,
                check=True
            )
            # Create initial .gitignore
            gitignore = self.project_dir / '.gitignore'
            gitignore.write_text('# Add any files to ignore here\n')

            # Initial commit
            subprocess.run(
                ['git', 'add', '.'],
                cwd=self.project_dir,
                capture_output=True,
                check=True
            )
            subprocess.run(
                ['git', 'commit', '-m', 'Initialize context storage'],
                cwd=self.project_dir,
                capture_output=True,
                check=True
            )

    def _auto_commit(self, message: str):
        """Automatically commit changes to context git repo."""
        try:
            # Stage all changes
            subprocess.run(
                ['git', 'add', '-A'],
                cwd=self.project_dir,
                capture_output=True,
                check=True
            )
            # Commit if there are changes
            subprocess.run(
                ['git', 'commit', '-m', message],
                cwd=self.project_dir,
                capture_output=True
            )
        except subprocess.CalledProcessError:
            # No changes to commit, that's fine
            pass

    def commit_changes(self, message: Optional[str] = None) -> tuple[bool, str]:
        """
        Commit all changes in the context storage.

        Args:
            message: Commit message. If None, uses default.

        Returns:
            Tuple of (success, output_message)
        """
        self.ensure_initialized()

        if message is None:
            message = "Manual update to contexts"

        try:
            # Check if there are changes
            result = subprocess.run(
                ['git', 'status', '--porcelain'],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                check=True
            )

            if not result.stdout.strip():
                return False, "No changes to commit"

            # Stage all changes
            subprocess.run(
                ['git', 'add', '-A'],
                cwd=self.project_dir,
                capture_output=True,
                check=True
            )

            # Commit
            subprocess.run(
                ['git', 'commit', '-m', message],
                cwd=self.project_dir,
                capture_output=True,
                check=True
            )

            # Get commit hash
            result = subprocess.run(
                ['git', 'rev-parse', '--short', 'HEAD'],
                cwd=self.project_dir,
                capture_output=True,
                text=True,
                check=True
            )
            commit_hash = result.stdout.strip()

            return True, f"Committed changes as {commit_hash}"

        except subprocess.CalledProcessError as e:
            return False, f"Git error: {e}"

    def _create_symlink(self):
        """Create a symlink in the project directory to the context storage."""
        symlink_path = self.git_root / '.claude' / 'context'

        # Create .claude directory if it doesn't exist
        symlink_path.parent.mkdir(parents=True, exist_ok=True)

        # Remove existing symlink or directory if it exists
        if symlink_path.is_symlink():
            symlink_path.unlink()
        elif symlink_path.exists():
            # Path exists but is not a symlink - don't overwrite
            return

        # Create symlink
        symlink_path.symlink_to(self.project_dir, target_is_directory=True)

        # Update .gitignore to exclude the symlink
        gitignore_path = self.git_root / '.gitignore'
        gitignore_entry = '.claude/context\n'

        if gitignore_path.exists():
            content = gitignore_path.read_text()
            if '.claude/context' not in content:
                # Add to existing .gitignore
                with gitignore_path.open('a') as f:
                    if not content.endswith('\n'):
                        f.write('\n')
                    f.write(gitignore_entry)
        else:
            # Create new .gitignore
            gitignore_path.write_text(gitignore_entry)

    def init(self) -> Optional[str]:
        """
        Initialize context storage for current project.

        Returns:
            Warning message if applicable
        """
        # Create directory structure
        self.project_dir.mkdir(parents=True, exist_ok=True)

        # Save metadata
        meta = {
            'git_root': str(self.git_root),
            'git_remote': get_git_remote_url(),
            'project_id': self.project_id,
            'used_remote': self.used_remote
        }
        self._get_meta_path().write_text(json.dumps(meta, indent=2))

        # Create default shared categories
        for category in self.DEFAULT_CATEGORIES:
            (self._get_shared_dir() / category).mkdir(parents=True, exist_ok=True)
            # Create .gitkeep to preserve empty directories
            (self._get_shared_dir() / category / '.gitkeep').touch()

        # Create default categories for current branch
        for category in self.DEFAULT_CATEGORIES:
            (self._get_branch_dir() / category).mkdir(parents=True, exist_ok=True)
            (self._get_branch_dir() / category / '.gitkeep').touch()

        # Initialize git
        self._init_git()
        self._auto_commit('Initialize project contexts')

        # Create symlink in project directory
        self._create_symlink()

        return self.warning

    def ensure_initialized(self):
        """Ensure the project context storage is initialized."""
        if not self.project_dir.exists():
            raise RuntimeError(
                "Context storage not initialized. Run 'ctx init' first."
            )

    def list_contexts(self, shared: bool = False, all_contexts: bool = False) -> List[str]:
        """
        List available contexts.

        Args:
            shared: If True, list only shared contexts
            all_contexts: If True, list all contexts (shared + all branches)

        Returns:
            List of context paths (relative)
        """
        self.ensure_initialized()
        contexts = []

        def scan_dir(base: Path, prefix: str = '') -> List[str]:
            """Recursively scan directory for all files."""
            results = []
            if not base.exists():
                return results

            for item in sorted(base.rglob('*')):
                if item.is_file() and item.name != '.gitkeep':
                    rel_path = item.relative_to(base)
                    if prefix:
                        results.append(f"{prefix}/{rel_path}")
                    else:
                        results.append(str(rel_path))
            return results

        if all_contexts:
            # List shared
            contexts.extend(scan_dir(self._get_shared_dir(), 'shared'))
            # List all branches
            branches_dir = self.project_dir / 'branches'
            if branches_dir.exists():
                for branch_dir in sorted(branches_dir.iterdir()):
                    if branch_dir.is_dir():
                        contexts.extend(scan_dir(branch_dir, f'branches/{branch_dir.name}'))
        elif shared:
            contexts.extend(scan_dir(self._get_shared_dir()))
        else:
            # List current branch
            contexts.extend(scan_dir(self._get_branch_dir()))

        return contexts

    def _resolve_path(self, context_path: str, shared: bool = False) -> Path:
        """
        Resolve a context path to absolute filesystem path.

        Args:
            context_path: Relative path like 'plans/auth.md' or 'scripts/setup.sh'
            shared: If True, resolve to shared directory

        Returns:
            Absolute path to the context file
        """
        if shared:
            return self._get_shared_dir() / context_path
        else:
            return self._get_branch_dir() / context_path

    def get_context_path(self, context_path: str, shared: bool = False) -> Path:
        """Get the absolute path for a context (ensures parent dirs exist)."""
        self.ensure_initialized()
        path = self._resolve_path(context_path, shared)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def read_context(self, context_path: str, shared: bool = False) -> str:
        """Read a context file."""
        self.ensure_initialized()
        path = self._resolve_path(context_path, shared)
        if not path.exists():
            raise FileNotFoundError(f"Context not found: {context_path}")
        return path.read_text()

    def write_context(self, context_path: str, content: str, shared: bool = False):
        """Write content to a context file."""
        self.ensure_initialized()
        path = self.get_context_path(context_path, shared)
        path.write_text(content)

        # Update index
        rel_path = str(path.relative_to(self.project_dir))
        self.index.index_document(rel_path, content, self.project_dir)

        # Auto-commit
        scope = "shared" if shared else get_current_branch()
        self._auto_commit(f"Update {scope}: {context_path}")

    def write_context_auto(
        self,
        content: str,
        filename_hint: Optional[str] = None,
        force_shared: Optional[bool] = None,
        chain_id: Optional[str] = None,
        auto_chain: bool = True,
    ) -> tuple[str, "ClassificationResult", Optional[str]]:
        """
        Auto-classify and save content.

        Args:
            content: Document content
            filename_hint: Optional hint for filename/type detection
            force_shared: If set, override scope detection
            chain_id: Explicit chain to add document to
            auto_chain: If True, try to infer chain from content references

        Returns:
            Tuple of (saved_path, classification_result, chain_id or None)
        """
        from .classifier import classify_document, ClassificationResult

        self.ensure_initialized()

        # Classify the document
        result = classify_document(content, filename_hint)

        # Override scope if requested
        if force_shared is not None:
            scope = 'shared' if force_shared else 'branch'
        else:
            scope = result.scope

        # Build the path
        from .classifier import get_category_for_type
        category = get_category_for_type(result.doc_type)

        if scope == 'shared':
            context_path = f"{category}/{result.suggested_filename}"
            path = self._get_shared_dir() / category / result.suggested_filename
        else:
            context_path = f"{category}/{result.suggested_filename}"
            path = self._get_branch_dir() / category / result.suggested_filename

        # Ensure directory exists
        path.parent.mkdir(parents=True, exist_ok=True)

        # Write the file
        path.write_text(content)

        # Update index with classification metadata
        rel_path = str(path.relative_to(self.project_dir))
        doc_id = self.index.index_document(rel_path, content, self.project_dir)

        # Add extracted tags
        for tag in result.tags:
            self.index.add_tag(doc_id, tag, auto_generated=True)

        # Handle chaining
        assigned_chain_id = None
        if chain_id:
            # Explicit chain assignment
            self.chains.add_document_to_chain(chain_id, doc_id)
            assigned_chain_id = chain_id
        elif auto_chain:
            # Try to infer chain from content
            assigned_chain_id = self.chains.auto_chain_document(
                doc_id, content, self.project_dir
            )

        # Auto-commit
        self._auto_commit(f"Add {result.doc_type}: {result.suggested_filename}")

        return context_path, result, assigned_chain_id

    def get_info(self) -> dict:
        """Get information about the current context storage."""
        self.ensure_initialized()

        meta = json.loads(self._get_meta_path().read_text())

        # Count contexts
        shared_count = len(self.list_contexts(shared=True))
        branch_count = len(self.list_contexts(shared=False))
        total_count = len(self.list_contexts(all_contexts=True))

        info = {
            'project_id': self.project_id,
            'git_root': meta['git_root'],
            'git_remote': meta.get('git_remote'),
            'storage_path': str(self.project_dir),
            'current_branch': get_current_branch(),
            'context_counts': {
                'shared': shared_count,
                'current_branch': branch_count,
                'total': total_count
            },
            'warning': self.warning
        }

        # Add index stats if available
        if self.has_index():
            info['index_stats'] = self.index.get_stats()

            # Add chain stats
            active_chains = self.chains.list_chains(status='active')
            info['chain_stats'] = {
                'active_chains': len(active_chains),
            }

        return info

    def reindex(self, force: bool = False) -> int:
        """Reindex all documents.

        Args:
            force: If True, reindex all docs. If False, only stale ones.

        Returns:
            Number of documents indexed
        """
        self.ensure_initialized()

        if force:
            # Clear existing index
            self.index.conn.execute("DELETE FROM documents")
            self.index.conn.commit()

        # Ensure fresh will scan and index all files
        self.index.ensure_fresh(self.project_dir)

        # Return count
        cursor = self.index.conn.execute("SELECT COUNT(*) as count FROM documents")
        return cursor.fetchone()['count']
