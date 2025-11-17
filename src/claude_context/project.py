"""Project detection and identification"""

import hashlib
import subprocess
from pathlib import Path
from typing import Optional, Tuple


class GitError(Exception):
    """Raised when git operations fail"""
    pass


def find_git_root() -> Path:
    """Find the git repository root from current directory."""
    try:
        result = subprocess.run(
            ['git', 'rev-parse', '--show-toplevel'],
            capture_output=True,
            text=True,
            check=True
        )
        return Path(result.stdout.strip())
    except subprocess.CalledProcessError:
        raise GitError("Not in a git repository")


def get_git_remote_url() -> Optional[str]:
    """Get the git remote URL (origin)."""
    try:
        result = subprocess.run(
            ['git', 'config', '--get', 'remote.origin.url'],
            capture_output=True,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        return None


def get_current_branch() -> str:
    """Get the current git branch name."""
    try:
        result = subprocess.run(
            ['git', 'branch', '--show-current'],
            capture_output=True,
            text=True,
            check=True
        )
        branch = result.stdout.strip()
        if not branch:
            # Detached HEAD state
            result = subprocess.run(
                ['git', 'rev-parse', '--short', 'HEAD'],
                capture_output=True,
                text=True,
                check=True
            )
            return f"detached-{result.stdout.strip()}"
        return branch
    except subprocess.CalledProcessError:
        raise GitError("Failed to get current branch")


def get_project_identifier() -> Tuple[str, bool, Optional[str]]:
    """
    Get a stable project identifier.

    Returns:
        Tuple of (identifier_hash, used_remote, warning_message)
        - identifier_hash: Hash to use for directory name
        - used_remote: True if remote URL was used, False if fallback to path
        - warning_message: Warning to show user if applicable
    """
    git_root = find_git_root()
    remote_url = get_git_remote_url()

    if remote_url:
        # Use remote URL for stable identification
        identifier = remote_url
        used_remote = True
        warning = None
    else:
        # Fallback to absolute path
        identifier = str(git_root.resolve())
        used_remote = False
        warning = (
            "⚠️  No git remote found. Using local path for project identification.\n"
            "   Contexts may not sync if you clone this repo elsewhere.\n"
            "   Add a remote with: git remote add origin <url>"
        )

    # Create hash for directory name
    hash_obj = hashlib.sha256(identifier.encode())
    identifier_hash = hash_obj.hexdigest()[:16]

    return identifier_hash, used_remote, warning


def sanitize_branch_name(branch: str) -> str:
    """Sanitize branch name for use as directory name."""
    # Replace slashes and other problematic characters
    return branch.replace('/', '-').replace('\\', '-')
