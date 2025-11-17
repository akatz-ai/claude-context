#!/usr/bin/env python3
"""Command-line interface for claude-context"""

import argparse
import os
import sys
from pathlib import Path

from .project import GitError
from .storage import ContextStorage


def cmd_init(args):
    """Initialize context storage for current project."""
    try:
        storage = ContextStorage()
        warning = storage.init()

        print(f"✓ Context storage initialized at: {storage.project_dir}")
        print(f"  Project: {storage.git_root}")
        print(f"  Branch: {storage._get_branch_dir().name}")
        print(f"  Symlink: {storage.git_root}/docs/contexts → {storage.project_dir}")

        if warning:
            print(f"\n{warning}")

        return 0
    except GitError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_list(args):
    """List available contexts."""
    try:
        storage = ContextStorage()
        contexts = storage.list_contexts(
            shared=args.shared,
            all_contexts=args.all
        )

        if not contexts:
            scope = "shared" if args.shared else ("all" if args.all else "current branch")
            print(f"No contexts found for {scope}")
            return 0

        # Print header
        if args.all:
            print("All contexts:")
        elif args.shared:
            print("Shared contexts:")
        else:
            branch = storage._get_branch_dir().name
            print(f"Contexts for branch '{branch}':")

        # Print contexts
        for ctx in contexts:
            print(f"  {ctx}")

        return 0
    except (GitError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_new(args):
    """Create a new context file."""
    try:
        storage = ContextStorage()
        path = storage.get_context_path(args.path, shared=args.shared)

        # Create empty file if it doesn't exist
        if not path.exists():
            path.write_text('')

        # Open in editor
        editor = os.environ.get('EDITOR', 'nano')
        os.system(f'{editor} "{path}"')

        # Auto-commit after editing
        scope = "shared" if args.shared else storage._get_branch_dir().name
        storage._auto_commit(f"Update {scope}: {args.path}")

        print(f"✓ Context saved: {args.path}")
        return 0
    except (GitError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_open(args):
    """Open an existing context file."""
    try:
        storage = ContextStorage()
        path = storage._resolve_path(args.path, shared=args.shared)

        if not path.exists():
            print(f"Error: Context not found: {args.path}", file=sys.stderr)
            print(f"Create it with: ctx new {args.path}", file=sys.stderr)
            return 1

        # Open in editor
        editor = os.environ.get('EDITOR', 'nano')
        os.system(f'{editor} "{path}"')

        # Auto-commit after editing
        scope = "shared" if args.shared else storage._get_branch_dir().name
        storage._auto_commit(f"Update {scope}: {args.path}")

        print(f"✓ Context saved: {args.path}")
        return 0
    except (GitError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_show(args):
    """Display context content."""
    try:
        storage = ContextStorage()
        content = storage.read_context(args.path, shared=args.shared)
        print(content, end='')
        return 0
    except FileNotFoundError:
        print(f"Error: Context not found: {args.path}", file=sys.stderr)
        return 1
    except (GitError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_save(args):
    """Save content to a context file (from stdin or args)."""
    try:
        storage = ContextStorage()

        # Read content from stdin
        if not sys.stdin.isatty():
            content = sys.stdin.read()
        elif args.content:
            content = args.content
        else:
            print("Error: No content provided. Pipe content to stdin or use --content", file=sys.stderr)
            return 1

        storage.write_context(args.path, content, shared=args.shared)

        scope = "shared" if args.shared else storage._get_branch_dir().name
        print(f"✓ Context saved: {args.path} ({scope})")
        return 0
    except (GitError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_info(args):
    """Display project context information."""
    try:
        storage = ContextStorage()
        info = storage.get_info()

        print("Project Context Information")
        print("=" * 50)
        print(f"Project ID:      {info['project_id']}")
        print(f"Git Root:        {info['git_root']}")
        print(f"Git Remote:      {info['git_remote'] or '(none)'}")
        print(f"Storage Path:    {info['storage_path']}")
        print(f"Current Branch:  {info['current_branch']}")
        print()
        print("Context Counts:")
        print(f"  Shared:         {info['context_counts']['shared']}")
        print(f"  Current Branch: {info['context_counts']['current_branch']}")
        print(f"  Total:          {info['context_counts']['total']}")

        if info['warning']:
            print(f"\n{info['warning']}")

        return 0
    except (GitError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def main():
    """Main entry point for the CLI"""
    parser = argparse.ArgumentParser(
        description="Manage project-wide and branch-specific context documents for Claude sessions",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument(
        '--version',
        action='version',
        version='%(prog)s 0.1.0'
    )

    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # init command
    init_parser = subparsers.add_parser('init', help='Initialize context storage for current project')
    init_parser.set_defaults(func=cmd_init)

    # list command
    list_parser = subparsers.add_parser('list', help='List available contexts')
    list_parser.add_argument('--shared', action='store_true', help='List only shared contexts')
    list_parser.add_argument('--all', action='store_true', help='List all contexts (shared + all branches)')
    list_parser.set_defaults(func=cmd_list)

    # new command
    new_parser = subparsers.add_parser('new', help='Create a new context file')
    new_parser.add_argument('path', help='Context path (e.g., plans/auth-system)')
    new_parser.add_argument('--shared', action='store_true', help='Create in shared contexts')
    new_parser.set_defaults(func=cmd_new)

    # open command
    open_parser = subparsers.add_parser('open', help='Open an existing context file')
    open_parser.add_argument('path', help='Context path')
    open_parser.add_argument('--shared', action='store_true', help='Open from shared contexts')
    open_parser.set_defaults(func=cmd_open)

    # show command
    show_parser = subparsers.add_parser('show', help='Display context content')
    show_parser.add_argument('path', help='Context path')
    show_parser.add_argument('--shared', action='store_true', help='Show from shared contexts')
    show_parser.set_defaults(func=cmd_show)

    # save command
    save_parser = subparsers.add_parser('save', help='Save content to a context file')
    save_parser.add_argument('path', help='Context path')
    save_parser.add_argument('--shared', action='store_true', help='Save to shared contexts')
    save_parser.add_argument('--content', help='Content to save (or use stdin)')
    save_parser.set_defaults(func=cmd_save)

    # info command
    info_parser = subparsers.add_parser('info', help='Display project context information')
    info_parser.set_defaults(func=cmd_info)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\nInterrupted", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
