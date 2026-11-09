"""Backwards-compatible entry point. Use:  python validator.py --project <project_id>

Without arguments, validates the active project.
"""
import sys

import config
from project_manager import ProjectManager
import validator

if __name__ == "__main__":
    if len(sys.argv) == 1:
        active = ProjectManager(config.ROOT_DIR).get_active_project(with_stats=False)
        if not active:
            sys.exit("Chưa có dự án nào.")
        sys.argv += ["--project", active["id"]]
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    validator.main()
