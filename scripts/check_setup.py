#!/usr/bin/env python3
"""Read-only local checks. Never launches Codex workers or Google tools."""
import importlib
from pathlib import Path
import shutil
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

def main():
    if sys.version_info < (3, 11):
        raise SystemExit("Python 3.11 or newer is required.")
    if sys.platform == "win32":
        raise SystemExit("Native Windows is unsupported; use macOS/Linux.")
    modules = sorted(path.stem for path in ROOT.glob("*.py"))
    for name in modules:
        importlib.import_module(name)
    required = ["01_landscape.md", "02_inventory.md", "03_extraction.md", "04_buying.md",
                "05_companies.md", "06_people.md", "07_report.md", "research_worker.md",
                "analysis_worker.md", "analysis_compact_worker.md", "resolve_company_profiles.md",
                "taxonomy_first.md", "global_synthesis.md", "research_listing.md",
                "research_resolution.md", "research_review.md", "research_extract.md",
                "research_listing_only.md", "research_discovery_legacy.md",
                "research_record.md", "research_checkpoints.md"]
    for name in required:
        assert (ROOT / "prompts" / name).is_file(), name
    with zipfile.ZipFile(ROOT / "assets/case_studies_seed.xlsx") as archive:
        assert archive.testzip() is None
    print(f"PASS: Python, {len(modules)} runtime imports, {len(required)} prompts and seed ZIP.")
    print("Codex CLI found on PATH." if shutil.which("codex") else
          "EXTERNAL PREREQUISITE MISSING: install/authenticate Codex CLI before real research.")
    print("Authentication and live Google-tool compatibility were not tested.")

if __name__ == "__main__":
    main()
