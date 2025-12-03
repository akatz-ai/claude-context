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
        print(f"  Symlink: {storage.git_root}/.claude/context → {storage.project_dir}")

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

        # If any index filters are specified, use the index
        use_index = any([
            getattr(args, 'type', None),
            getattr(args, 'tags', None),
            getattr(args, 'since', None),
            getattr(args, 'status', None) and args.status != 'active',
        ])

        if use_index and storage.has_index():
            # Ensure index is fresh
            storage.index.ensure_fresh(storage.project_dir)

            # Parse tags
            tags = args.tags.split(',') if args.tags else None

            # Get filtered results from index
            results = storage.index.list_documents(
                doc_type=args.type,
                tags=tags,
                scope='shared' if args.shared else None,
                status=args.status or 'active',
                since=args.since,
                limit=100
            )

            if not results:
                print("No documents found matching filters")
                return 0

            print(f"Documents ({len(results)} results):")
            for doc in results:
                type_str = f"[{doc.doc_type}]" if doc.doc_type else ""
                tag_str = f" #{', #'.join(doc.tags[:3])}" if doc.tags else ""
                print(f"  {doc.filename} {type_str}{tag_str}")
                if doc.title:
                    print(f"    {doc.title}")
        else:
            # Original behavior
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

        # Auto-classify mode
        if getattr(args, 'auto', False):
            # Force shared if --shared flag is set
            force_shared = True if args.shared else None

            # Resolve chain prefix to full ID
            chain_id_arg = getattr(args, 'chain', None)
            resolved_chain_id = None
            if chain_id_arg:
                chains = storage.chains.list_chains(status='all')
                matching = [c for c in chains if c.chain_id.startswith(chain_id_arg)]
                if matching:
                    resolved_chain_id = matching[0].chain_id
                else:
                    print(f"Warning: Chain not found: {chain_id_arg}", file=sys.stderr)

            saved_path, result, chain_id = storage.write_context_auto(
                content,
                filename_hint=getattr(args, 'path', None),
                force_shared=force_shared,
                chain_id=resolved_chain_id,
            )

            print(f"✓ Auto-classified and saved:")
            print(f"  Path: {saved_path}")
            print(f"  Type: {result.doc_type} (confidence: {result.confidence:.0%})")
            print(f"  Scope: {result.scope}")
            if result.tags:
                print(f"  Tags: {', '.join(result.tags)}")
            if result.title:
                print(f"  Title: {result.title}")
            if chain_id:
                print(f"  Chain: {chain_id[:8]}...")
        else:
            # Traditional save with explicit path
            if not args.path:
                print("Error: Path required (or use --auto for auto-classification)", file=sys.stderr)
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

        # Show index stats if available
        if 'index_stats' in info:
            stats = info['index_stats']
            print()
            print("Index Statistics:")
            print(f"  Indexed Docs:   {stats.get('total_documents', 0)}")
            print(f"  Total Tags:     {stats.get('total_tags', 0)}")
            print(f"  Schema Version: {stats.get('schema_version', 'N/A')}")
            if stats.get('by_type'):
                print("  By Type:")
                for doc_type, count in sorted(stats['by_type'].items()):
                    print(f"    {doc_type}: {count}")

        # Show chain stats if available
        if 'chain_stats' in info:
            chain_stats = info['chain_stats']
            print()
            print("Chain Statistics:")
            print(f"  Active Chains:  {chain_stats.get('active_chains', 0)}")

        if info['warning']:
            print(f"\n{info['warning']}")

        return 0
    except (GitError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_commit(args):
    """Commit all changes in context storage."""
    try:
        storage = ContextStorage()
        success, message = storage.commit_changes(args.message)

        if success:
            print(f"✓ {message}")
            return 0
        else:
            print(message)
            return 0 if "No changes" in message else 1

    except (GitError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_find(args):
    """Full-text search across context documents."""
    try:
        storage = ContextStorage()

        if not storage.has_index():
            print("Index not found. Run 'ctx reindex' first.", file=sys.stderr)
            return 1

        # Ensure index is fresh
        storage.index.ensure_fresh(storage.project_dir)

        # Parse tags
        tags = args.tags.split(',') if args.tags else None

        # Search
        results = storage.index.search(
            query=args.query,
            doc_type=args.type,
            tags=tags,
            status=args.status or 'active',
            since=args.since,
            limit=args.limit or 20
        )

        if not results:
            print("No documents found matching query")
            return 0

        print(f"Search results ({len(results)} matches):")
        for result in results:
            type_str = f"[{result.doc_type}]" if result.doc_type else ""
            print(f"\n  {result.filename} {type_str}")
            if result.title:
                print(f"  Title: {result.title}")
            if result.snippet:
                # Clean up snippet for display
                snippet = result.snippet.replace('\n', ' ').strip()
                print(f"  ...{snippet}...")
            if result.tags:
                print(f"  Tags: {', '.join(result.tags[:5])}")

        return 0
    except (GitError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_reindex(args):
    """Reindex all context documents."""
    try:
        storage = ContextStorage()

        print("Reindexing context documents...")
        count = storage.reindex(force=args.force)
        print(f"✓ Indexed {count} documents")

        # Show stats
        stats = storage.index.get_stats()
        if stats.get('by_type'):
            print("\nBy type:")
            for doc_type, type_count in sorted(stats['by_type'].items()):
                print(f"  {doc_type}: {type_count}")

        return 0
    except (GitError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_tags(args):
    """List all tags with document counts."""
    try:
        storage = ContextStorage()

        if not storage.has_index():
            print("Index not found. Run 'ctx reindex' first.", file=sys.stderr)
            return 1

        tags = storage.index.get_all_tags()

        if not tags:
            print("No tags found")
            return 0

        print(f"Tags ({len(tags)} total):")
        for tag, count in tags:
            print(f"  #{tag} ({count})")

        return 0
    except (GitError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_chains(args):
    """List work chains."""
    try:
        storage = ContextStorage()

        if not storage.has_index():
            print("Index not found. Run 'ctx reindex' first.", file=sys.stderr)
            return 1

        status = getattr(args, 'status', 'active') or 'active'
        chains = storage.chains.list_chains(status=status)

        if not chains:
            print(f"No {status} chains found")
            return 0

        print(f"Work Chains ({len(chains)} {status}):")
        for chain in chains:
            name = chain.name or chain.latest_title or "(unnamed)"
            print(f"\n  {chain.chain_id[:8]}... [{chain.status}]")
            print(f"    Name: {name}")
            print(f"    Docs: {chain.doc_count}")
            if chain.latest_title:
                print(f"    Latest: {chain.latest_title}")
            if chain.updated_at:
                print(f"    Updated: {chain.updated_at[:10]}")

        return 0
    except (GitError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_chain_start(args):
    """Start a new work chain."""
    try:
        storage = ContextStorage()

        if not storage.has_index():
            print("Index not found. Run 'ctx reindex' first.", file=sys.stderr)
            return 1

        chain_id = storage.chains.create_chain(
            name=args.name,
            description=getattr(args, 'description', None),
        )

        print(f"✓ Created chain: {chain_id[:8]}...")
        print(f"  Name: {args.name}")
        print()
        print("To add documents to this chain:")
        print(f"  ctx save --auto --chain {chain_id[:8]}")

        return 0
    except (GitError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_chain_show(args):
    """Show chain details and history."""
    try:
        storage = ContextStorage()

        if not storage.has_index():
            print("Index not found. Run 'ctx reindex' first.", file=sys.stderr)
            return 1

        # Find chain by prefix
        chains = storage.chains.list_chains(status='all')
        matching = [c for c in chains if c.chain_id.startswith(args.chain_id)]

        if not matching:
            print(f"Chain not found: {args.chain_id}", file=sys.stderr)
            return 1

        if len(matching) > 1:
            print(f"Multiple chains match '{args.chain_id}':", file=sys.stderr)
            for c in matching:
                print(f"  {c.chain_id}", file=sys.stderr)
            return 1

        chain = matching[0]
        docs = storage.chains.get_chain_documents(chain.chain_id)

        print(f"Chain: {chain.chain_id}")
        print("=" * 50)
        print(f"Name:    {chain.name or '(unnamed)'}")
        print(f"Status:  {chain.status}")
        print(f"Created: {chain.created_at[:10] if chain.created_at else 'N/A'}")
        print(f"Updated: {chain.updated_at[:10] if chain.updated_at else 'N/A'}")
        print()
        print(f"Documents ({len(docs)}):")
        for i, doc in enumerate(docs, 1):
            prefix = "└─" if i == len(docs) else "├─"
            title = doc.title or doc.filename
            print(f"  {prefix} {title}")
            if doc.summary:
                print(f"     {doc.summary[:60]}...")

        return 0
    except (GitError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_continue(args):
    """Get the latest document in a chain for continuation."""
    try:
        storage = ContextStorage()

        if not storage.has_index():
            print("Index not found. Run 'ctx reindex' first.", file=sys.stderr)
            return 1

        # Ensure index is fresh
        storage.index.ensure_fresh(storage.project_dir)

        # Parse tags
        tags = args.tags.split(',') if args.tags else None

        # Find chain by prefix if specified
        chain_id = None
        if args.chain:
            chains = storage.chains.list_chains(status='all')
            matching = [c for c in chains if c.chain_id.startswith(args.chain)]
            if matching:
                chain_id = matching[0].chain_id

        # Get latest document
        doc = storage.chains.get_latest_in_chain(chain_id=chain_id, tags=tags)

        if not doc:
            if chain_id:
                print("No documents found in chain", file=sys.stderr)
            elif tags:
                print(f"No chained documents found with tags: {', '.join(tags)}", file=sys.stderr)
            else:
                print("No chained documents found", file=sys.stderr)
            return 1

        if args.path_only:
            print(doc.filename)
        else:
            print(f"Continue from: {doc.filename}")
            if doc.title:
                print(f"Title: {doc.title}")
            if doc.summary:
                print(f"Summary: {doc.summary[:100]}...")
            if doc.created_at:
                print(f"Created: {doc.created_at[:10]}")

        return 0
    except (GitError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_classify(args):
    """Preview auto-classification of content (without saving)."""
    try:
        from .classifier import classify_document, suggest_improvements

        # Read content from stdin or file
        if args.file:
            content = Path(args.file).read_text()
            filename_hint = Path(args.file).name
        elif not sys.stdin.isatty():
            content = sys.stdin.read()
            filename_hint = None
        else:
            print("Error: Provide content via stdin or --file", file=sys.stderr)
            return 1

        result = classify_document(content, filename_hint)

        print("Classification Result:")
        print("=" * 50)
        print(f"Type:       {result.doc_type} (confidence: {result.confidence:.0%})")
        print(f"Scope:      {result.scope}")
        print(f"Filename:   {result.suggested_filename}")
        print(f"Path:       {result.suggested_path}")

        if result.title:
            print(f"Title:      {result.title}")
        if result.summary:
            print(f"Summary:    {result.summary[:100]}...")
        if result.tags:
            print(f"Tags:       {', '.join(result.tags)}")

        # Show suggestions for improvement
        suggestions = suggest_improvements(content, result)
        if suggestions:
            print()
            print("Suggestions:")
            for i, suggestion in enumerate(suggestions, 1):
                print(f"  {i}. {suggestion}")

        return 0
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_last(args):
    """Get the most recent document, optionally filtered by type."""
    try:
        storage = ContextStorage()

        if not storage.has_index():
            print("Index not found. Run 'ctx reindex' first.", file=sys.stderr)
            return 1

        # Ensure index is fresh
        storage.index.ensure_fresh(storage.project_dir)

        results = storage.index.list_documents(
            doc_type=args.type,
            status='active',
            limit=1
        )

        if not results:
            print("No documents found", file=sys.stderr)
            return 1

        doc = results[0]
        if args.path_only:
            # Output just the path for scripting
            print(doc.filename)
        else:
            print(f"Latest: {doc.filename}")
            if doc.title:
                print(f"Title: {doc.title}")
            if doc.doc_type:
                print(f"Type: {doc.doc_type}")
            if doc.created_at:
                print(f"Created: {doc.created_at}")

        return 0
    except (GitError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


# =============================================================================
# Phase 4: Commit Integration Commands
# =============================================================================


def cmd_show_commits(args):
    """Show commits linked to a context document."""
    try:
        storage = ContextStorage()

        if not storage.has_index():
            print("Index not found. Run 'ctx reindex' first.", file=sys.stderr)
            return 1

        # Find the document
        doc = storage.index.get_document_by_filename_or_id(args.doc)
        if not doc:
            print(f"Document not found: {args.doc}", file=sys.stderr)
            return 1

        # Get linked commits
        commits = storage.git_integration.get_commits_for_doc(doc['id'])

        if not commits:
            print(f"No commits linked to: {doc['filename']}")
            return 0

        print(f"Commits linked to: {doc['filename']}")
        if doc.get('title'):
            print(f"Title: {doc['title']}")
        print("=" * 50)

        for ref in commits:
            print(f"\n  {ref.commit_hash[:8]} [{ref.ref_type}]")
            if ref.commit_message:
                print(f"    {ref.commit_message}")
            if ref.created_at:
                print(f"    Linked: {ref.created_at[:10]}")

        return 0
    except (GitError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_show_context(args):
    """Show context documents linked to a code commit."""
    try:
        storage = ContextStorage()

        if not storage.has_index():
            print("Index not found. Run 'ctx reindex' first.", file=sys.stderr)
            return 1

        # Get commit info
        commit_info = storage.git_integration.get_commit_info(args.commit)
        if not commit_info:
            print(f"Commit not found: {args.commit}", file=sys.stderr)
            return 1

        # Get linked documents
        docs = storage.git_integration.get_docs_for_commit(args.commit)

        print(f"Commit: {commit_info.short_hash}")
        print(f"Message: {commit_info.message}")
        print(f"Author: {commit_info.author}")
        print(f"Date: {commit_info.date.strftime('%Y-%m-%d %H:%M')}")
        print("=" * 50)

        if not docs:
            print("\nNo context documents linked to this commit")
            # Suggest finding related documents
            print("\nTo link a document to this commit:")
            print(f"  ctx link <doc> {commit_info.short_hash}")
            return 0

        print(f"\nLinked Documents ({len(docs)}):")
        for ref in docs:
            print(f"\n  {ref.doc_filename} [{ref.ref_type}]")
            if ref.doc_title:
                print(f"    Title: {ref.doc_title}")

            # Show ctx:// URI
            from .git_integration import create_ctx_uri
            uri = create_ctx_uri(storage.project_id, doc_id=ref.doc_id)
            print(f"    URI: {uri}")

        return 0
    except (GitError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_link(args):
    """Link a context document to a code commit."""
    try:
        storage = ContextStorage()

        if not storage.has_index():
            print("Index not found. Run 'ctx reindex' first.", file=sys.stderr)
            return 1

        # Find the document
        doc = storage.index.get_document_by_filename_or_id(args.doc)
        if not doc:
            print(f"Document not found: {args.doc}", file=sys.stderr)
            return 1

        # Verify commit exists
        commit_info = storage.git_integration.get_commit_info(args.commit)
        if not commit_info:
            print(f"Commit not found: {args.commit}", file=sys.stderr)
            return 1

        # Create the link
        ref_type = getattr(args, 'type', None) or 'documents'
        storage.git_integration.link_commit_to_doc(
            doc_id=doc['id'],
            commit_hash=commit_info.hash,
            ref_type=ref_type,
            commit_message=commit_info.message
        )

        # Show ctx:// URI
        from .git_integration import create_ctx_uri
        uri = create_ctx_uri(storage.project_id, doc_id=doc['id'])

        print(f"✓ Linked document to commit")
        print(f"  Document: {doc['filename']}")
        print(f"  Commit: {commit_info.short_hash} - {commit_info.message}")
        print(f"  Type: {ref_type}")
        print(f"  URI: {uri}")

        return 0
    except (GitError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_links(args):
    """List all commit<->document links."""
    try:
        storage = ContextStorage()

        if not storage.has_index():
            print("Index not found. Run 'ctx reindex' first.", file=sys.stderr)
            return 1

        # Get all links
        refs = storage.git_integration.get_all_commit_refs(limit=args.limit or 50)

        if not refs:
            print("No commit links found")
            print("\nTo link a document to a commit:")
            print("  ctx link <doc> <commit>")
            return 0

        print(f"Commit Links ({len(refs)} total):")
        print("=" * 50)

        for ref in refs:
            print(f"\n  {ref.commit_hash[:8]} ↔ {ref.doc_filename}")
            print(f"    Type: {ref.ref_type}")
            if ref.commit_message:
                print(f"    Commit: {ref.commit_message[:50]}...")
            if ref.doc_title:
                print(f"    Doc: {ref.doc_title[:50]}")

        return 0
    except (GitError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_uri(args):
    """Generate or resolve a ctx:// URI."""
    try:
        storage = ContextStorage()

        if not storage.has_index():
            print("Index not found. Run 'ctx reindex' first.", file=sys.stderr)
            return 1

        # Check if input is a ctx:// URI to resolve
        if args.input.startswith('ctx://'):
            # Resolve URI
            doc = storage.git_integration.resolve_ctx_uri(args.input)
            if not doc:
                print(f"Could not resolve URI: {args.input}", file=sys.stderr)
                return 1

            print(f"Resolved: {args.input}")
            print("=" * 50)
            print(f"Filename: {doc['filename']}")
            if doc.get('title'):
                print(f"Title: {doc['title']}")
            if doc.get('doc_type'):
                print(f"Type: {doc['doc_type']}")
            if doc.get('summary'):
                print(f"Summary: {doc['summary'][:100]}...")

            if args.show_content:
                print()
                print("Content:")
                print("-" * 50)
                print(doc.get('full_content', ''))
        else:
            # Generate URI for document
            doc = storage.index.get_document_by_filename_or_id(args.input)
            if not doc:
                print(f"Document not found: {args.input}", file=sys.stderr)
                return 1

            from .git_integration import create_ctx_uri
            uri = create_ctx_uri(storage.project_id, doc_id=doc['id'])

            if args.verbose:
                print(f"Document: {doc['filename']}")
                if doc.get('title'):
                    print(f"Title: {doc['title']}")
                print(f"URI: {uri}")
            else:
                print(uri)

        return 0
    except (GitError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


# =============================================================================
# Phase 5: Migration Commands
# =============================================================================


def cmd_backup(args):
    """Create a backup of the context storage."""
    try:
        storage = ContextStorage()
        storage.ensure_initialized()

        from .migration import MigrationManager, get_storage_stats

        manager = MigrationManager(storage.project_dir)

        # Get stats first
        stats = get_storage_stats(storage.project_dir)
        print(f"Creating backup of {stats['total_files']} files...")

        # Determine output path
        output_path = Path(args.output) if args.output else None
        compress = not args.no_compress

        result = manager.create_backup(output_path=output_path, compress=compress)

        if result.success:
            size_mb = result.size_bytes / (1024 * 1024)
            print(f"✓ Backup created successfully")
            print(f"  Path: {result.backup_path}")
            print(f"  Files: {result.file_count}")
            print(f"  Size: {size_mb:.2f} MB")
            return 0
        else:
            print("Failed to create backup", file=sys.stderr)
            return 1

    except (GitError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_migrate(args):
    """Migrate context storage to v2 format."""
    try:
        storage = ContextStorage()

        from .migration import MigrationManager, detect_version, get_storage_stats

        manager = MigrationManager(storage.project_dir)

        # Check current version
        version = detect_version(storage.project_dir)
        print(f"Current version: {version}")

        if version == "uninitialized":
            print("Context storage not initialized. Run 'ctx init' first.", file=sys.stderr)
            return 1

        # Get stats
        stats = get_storage_stats(storage.project_dir)
        print(f"Files to process: {stats['total_files']}")

        if args.dry_run:
            print("\n[DRY RUN - no changes will be made]\n")

        # Run migration
        result = manager.migrate(dry_run=args.dry_run, verbose=args.verbose)

        print()
        print("Migration Result:")
        print("=" * 50)
        print(f"Version: {result.version_before} → {result.version_after}")
        print(f"Files indexed: {result.files_indexed}")
        print(f"Chains created: {result.chains_created}")

        if result.warnings:
            print("\nWarnings:")
            for warning in result.warnings:
                print(f"  ⚠ {warning}")

        if result.errors:
            print("\nErrors:")
            for error in result.errors:
                print(f"  ✗ {error}")
            return 1

        if not args.dry_run:
            print("\n✓ Migration completed successfully")

        return 0

    except (GitError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_version(args):
    """Show context storage version and stats."""
    try:
        storage = ContextStorage()

        from .migration import detect_version, get_storage_stats

        version = detect_version(storage.project_dir)
        stats = get_storage_stats(storage.project_dir)

        print(f"Context Storage Version: {version}")
        print("=" * 50)
        print(f"Storage path: {storage.project_dir}")
        print(f"Total files: {stats['total_files']}")

        size_mb = stats['total_size_bytes'] / (1024 * 1024)
        print(f"Total size: {size_mb:.2f} MB")

        if stats['by_extension']:
            print("\nBy extension:")
            for ext, count in sorted(stats['by_extension'].items(), key=lambda x: -x[1]):
                print(f"  {ext}: {count}")

        if stats['by_directory']:
            print("\nBy directory:")
            for dir_name, count in sorted(stats['by_directory'].items(), key=lambda x: -x[1]):
                print(f"  {dir_name}/: {count}")

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
    list_parser.add_argument('--type', '-t', help='Filter by document type (session, plan, decision, etc.)')
    list_parser.add_argument('--tags', help='Filter by tags (comma-separated)')
    list_parser.add_argument('--since', help='Filter by date (ISO format: YYYY-MM-DD)')
    list_parser.add_argument('--status', choices=['active', 'archived', 'superseded', 'all'], default='active',
                            help='Filter by status (default: active)')
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
    save_parser.add_argument('path', nargs='?', help='Context path (optional with --auto)')
    save_parser.add_argument('--shared', action='store_true', help='Save to shared contexts')
    save_parser.add_argument('--content', help='Content to save (or use stdin)')
    save_parser.add_argument('--auto', '-a', action='store_true',
                            help='Auto-classify: detect type, generate filename, extract tags')
    save_parser.add_argument('--chain', help='Add to specified chain (use chain ID prefix)')
    save_parser.set_defaults(func=cmd_save)

    # info command
    info_parser = subparsers.add_parser('info', help='Display project context information')
    info_parser.set_defaults(func=cmd_info)

    # commit command
    commit_parser = subparsers.add_parser('commit', help='Commit all changes in context storage')
    commit_parser.add_argument('message', nargs='?', help='Commit message (optional)')
    commit_parser.set_defaults(func=cmd_commit)

    # find command (new in v2)
    find_parser = subparsers.add_parser('find', help='Full-text search across context documents')
    find_parser.add_argument('query', help='Search query (supports FTS5 syntax)')
    find_parser.add_argument('--type', '-t', help='Filter by document type')
    find_parser.add_argument('--tags', help='Filter by tags (comma-separated)')
    find_parser.add_argument('--since', help='Filter by date (ISO format: YYYY-MM-DD)')
    find_parser.add_argument('--status', choices=['active', 'archived', 'superseded', 'all'], default='active',
                            help='Filter by status (default: active)')
    find_parser.add_argument('--limit', '-n', type=int, default=20, help='Maximum results (default: 20)')
    find_parser.set_defaults(func=cmd_find)

    # reindex command (new in v2)
    reindex_parser = subparsers.add_parser('reindex', help='Reindex all context documents')
    reindex_parser.add_argument('--force', '-f', action='store_true', help='Force full reindex (ignore cached)')
    reindex_parser.set_defaults(func=cmd_reindex)

    # tags command (new in v2)
    tags_parser = subparsers.add_parser('tags', help='List all tags with document counts')
    tags_parser.set_defaults(func=cmd_tags)

    # last command (new in v2)
    last_parser = subparsers.add_parser('last', help='Get the most recent document')
    last_parser.add_argument('--type', '-t', help='Filter by document type')
    last_parser.add_argument('--path-only', '-p', action='store_true', help='Output only the path (for scripting)')
    last_parser.set_defaults(func=cmd_last)

    # classify command (new in v2)
    classify_parser = subparsers.add_parser('classify', help='Preview auto-classification without saving')
    classify_parser.add_argument('--file', '-f', help='File to classify (or use stdin)')
    classify_parser.set_defaults(func=cmd_classify)

    # chains command (new in v2 - Phase 3)
    chains_parser = subparsers.add_parser('chains', help='List work chains')
    chains_parser.add_argument('--status', '-s', choices=['active', 'completed', 'abandoned', 'all'],
                              default='active', help='Filter by status (default: active)')
    chains_parser.set_defaults(func=cmd_chains)

    # chain subcommands
    chain_parser = subparsers.add_parser('chain', help='Chain management commands')
    chain_subparsers = chain_parser.add_subparsers(dest='chain_command', help='Chain commands')

    # chain start
    chain_start_parser = chain_subparsers.add_parser('start', help='Start a new work chain')
    chain_start_parser.add_argument('name', help='Chain name')
    chain_start_parser.add_argument('--description', '-d', help='Chain description')
    chain_start_parser.set_defaults(func=cmd_chain_start)

    # chain show
    chain_show_parser = chain_subparsers.add_parser('show', help='Show chain details')
    chain_show_parser.add_argument('chain_id', help='Chain ID (or prefix)')
    chain_show_parser.set_defaults(func=cmd_chain_show)

    # continue command (new in v2 - Phase 3)
    continue_parser = subparsers.add_parser('continue', help='Get latest document in a chain')
    continue_parser.add_argument('--chain', '-c', help='Specific chain ID (or prefix)')
    continue_parser.add_argument('--tags', '-t', help='Filter by tags (comma-separated)')
    continue_parser.add_argument('--path-only', '-p', action='store_true',
                                help='Output only the path (for scripting)')
    continue_parser.set_defaults(func=cmd_continue)

    # =========================================================================
    # Phase 4: Commit Integration Commands
    # =========================================================================

    # show-commits command: show commits linked to a document
    show_commits_parser = subparsers.add_parser('show-commits',
                                                 help='Show commits linked to a context document')
    show_commits_parser.add_argument('doc', help='Document filename or ID')
    show_commits_parser.set_defaults(func=cmd_show_commits)

    # show-context command: show documents linked to a commit
    show_context_parser = subparsers.add_parser('show-context',
                                                 help='Show context documents for a code commit')
    show_context_parser.add_argument('commit', help='Git commit hash (full or short)')
    show_context_parser.set_defaults(func=cmd_show_context)

    # link command: link a document to a commit
    link_parser = subparsers.add_parser('link', help='Link a context document to a code commit')
    link_parser.add_argument('doc', help='Document filename or ID')
    link_parser.add_argument('commit', help='Git commit hash')
    link_parser.add_argument('--type', '-t', choices=['informed_by', 'implements', 'documents'],
                            default='documents', help='Type of link (default: documents)')
    link_parser.set_defaults(func=cmd_link)

    # links command: list all links
    links_parser = subparsers.add_parser('links', help='List all commit<->document links')
    links_parser.add_argument('--limit', '-n', type=int, default=50, help='Maximum results')
    links_parser.set_defaults(func=cmd_links)

    # uri command: generate or resolve ctx:// URIs
    uri_parser = subparsers.add_parser('uri', help='Generate or resolve ctx:// URIs')
    uri_parser.add_argument('input', help='Document filename/ID (to generate) or ctx:// URI (to resolve)')
    uri_parser.add_argument('--verbose', '-v', action='store_true', help='Show full document info')
    uri_parser.add_argument('--content', dest='show_content', action='store_true',
                           help='Show document content when resolving')
    uri_parser.set_defaults(func=cmd_uri)

    # =========================================================================
    # Phase 5: Migration Commands
    # =========================================================================

    # backup command: create backup of context storage
    backup_parser = subparsers.add_parser('backup', help='Create a backup of context storage')
    backup_parser.add_argument('--output', '-o', help='Output path (default: auto-generated in parent dir)')
    backup_parser.add_argument('--no-compress', action='store_true',
                              help='Create directory copy instead of .tar.gz')
    backup_parser.set_defaults(func=cmd_backup)

    # migrate command: migrate to v2 format
    migrate_parser = subparsers.add_parser('migrate', help='Migrate context storage to v2 format')
    migrate_parser.add_argument('--dry-run', '-n', action='store_true',
                               help='Show what would be done without making changes')
    migrate_parser.add_argument('--verbose', '-v', action='store_true',
                               help='Show detailed progress')
    migrate_parser.set_defaults(func=cmd_migrate)

    # version command: show storage version and stats
    version_parser = subparsers.add_parser('storage-version', help='Show context storage version and stats')
    version_parser.set_defaults(func=cmd_version)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Handle chain subcommand
    if args.command == 'chain' and not getattr(args, 'chain_command', None):
        chain_parser.print_help()
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
