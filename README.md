# claude-context

Manage project-wide and branch-specific context documents for Claude sessions.

## The Problem

When working with Claude across multiple git worktrees, you lose access to git-ignored context documents (plans, decisions, notes) that you've created in previous sessions. This tool solves that by centralizing context storage outside your worktrees while keeping everything organized by project and branch.

## Features

- **Centralized storage** - Contexts stored in `~/.claude-contexts/`, outside your worktrees
- **Branch-aware** - Automatic organization by git branch
- **Shared contexts** - Project-wide contexts accessible from any branch
- **Git-backed** - Every project's contexts are version controlled
- **Claude-friendly** - Simple commands that both you and Claude can use
- **Worktree-safe** - Access the same contexts from any worktree of the same project

## Installation

From PyPI:

```bash
uv tool install claude-context
```

Or from source:

```bash
git clone <repository-url>
cd claude-context
uv tool install .
```

## Quick Start

```bash
# In your git project
cd ~/my-project
ctx init

# Create a new context (any file type!)
ctx new plans/feature-implementation.md
ctx save scripts/setup.sh < setup.sh

# List contexts for current branch
ctx list

# List shared (project-wide) contexts
ctx list --shared

# Show a context's content
ctx show plans/feature-implementation.md

# Save content from stdin (useful for Claude)
echo "Implementation plan..." | ctx save plans/feature-implementation.md

# Get project info
ctx info
```

## Usage

### Initialize a Project

Run this once per project (in any worktree):

```bash
ctx init
```

This creates:
- Context storage at `~/.claude-contexts/<project-id>/`
- Symlink at `.claude/context/` → central storage (for easy access)
- Default category directories: `plans/`, `decisions/`, `bugs/`, `notes/`
- Metadata tracking your project
- Git repository for version control
- Adds `.claude/context` to `.gitignore`

### Working with Contexts

**Any file type supported** - Store markdown, scripts, configs, or any file:

```bash
# Markdown files
ctx new plans/auth-system.md
ctx save notes/meeting.md

# Shell scripts
ctx save --shared scripts/setup.sh < setup.sh

# Config files
ctx save configs/env.json --content '{"key": "value"}'

# Any file type
cp important-doc.pdf .claude/context/shared/docs/
```

**Create a new context:**
```bash
ctx new plans/auth-system.md
# Opens in $EDITOR (nano by default)
```

**Create a shared context (available across all branches):**
```bash
ctx new --shared architecture/database.md
```

**Open an existing context:**
```bash
ctx open plans/auth-system.md
```

**Show context content (no editor, just output):**
```bash
ctx show plans/auth-system.md
# Perfect for piping to Claude or other tools
```

**Save content to a context:**
```bash
# From stdin
echo "New plan content" | ctx save plans/auth-system.md

# From command line
ctx save plans/auth-system.md --content "New plan content"

# Shell scripts
cat setup.sh | ctx save scripts/setup.sh
```

### Listing Contexts

**Current branch contexts:**
```bash
ctx list
```

**Shared contexts only:**
```bash
ctx list --shared
```

**All contexts (shared + all branches):**
```bash
ctx list --all
```

### Direct Access via Symlink

You can also work with contexts directly through the filesystem using the `.claude/context/` symlink:

```bash
# Browse contexts
ls .claude/context/branches/main/
ls .claude/context/shared/

# Read any file type
cat .claude/context/branches/main/plans/auth-system.md
cat .claude/context/shared/scripts/setup.sh

# Create/edit with your favorite editor
vim .claude/context/shared/architecture/database.md
code .claude/context/branches/main/configs/settings.json

# Copy files in/out (any file type!)
cp external-doc.pdf .claude/context/branches/main/notes/
cp setup.sh .claude/context/shared/scripts/
cp -r templates/ .claude/context/shared/

# The symlink is git-ignored, so it won't pollute your repo
```

**Note**: Files created directly through the symlink won't be auto-committed to the context git repo. Use `ctx save` for automatic git commits, or commit manually:

```bash
cd ~/.claude-contexts/<project-id>
git add -A && git commit -m "Manual update"
```

### Project Information

```bash
ctx info
```

Shows:
- Project ID (hash used for storage)
- Git root path
- Git remote URL
- Current branch
- Context counts

## Directory Structure

**Central storage** (`~/.claude-contexts/`):
```
~/.claude-contexts/
├── <project-hash>/
│   ├── .git/                    # Version control
│   ├── .ctx-meta                # Project metadata
│   ├── shared/                  # Project-wide contexts
│   │   ├── plans/
│   │   ├── decisions/
│   │   ├── bugs/
│   │   └── notes/
│   └── branches/                # Branch-specific contexts
│       ├── main/
│       │   ├── plans/
│       │   ├── decisions/
│       │   ├── bugs/
│       │   └── notes/
│       └── feature-auth/
│           ├── plans/
│           └── ...
```

**Project directory** (with symlink):
```
~/my-project/
├── .claude/
│   └── context/  → symlink to ~/.claude-contexts/<project-hash>/
├── src/
└── ... (your project files)
```

## Working with Git Worktrees

```bash
# Main project
cd ~/my-project
ctx init
ctx new plans/main-plan

# Create a worktree for a feature
git worktree add ~/my-project-auth feature/auth
cd ~/my-project-auth

# Same contexts available!
ctx list --shared              # See project-wide contexts
ctx new plans/auth-implementation  # Create branch-specific plan

# Later, merge and delete worktree
cd ~/my-project
git merge feature/auth
git worktree remove ~/my-project-auth

# Context preserved!
ctx list --all                 # feature-auth contexts still there
```

## Project Identification

The tool identifies projects by:

1. **Git remote URL** (preferred) - Stable across clones and moves
2. **Git root path** (fallback) - Used when no remote exists

If no git remote is configured, you'll see a warning. Add one with:

```bash
git remote add origin <url>
```

## Tips

**Use categories to organize:**
- `plans/` - Implementation plans (markdown)
- `decisions/` - Architecture and design decisions (markdown)
- `bugs/` - Bug investigation notes (markdown)
- `notes/` - General session notes (markdown)
- `scripts/` - Setup scripts, utilities (shell, python, etc.)
- `configs/` - Configuration files (json, yaml, toml, etc.)
- `docs/` - Reference documentation (pdf, txt, etc.)

Categories are freeform - create your own structure!

**Any file type works:**
- Markdown: `.md`
- Scripts: `.sh`, `.py`, `.js`
- Configs: `.json`, `.yaml`, `.toml`, `.env`
- Documents: `.txt`, `.pdf`, `.docx`
- Or anything else you need!

**Claude can use ctx too:**

```bash
# Ask Claude to save a plan
ctx save plans/new-feature --content "$(claude-generated-content)"

# Ask Claude to read a plan
ctx show plans/existing-feature | claude
```

**Version control:**

Each project's contexts are git-backed. You can:

```bash
cd ~/.claude-contexts/<project-id>
git log                    # See history
git diff                   # See recent changes
git show HEAD~1:shared/plans/feature.md  # View old versions
```

## Environment Variables

- `EDITOR` - Text editor for `ctx new` and `ctx open` (default: `nano`)

## FAQ

**Q: What happens if I move my project directory?**

A: If you have a git remote URL configured, contexts remain accessible (projects are identified by remote URL). Without a remote, you'll create a new context store (old one remains in `~/.claude-contexts/`).

**Q: Can I share contexts between machines?**

A: Yes! The `~/.claude-contexts/<project-id>/` directory is a git repository. You can push it to a remote or sync via cloud storage.

**Q: What if I delete a worktree?**

A: Contexts are stored centrally, not in worktrees. Deleting a worktree doesn't affect your contexts.

**Q: Can I use this without git?**

A: No, `claude-context` requires a git repository to identify projects and branches.

## License

MIT
