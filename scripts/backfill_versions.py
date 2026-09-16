#!/usr/bin/env python3
"""Give version numbers to generations created before versions existed.

Older records have no ``version`` field, so they all load as version 1 and a
project's history reads as several "version 1"s. This walks each project, orders
its generations by when they were requested, numbers them from 1, and sets the
project's counter so the next take continues from there.

Safe to run more than once: a project whose numbers are already distinct is left
alone. Nothing is deleted, no audio is touched, and no configuration is changed.

    python3 scripts/backfill_versions.py            # report what would change
    python3 scripts/backfill_versions.py --apply    # write it
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "packages" / "core"))

from yue2_studio_core.store import Store  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true", help="write the changes (otherwise report only)")
    arguments = parser.parse_args()

    store = Store()
    by_project: dict[str, list] = defaultdict(list)
    for job in store.iter_jobs():
        by_project[job.project_id].append(job)

    renumbered = 0
    counters = 0
    for project_id, jobs in sorted(by_project.items()):
        jobs.sort(key=lambda job: (job.requested_at, job.id))
        try:
            project = store.get_project(project_id)
        except Exception:
            print(f"  skip {project_id}: the project record is missing")
            continue

        versions = [job.version for job in jobs]
        needs_numbers = len(set(versions)) != len(versions)
        highest = max(versions) if versions else 0

        if needs_numbers:
            print(f"  {project_id}: numbering {len(jobs)} generation(s) 1..{len(jobs)}")
            for number, job in enumerate(jobs, start=1):
                if job.version != number:
                    job.version = number
                    renumbered += 1
                    if arguments.apply:
                        store.save_job(job)
            highest = len(jobs)

        if project.generation_counter < highest:
            print(f"  {project_id}: counter {project.generation_counter} -> {highest}")
            counters += 1
            if arguments.apply:
                project.generation_counter = highest
                store.save_project(project)

    verb = "updated" if arguments.apply else "would update"
    print(f"{verb} {renumbered} generation(s) and {counters} project counter(s)")
    if not arguments.apply and (renumbered or counters):
        print("Re-run with --apply to write these changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
