import pytest
from app.utils.file_filter import (
    should_exclude_path,
    get_file_priority,
    rank_and_select_files,
    PRIORITY_TIER1,
    PRIORITY_TIER2,
    PRIORITY_TIER3,
    PRIORITY_SKIP,
)


class TestShouldExcludePath:
    def test_excludes_node_modules(self):
        assert should_exclude_path("node_modules/express/index.js") is True

    def test_excludes_vendor(self):
        assert should_exclude_path("vendor/autoload.php") is True

    def test_excludes_pycache(self):
        assert should_exclude_path("__pycache__/module.cpython-310.pyc") is True

    def test_excludes_dotgit(self):
        assert should_exclude_path(".git/config") is True

    def test_excludes_venv(self):
        assert should_exclude_path(".venv/lib/python3.10/site.py") is True

    def test_allows_src_files(self):
        assert should_exclude_path("src/main.py") is False

    def test_allows_root_files(self):
        assert should_exclude_path("README.md") is False

    def test_excludes_binary_extensions(self):
        assert should_exclude_path("images/logo.png") is True
        assert should_exclude_path("fonts/arial.woff2") is True

    def test_excludes_lock_files(self):
        assert should_exclude_path("package-lock.json") is True
        assert should_exclude_path("poetry.lock") is True
        assert should_exclude_path("yarn.lock") is True

    def test_excludes_min_files(self):
        assert should_exclude_path("dist/app.min.js") is True
        assert should_exclude_path("styles/main.min.css") is True


class TestGetFilePriority:
    def test_readme_is_tier1(self):
        assert get_file_priority("README.md") == PRIORITY_TIER1

    def test_readme_rst_is_tier1(self):
        assert get_file_priority("README.rst") == PRIORITY_TIER1

    def test_package_json_is_tier2(self):
        assert get_file_priority("package.json") == PRIORITY_TIER2

    def test_pyproject_toml_is_tier2(self):
        assert get_file_priority("pyproject.toml") == PRIORITY_TIER2

    def test_dockerfile_is_tier2(self):
        assert get_file_priority("Dockerfile") == PRIORITY_TIER2

    def test_github_workflow_is_tier2(self):
        assert get_file_priority(".github/workflows/ci.yml") == PRIORITY_TIER2

    def test_main_py_is_tier3(self):
        assert get_file_priority("main.py") == PRIORITY_TIER3

    def test_src_file_is_tier3(self):
        assert get_file_priority("src/app.py") == PRIORITY_TIER3

    def test_deep_nested_file_is_tier3(self):
        assert get_file_priority("src/utils/helpers/format.py") == PRIORITY_TIER3

    def test_test_files_deprioritized(self):
        p1 = get_file_priority("src/app.py")
        p2 = get_file_priority("tests/test_app.py")
        assert p2 > p1  # Higher number = lower priority


class TestRankAndSelectFiles:
    def test_selects_within_budget(self):
        files = [
            {"path": "README.md", "size": 500},
            {"path": "src/main.py", "size": 300},
            {"path": "src/utils.py", "size": 200},
        ]
        selected = rank_and_select_files(files, max_chars=900)
        paths = [f["path"] for f in selected]
        assert "README.md" in paths

    def test_respects_budget(self):
        files = [
            {"path": "README.md", "size": 600},
            {"path": "src/main.py", "size": 600},
        ]
        selected = rank_and_select_files(files, max_chars=700)
        assert len(selected) == 1

    def test_readme_selected_first(self):
        files = [
            {"path": "src/main.py", "size": 100},
            {"path": "README.md", "size": 100},
            {"path": "package.json", "size": 100},
        ]
        selected = rank_and_select_files(files, max_chars=10000)
        assert selected[0]["path"] == "README.md"

    def test_empty_list(self):
        selected = rank_and_select_files([], max_chars=10000)
        assert selected == []

    def test_skips_excluded_files(self):
        files = [
            {"path": "README.md", "size": 100},
            {"path": "node_modules/foo.js", "size": 100},
        ]
        selected = rank_and_select_files(files, max_chars=10000)
        paths = [f["path"] for f in selected]
        assert "node_modules/foo.js" not in paths
