"""File filtering and priority ranking for GitHub repository analysis."""

PRIORITY_TIER1 = 1   # README, top-level docs
PRIORITY_TIER2 = 2   # Config files, package manifests
PRIORITY_TIER3 = 3   # Source code files
PRIORITY_TIER4 = 4   # Test files, docs, examples
PRIORITY_SKIP = 99   # Should not be fetched

# Directories to completely skip
EXCLUDED_DIRS: set[str] = {
    "node_modules", "vendor", ".git", "dist", "build", "__pycache__",
    ".venv", "venv", "env", ".idea", ".vscode", ".tox", ".mypy_cache",
    ".pytest_cache", ".next", ".nuxt", "target", "bin", "obj",
    "coverage", ".coverage", "htmlcov", ".eggs", ".gradle",
    ".terraform", ".serverless",
}

# File extensions to skip (binary/generated)
EXCLUDED_EXTENSIONS: set[str] = {
    # Images
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".bmp", ".webp",
    # Fonts
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    # Media
    ".mp3", ".mp4", ".avi", ".mov", ".wav",
    # Archives
    ".zip", ".tar", ".gz", ".bz2", ".rar", ".7z",
    # Documents
    ".pdf", ".doc", ".docx", ".xls", ".xlsx",
    # Compiled
    ".exe", ".dll", ".so", ".dylib", ".pyc", ".pyo", ".class", ".o",
    ".wasm",
    # Data
    ".sqlite", ".db",
    # Source maps
    ".map",
}

# Specific filenames to skip (lock files, generated)
EXCLUDED_FILENAMES: set[str] = {
    "package-lock.json", "yarn.lock", "poetry.lock", "Cargo.lock",
    "Gemfile.lock", "composer.lock", "go.sum", "pnpm-lock.yaml",
    "npm-shrinkwrap.json", ".DS_Store", "Thumbs.db",
}

# Tier 1: README and top-level docs (highest priority)
TIER1_FILENAMES: set[str] = {
    "README.md", "README.rst", "README.txt", "README",
}

# Tier 2: Config/manifest files
TIER2_FILENAMES: set[str] = {
    "package.json", "pyproject.toml", "setup.py", "setup.cfg",
    "Cargo.toml", "go.mod", "pom.xml", "build.gradle", "build.gradle.kts",
    "Makefile", "CMakeLists.txt", "Dockerfile", "docker-compose.yml",
    "docker-compose.yaml", "requirements.txt", "Gemfile", "Pipfile",
    "tsconfig.json", "tox.ini", ".eslintrc.json", ".eslintrc.js",
    "webpack.config.js", "vite.config.ts", "vite.config.js",
    "next.config.js", "next.config.mjs",
}

# Tier 2: Directory patterns for config files
TIER2_DIR_PATTERNS: list[str] = [
    ".github/workflows/",
]

# Tier 3: Entry point filenames (higher priority within tier 3)
TIER3_ENTRY_POINTS: set[str] = {
    "main.py", "app.py", "index.ts", "index.js", "main.ts", "main.js",
    "server.py", "server.ts", "server.js", "main.go", "main.rs",
    "lib.rs", "mod.rs", "index.py",
}

# Source code extensions
SOURCE_EXTENSIONS: set[str] = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".go", ".rs", ".java",
    ".kt", ".rb", ".php", ".c", ".cpp", ".h", ".hpp", ".cs",
    ".swift", ".scala", ".clj", ".ex", ".exs", ".hs", ".lua",
    ".r", ".R", ".jl", ".sh", ".bash", ".zsh", ".fish",
    ".yaml", ".yml", ".toml", ".json", ".xml", ".html", ".css",
    ".scss", ".less", ".sql", ".graphql", ".proto", ".tf",
    ".md", ".rst", ".txt",
}


def should_exclude_path(path: str) -> bool:
    """Check if a file path should be excluded from analysis."""
    parts = path.split("/")

    # Check directory exclusions
    for part in parts[:-1]:  # All parts except filename
        if part in EXCLUDED_DIRS:
            return True

    filename = parts[-1]

    # Check excluded filenames
    if filename in EXCLUDED_FILENAMES:
        return True

    # Check excluded extensions
    dot_idx = filename.rfind(".")
    if dot_idx != -1:
        ext = filename[dot_idx:].lower()
        if ext in EXCLUDED_EXTENSIONS:
            return True

    # Check minified files
    if filename.endswith(".min.js") or filename.endswith(".min.css"):
        return True

    # Check chunk files
    if ".chunk." in filename:
        return True

    return False


def get_file_priority(path: str) -> int:
    """Return priority tier for a file (lower number = higher priority)."""
    parts = path.split("/")
    filename = parts[-1]

    # Tier 1: README
    if filename.upper().startswith("README"):
        return PRIORITY_TIER1

    # Tier 2: Config/manifest files
    if filename in TIER2_FILENAMES:
        return PRIORITY_TIER2

    # Tier 2: GitHub workflows and similar config dirs
    for pattern in TIER2_DIR_PATTERNS:
        if path.startswith(pattern):
            return PRIORITY_TIER2

    # Check if it's a source file at all
    dot_idx = filename.rfind(".")
    ext = filename[dot_idx:].lower() if dot_idx != -1 else ""

    if ext not in SOURCE_EXTENSIONS and filename not in TIER3_ENTRY_POINTS:
        return PRIORITY_SKIP

    # Tier 4: Test files (lower priority than regular source)
    lower_path = path.lower()
    if (
        "/test" in lower_path
        or "/tests" in lower_path
        or "/spec" in lower_path
        or filename.startswith("test_")
        or filename.endswith("_test.py")
        or filename.endswith(".test.js")
        or filename.endswith(".test.ts")
        or filename.endswith(".spec.js")
        or filename.endswith(".spec.ts")
    ):
        return PRIORITY_TIER4

    # Tier 3: Regular source files
    return PRIORITY_TIER3


def _sort_key(file_info: dict) -> tuple:
    """Sort key: (priority, depth, size). Shallower and smaller files first."""
    path = file_info["path"]
    priority = get_file_priority(path)
    depth = path.count("/")
    size = file_info.get("size", 0)
    # Entry points get a slight boost within their tier
    filename = path.split("/")[-1]
    is_entry = 0 if filename in TIER3_ENTRY_POINTS else 1
    return (priority, is_entry, depth, size)


def rank_and_select_files(
    files: list[dict], max_chars: int
) -> list[dict]:
    """Rank files by priority and select within character budget.

    Args:
        files: List of dicts with "path" and "size" keys.
        max_chars: Maximum total characters to select.

    Returns:
        Ordered list of file dicts to fetch, within budget.
    """
    # Filter out excluded files
    eligible = [f for f in files if not should_exclude_path(f["path"])]

    # Filter out files with non-source extensions that aren't config
    eligible = [f for f in eligible if get_file_priority(f["path"]) != PRIORITY_SKIP]

    # Sort by priority
    eligible.sort(key=_sort_key)

    # Select within budget
    selected = []
    total_chars = 0
    for f in eligible:
        estimated_chars = f.get("size", 0)
        if total_chars + estimated_chars > max_chars and selected:
            continue  # Skip but keep trying smaller files
        selected.append(f)
        total_chars += estimated_chars

    return selected
