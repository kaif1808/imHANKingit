from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_canonical_entrypoints_exist_at_root():
    expected = [
        "htm_classification.py",
        "generate_choropleths.py",
        "cumulative_irf_heterogeneity.py",
    ]
    for rel_path in expected:
        assert (REPO_ROOT / rel_path).exists(), f"Missing canonical entrypoint: {rel_path}"


def test_scripts_folders_exist():
    expected_dirs = [
        "scripts/data_prep",
        "scripts/reporting",
        "scripts/utils",
        "analysis",
        "archive/legacy",
    ]
    for rel_path in expected_dirs:
        assert (REPO_ROOT / rel_path).is_dir(), f"Missing scripts folder: {rel_path}"


def test_root_script_clutter_guardrail():
    # Keep root focused on canonical entrypoints and avoid reintroducing loose scripts.
    allowed_root_scripts = {
        "htm_classification.py",
        "generate_choropleths.py",
        "cumulative_irf_heterogeneity.py",
        "pnad_faixa_pretreat.py",
    }
    root_scripts = {
        path.name for path in REPO_ROOT.iterdir()
        if path.is_file() and path.suffix in {".py", ".R"}
    }
    assert root_scripts == allowed_root_scripts
