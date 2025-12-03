"""Auto-classification for context documents.

Provides rule-based classification of documents by:
- Document type (session, plan, decision, etc.)
- Tags (extracted from content)
- Scope (shared vs branch-specific)
- Auto-generated filenames
"""

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Set, Tuple


@dataclass
class ClassificationResult:
    """Result of auto-classifying a document."""
    doc_type: str
    tags: List[str]
    scope: str  # 'shared' or 'branch'
    suggested_filename: str
    suggested_path: str  # Full relative path including category
    title: Optional[str]
    summary: Optional[str]
    confidence: float  # 0.0 to 1.0


# Document type patterns - checked against content
# Patterns are (regex, weight) - weights should be balanced so no type dominates
TYPE_CONTENT_PATTERNS = {
    'session': [
        (r'##\s*What\s+(was\s+)?Accomplished', 0.5),
        (r'##\s*Next\s+Steps', 0.2),
        (r'##\s*Files\s+(Created|Modified|Changed)', 0.4),
        (r'\*\*Status:\*\*\s*(Completed|In Progress|Implemented)', 0.3),
        (r'session\s+summary', 0.5),
        (r'work\s+session', 0.4),
        (r'today.s?\s+work', 0.3),
        (r'this\s+session', 0.4),
    ],
    'plan': [
        (r'##\s*Implementation\s*(Plan|Phases?|Steps?)', 0.4),
        (r'##\s*Phase\s*\d', 0.5),
        (r'##\s*Phases?\s*$', 0.3),
        (r'##\s*Tasks?\s*$', 0.2),
        (r'##\s*Goals?\s*$', 0.2),
        (r'##\s*Timeline', 0.4),
        (r'##\s*Milestones?', 0.4),
        (r'##\s*Deliverables?', 0.4),
        (r'implementation\s+plan', 0.5),
        (r'project\s+plan', 0.4),
        (r'-\s*\[\s*[xX\s]\s*\]', 0.15),  # Checkboxes (multiple matches add up)
    ],
    'decision': [
        (r'##\s*Decision', 0.4),
        (r'##\s*Alternatives?\s*Considered', 0.4),
        (r'##\s*Rationale', 0.4),
        (r'##\s*Trade-?offs?', 0.3),
        (r'##\s*Context', 0.1),
        (r'##\s*Consequences', 0.3),
        (r'ADR|Architecture Decision', 0.4),
        (r'we\s+decided\s+to', 0.2),
    ],
    'bug': [
        (r'##\s*Bug', 0.3),
        (r'##\s*Issue', 0.2),
        (r'##\s*Problem', 0.2),
        (r'##\s*Root\s+Cause', 0.4),
        (r'##\s*Fix|Solution', 0.2),
        (r'##\s*Steps\s+to\s+Reproduce', 0.4),
        (r'##\s*Expected\s+Behavior', 0.3),
        (r'##\s*Actual\s+Behavior', 0.3),
        (r'error|exception|crash|fail', 0.1),
    ],
    'knowledge': [
        (r'##\s*Overview', 0.2),
        (r'##\s*How\s+(to|it\s+works)', 0.3),
        (r'##\s*Reference', 0.2),
        (r'##\s*Guide', 0.3),
        (r'##\s*Tutorial', 0.3),
        (r'##\s*Examples?', 0.2),
        (r'##\s*API', 0.2),
        (r'##\s*Usage', 0.2),
    ],
    'design': [
        (r'##\s*Design', 0.3),
        (r'##\s*Architecture', 0.4),
        (r'##\s*Components?', 0.2),
        (r'##\s*Data\s*(Model|Flow|Structure)', 0.3),
        (r'##\s*UI|UX', 0.3),
        (r'##\s*Wireframe', 0.3),
        (r'##\s*System\s+Design', 0.4),
        (r'```(mermaid|plantuml)', 0.3),
    ],
}

# Keywords for tag extraction (topic -> tags)
TAG_KEYWORDS = {
    'auth': ['authentication', 'authorization', 'login', 'logout', 'oauth', 'jwt', 'session', 'password', 'credential'],
    'api': ['api', 'endpoint', 'rest', 'graphql', 'request', 'response', 'http'],
    'database': ['database', 'sql', 'query', 'schema', 'migration', 'postgres', 'mysql', 'sqlite', 'mongodb'],
    'frontend': ['frontend', 'react', 'vue', 'angular', 'component', 'ui', 'css', 'html', 'dom'],
    'backend': ['backend', 'server', 'express', 'fastapi', 'django', 'flask'],
    'testing': ['test', 'testing', 'unittest', 'pytest', 'jest', 'mock', 'coverage'],
    'deployment': ['deploy', 'deployment', 'docker', 'kubernetes', 'k8s', 'ci', 'cd', 'pipeline'],
    'performance': ['performance', 'optimization', 'cache', 'caching', 'speed', 'latency', 'benchmark'],
    'security': ['security', 'vulnerability', 'xss', 'csrf', 'injection', 'encryption'],
    'config': ['config', 'configuration', 'settings', 'environment', 'env'],
    'refactor': ['refactor', 'refactoring', 'cleanup', 'restructure', 'reorganize'],
    'docs': ['documentation', 'docs', 'readme', 'comment', 'docstring'],
}

# Scope indicators - patterns that suggest shared vs branch scope
SHARED_INDICATORS = [
    r'architecture',
    r'design\s+decision',
    r'project.wide',
    r'all\s+branches',
    r'shared\s+knowledge',
    r'team\s+reference',
    r'coding\s+standards?',
    r'style\s+guide',
    r'api\s+reference',
]

BRANCH_INDICATORS = [
    r'this\s+branch',
    r'current\s+work',
    r'wip|work.in.progress',
    r'feature.specific',
    r'branch.specific',
    r'local\s+changes',
]


def classify_document(content: str, filename_hint: Optional[str] = None) -> ClassificationResult:
    """
    Classify a document based on its content.

    Args:
        content: Full markdown content
        filename_hint: Optional filename hint for additional context

    Returns:
        ClassificationResult with type, tags, scope, and suggested filename
    """
    # Extract title
    title = extract_title(content)

    # Classify type
    doc_type, type_confidence = classify_type(content, filename_hint)

    # Extract tags
    tags = extract_tags(content, title)

    # Determine scope
    scope = infer_scope(content, tags)

    # Generate filename
    suggested_filename = generate_filename(title, doc_type, tags)

    # Determine category/path
    category = get_category_for_type(doc_type)
    if scope == 'shared':
        suggested_path = f"shared/{category}/{suggested_filename}"
    else:
        suggested_path = f"{category}/{suggested_filename}"

    # Extract summary
    summary = extract_summary(content, title)

    return ClassificationResult(
        doc_type=doc_type,
        tags=tags,
        scope=scope,
        suggested_filename=suggested_filename,
        suggested_path=suggested_path,
        title=title,
        summary=summary,
        confidence=type_confidence,
    )


def classify_type(content: str, filename_hint: Optional[str] = None) -> Tuple[str, float]:
    """
    Classify document type based on content patterns.

    Returns:
        Tuple of (type, confidence)
    """
    scores = {doc_type: 0.0 for doc_type in TYPE_CONTENT_PATTERNS}

    content_lower = content.lower()

    # Score each type based on pattern matches
    for doc_type, patterns in TYPE_CONTENT_PATTERNS.items():
        for pattern, weight in patterns:
            if re.search(pattern, content, re.IGNORECASE):
                scores[doc_type] += weight

    # Boost from filename hint
    if filename_hint:
        filename_lower = filename_hint.lower()
        for doc_type in scores:
            if doc_type in filename_lower:
                scores[doc_type] += 0.3

    # Find best match
    best_type = max(scores, key=scores.get)
    best_score = scores[best_type]

    # Normalize confidence (cap at 1.0)
    confidence = min(best_score, 1.0)

    # Fall back to 'note' if no clear match
    if confidence < 0.2:
        return 'note', 0.5

    return best_type, confidence


def extract_title(content: str) -> Optional[str]:
    """Extract title from content (first # heading)."""
    for line in content.split('\n')[:20]:
        line = line.strip()
        if line.startswith('# '):
            return line[2:].strip()
    return None


def extract_tags(content: str, title: Optional[str] = None) -> List[str]:
    """
    Extract relevant tags from content.

    Uses keyword matching and frequency analysis.
    """
    tags: Set[str] = set()
    content_lower = content.lower()

    # Check for keyword matches
    for tag, keywords in TAG_KEYWORDS.items():
        for keyword in keywords:
            # Look for word boundaries to avoid partial matches
            if re.search(rf'\b{re.escape(keyword)}\b', content_lower):
                tags.add(tag)
                break

    # Extract from explicit tags in frontmatter
    frontmatter_tags = extract_frontmatter_tags(content)
    tags.update(frontmatter_tags)

    # Extract from title
    if title:
        title_words = re.findall(r'\b[a-z]{3,}\b', title.lower())
        # Add significant title words as tags
        stopwords = {'the', 'and', 'for', 'with', 'this', 'that', 'from', 'into', 'system', 'implementation'}
        for word in title_words:
            if word not in stopwords and len(word) > 3:
                # Check if it matches any known tag keyword
                for tag, keywords in TAG_KEYWORDS.items():
                    if word in keywords:
                        tags.add(tag)

    # Limit to most relevant tags
    return sorted(list(tags))[:10]


def extract_frontmatter_tags(content: str) -> Set[str]:
    """Extract tags from YAML frontmatter."""
    tags = set()

    # Match frontmatter block
    match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if match:
        frontmatter = match.group(1)
        # Look for tags field
        tags_match = re.search(r'^tags:\s*\[([^\]]+)\]', frontmatter, re.MULTILINE)
        if tags_match:
            for tag in tags_match.group(1).split(','):
                tag = tag.strip().strip('"\'').lower()
                if tag:
                    tags.add(tag)

        # Also check for tags as list
        tags_list_match = re.search(r'^tags:\s*\n((?:\s*-\s*.+\n)+)', frontmatter, re.MULTILINE)
        if tags_list_match:
            for line in tags_list_match.group(1).split('\n'):
                if line.strip().startswith('-'):
                    tag = line.strip()[1:].strip().strip('"\'').lower()
                    if tag:
                        tags.add(tag)

    return tags


def infer_scope(content: str, tags: List[str]) -> str:
    """
    Infer whether document should be shared or branch-specific.

    Returns:
        'shared' or 'branch'
    """
    content_lower = content.lower()

    shared_score = 0
    branch_score = 0

    # Check content patterns
    for pattern in SHARED_INDICATORS:
        if re.search(pattern, content_lower):
            shared_score += 1

    for pattern in BRANCH_INDICATORS:
        if re.search(pattern, content_lower):
            branch_score += 1

    # Tags that suggest shared scope
    shared_tags = {'architecture', 'design', 'api', 'docs'}
    for tag in tags:
        if tag in shared_tags:
            shared_score += 0.5

    # Tags that suggest branch scope
    branch_tags = {'refactor', 'testing'}
    for tag in tags:
        if tag in branch_tags:
            branch_score += 0.5

    # Default to branch for session summaries
    if 'session' in content_lower or '## summary' in content_lower:
        branch_score += 1

    return 'shared' if shared_score > branch_score else 'branch'


def generate_filename(
    title: Optional[str],
    doc_type: str,
    tags: List[str],
) -> str:
    """
    Generate a descriptive filename.

    Format: YYYY-MM-DD-<slug>-<type>.md
    """
    date_str = datetime.now().strftime('%Y-%m-%d')

    # Create slug from title
    if title:
        # Clean title for filename
        slug = title.lower()
        slug = re.sub(r'[^\w\s-]', '', slug)  # Remove special chars
        slug = re.sub(r'\s+', '-', slug)  # Spaces to hyphens
        slug = re.sub(r'-+', '-', slug)  # Multiple hyphens to single
        slug = slug.strip('-')[:40]  # Limit length
    elif tags:
        # Use first few tags as slug
        slug = '-'.join(tags[:3])
    else:
        slug = 'untitled'

    # Add type suffix if not already in slug
    if doc_type not in slug:
        return f"{date_str}-{slug}-{doc_type}.md"
    else:
        return f"{date_str}-{slug}.md"


def get_category_for_type(doc_type: str) -> str:
    """Get the default category directory for a document type."""
    type_to_category = {
        'session': 'notes',
        'plan': 'plans',
        'decision': 'decisions',
        'bug': 'bugs',
        'knowledge': 'knowledge',
        'design': 'designs',
        'reference': 'reference',
        'note': 'notes',
        'script': 'scripts',
    }
    return type_to_category.get(doc_type, 'notes')


def extract_summary(content: str, title: Optional[str] = None) -> Optional[str]:
    """
    Extract a one-line summary from content.

    Tries multiple strategies:
    1. Explicit ## Summary section
    2. First paragraph after title
    3. First non-empty line
    """
    # Try to find ## Summary section
    match = re.search(
        r'^##\s*Summary\s*\n+(.+?)(?:\n\n|\n##|\Z)',
        content,
        re.MULTILINE | re.DOTALL
    )
    if match:
        summary = match.group(1).strip()
        first_line = summary.split('\n')[0].strip()
        if first_line and not first_line.startswith('#'):
            return first_line[:200]

    # Try first paragraph after title
    lines = content.split('\n')
    in_paragraph = False
    paragraph_lines = []

    for line in lines:
        line = line.strip()
        if not line:
            if in_paragraph:
                break
            continue
        if line.startswith('#'):
            in_paragraph = True
            continue
        if in_paragraph:
            if line.startswith(('*', '-', '|', '`', '>')):
                break
            paragraph_lines.append(line)
            if len(' '.join(paragraph_lines)) > 100:
                break

    if paragraph_lines:
        summary = ' '.join(paragraph_lines)
        return summary[:200]

    # Fall back to title
    return title[:200] if title else None


def suggest_improvements(content: str, result: ClassificationResult) -> List[str]:
    """
    Suggest improvements to the document for better classification.

    Returns list of suggestions.
    """
    suggestions = []

    if result.confidence < 0.5:
        suggestions.append(
            f"Add section headers like '## Summary' or '## {result.doc_type.title()}' "
            "to improve classification confidence"
        )

    if not result.title:
        suggestions.append("Add a '# Title' heading at the start of the document")

    if not result.tags:
        suggestions.append(
            "Consider adding a YAML frontmatter with tags:\n"
            "---\ntags: [tag1, tag2]\n---"
        )

    if not result.summary:
        suggestions.append("Add a '## Summary' section for better searchability")

    return suggestions
