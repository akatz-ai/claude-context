-- Claude Context v2: SQLite Schema
-- Created: 2025-12-03
-- Usage: Initialize with sqlite3 index.db < v2.sql

-- Enable foreign keys
PRAGMA foreign_keys = ON;

-- ============================================================================
-- MAIN TABLES
-- ============================================================================

-- Documents table: Core document metadata and content
CREATE TABLE IF NOT EXISTS documents (
    id TEXT PRIMARY KEY,                    -- UUID
    filename TEXT NOT NULL UNIQUE,          -- Relative path from context root
    title TEXT,                             -- Extracted from first heading
    doc_type TEXT,                          -- 'session', 'plan', 'decision', 'knowledge', etc.
    original_category TEXT,                 -- Directory-based category (preserved from path)

    -- Scope and branch
    scope TEXT DEFAULT 'shared',            -- 'shared' or 'branch'
    branch TEXT,                            -- Branch name if scope='branch'

    -- Lifecycle
    status TEXT DEFAULT 'active',           -- 'active', 'archived', 'superseded'
    superseded_by TEXT,                     -- ID of newer doc if superseded

    -- Timestamps
    created_at TIMESTAMP,                   -- When doc was first created
    updated_at TIMESTAMP,                   -- When doc content last changed
    indexed_at TIMESTAMP,                   -- When last indexed
    file_mtime REAL,                        -- File modification time (for staleness check)

    -- Content
    summary TEXT,                           -- AI-generated or extracted one-liner
    full_content TEXT,                      -- Full markdown content
    frontmatter TEXT,                       -- JSON of YAML frontmatter if present

    -- Chain tracking (for session continuity)
    chain_id TEXT,                          -- Work chain this doc belongs to
    parent_doc_id TEXT,                     -- Previous doc in chain (for lineage)
    session_id TEXT,                        -- Claude session ID that created this (if known)

    -- Foreign keys
    FOREIGN KEY (superseded_by) REFERENCES documents(id) ON DELETE SET NULL,
    FOREIGN KEY (parent_doc_id) REFERENCES documents(id) ON DELETE SET NULL,
    FOREIGN KEY (chain_id) REFERENCES chains(chain_id) ON DELETE SET NULL
);

-- Tags table: Flexible categorization
CREATE TABLE IF NOT EXISTS tags (
    doc_id TEXT NOT NULL,
    tag TEXT NOT NULL,
    auto_generated BOOLEAN DEFAULT TRUE,    -- TRUE=AI/rules suggested, FALSE=user added
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (doc_id, tag),
    FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE
);

-- Document cross-references
CREATE TABLE IF NOT EXISTS doc_refs (
    source_doc_id TEXT NOT NULL,
    target_doc_id TEXT NOT NULL,
    ref_type TEXT,                          -- 'references', 'supersedes', 'continues', 'related'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (source_doc_id, target_doc_id),
    FOREIGN KEY (source_doc_id) REFERENCES documents(id) ON DELETE CASCADE,
    FOREIGN KEY (target_doc_id) REFERENCES documents(id) ON DELETE CASCADE
);

-- Links to code repository commits
CREATE TABLE IF NOT EXISTS commit_refs (
    doc_id TEXT NOT NULL,
    commit_hash TEXT NOT NULL,              -- Code repo commit SHA
    repo_path TEXT,                         -- Path to code repo (for multi-repo scenarios)
    ref_type TEXT,                          -- 'informed_by', 'implements', 'documents'
    commit_message TEXT,                    -- First line of commit message
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (doc_id, commit_hash),
    FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE
);

-- Work chains for session continuity
CREATE TABLE IF NOT EXISTS chains (
    chain_id TEXT PRIMARY KEY,              -- UUID
    name TEXT,                              -- Optional human-readable name
    description TEXT,                       -- What this chain is about
    root_doc_id TEXT,                       -- First doc in chain
    latest_doc_id TEXT,                     -- Most recent doc in chain
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    status TEXT DEFAULT 'active',           -- 'active', 'completed', 'abandoned'

    FOREIGN KEY (root_doc_id) REFERENCES documents(id) ON DELETE SET NULL,
    FOREIGN KEY (latest_doc_id) REFERENCES documents(id) ON DELETE SET NULL
);

-- ============================================================================
-- FULL-TEXT SEARCH
-- ============================================================================

-- FTS5 virtual table for full-text search
CREATE VIRTUAL TABLE IF NOT EXISTS doc_fts USING fts5(
    title,
    full_content,
    summary,
    content='documents',
    content_rowid='rowid',
    tokenize='porter unicode61'
);

-- Triggers to keep FTS in sync with documents table

-- After INSERT: Add to FTS
CREATE TRIGGER IF NOT EXISTS docs_fts_insert AFTER INSERT ON documents BEGIN
    INSERT INTO doc_fts(rowid, title, full_content, summary)
    VALUES (new.rowid, new.title, new.full_content, new.summary);
END;

-- After DELETE: Remove from FTS
CREATE TRIGGER IF NOT EXISTS docs_fts_delete AFTER DELETE ON documents BEGIN
    INSERT INTO doc_fts(doc_fts, rowid, title, full_content, summary)
    VALUES ('delete', old.rowid, old.title, old.full_content, old.summary);
END;

-- After UPDATE: Update FTS (delete old, insert new)
CREATE TRIGGER IF NOT EXISTS docs_fts_update AFTER UPDATE ON documents BEGIN
    INSERT INTO doc_fts(doc_fts, rowid, title, full_content, summary)
    VALUES ('delete', old.rowid, old.title, old.full_content, old.summary);
    INSERT INTO doc_fts(rowid, title, full_content, summary)
    VALUES (new.rowid, new.title, new.full_content, new.summary);
END;

-- ============================================================================
-- INDEXES
-- ============================================================================

-- Document queries
CREATE INDEX IF NOT EXISTS idx_docs_type ON documents(doc_type);
CREATE INDEX IF NOT EXISTS idx_docs_scope ON documents(scope);
CREATE INDEX IF NOT EXISTS idx_docs_branch ON documents(branch);
CREATE INDEX IF NOT EXISTS idx_docs_status ON documents(status);
CREATE INDEX IF NOT EXISTS idx_docs_chain ON documents(chain_id);
CREATE INDEX IF NOT EXISTS idx_docs_created ON documents(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_docs_updated ON documents(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_docs_category ON documents(original_category);

-- Tag queries
CREATE INDEX IF NOT EXISTS idx_tags_tag ON tags(tag);
CREATE INDEX IF NOT EXISTS idx_tags_auto ON tags(auto_generated);

-- Chain queries
CREATE INDEX IF NOT EXISTS idx_chains_status ON chains(status);
CREATE INDEX IF NOT EXISTS idx_chains_updated ON chains(updated_at DESC);

-- Commit reference queries
CREATE INDEX IF NOT EXISTS idx_commits_hash ON commit_refs(commit_hash);
CREATE INDEX IF NOT EXISTS idx_commits_repo ON commit_refs(repo_path);

-- ============================================================================
-- VIEWS
-- ============================================================================

-- Active documents with tags (common query)
CREATE VIEW IF NOT EXISTS v_active_docs AS
SELECT
    d.*,
    GROUP_CONCAT(t.tag, ', ') as tags
FROM documents d
LEFT JOIN tags t ON d.id = t.doc_id
WHERE d.status = 'active'
GROUP BY d.id;

-- Chain overview
CREATE VIEW IF NOT EXISTS v_chains AS
SELECT
    c.*,
    rd.title as root_title,
    ld.title as latest_title,
    (SELECT COUNT(*) FROM documents WHERE chain_id = c.chain_id) as doc_count
FROM chains c
LEFT JOIN documents rd ON c.root_doc_id = rd.id
LEFT JOIN documents ld ON c.latest_doc_id = ld.id;

-- Recent sessions (for quick access)
CREATE VIEW IF NOT EXISTS v_recent_sessions AS
SELECT *
FROM documents
WHERE doc_type = 'session' AND status = 'active'
ORDER BY created_at DESC
LIMIT 20;

-- ============================================================================
-- METADATA
-- ============================================================================

-- Schema version and migration tracking
CREATE TABLE IF NOT EXISTS schema_info (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Insert schema version
INSERT OR REPLACE INTO schema_info (key, value, updated_at)
VALUES ('version', '2.0.0', CURRENT_TIMESTAMP);

INSERT OR REPLACE INTO schema_info (key, value, updated_at)
VALUES ('created_at', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP);
