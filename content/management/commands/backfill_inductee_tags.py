"""
Restores InducteeDetailPage tags to match the Dec 26, 2025 backup
(wahfdb-2025-12-26.sql), reverting an apparent tag-normalization pass made
on production sometime after that backup: most pages had their granular
multi-token tags (e.g. "bob lussow", "lussow") collapsed down to a single
full-name tag, and a "test" tag (absent from the backup entirely) got added
to ~157 pages alongside it - almost certainly a leaked QA/testing artifact.

This does a full tag SET per page (adds anything missing, removes anything
not in the backup - including "test"), not just an additive backfill like
backfill_inductee_locations.py. Source data:
restore_inductee_tags_from_1226.json.

Matches pages by slug (skips slugs not found - some are legitimate renames,
see restore_deleted_inductees.py's docstring).

Usage:
  python manage.py backfill_inductee_tags                       # dry run, report only
  python manage.py backfill_inductee_tags --commit
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from content.models import InducteeDetailPage

DEFAULT_JSON_FILE = "restore_inductee_tags_from_1226.json"


class Command(BaseCommand):
    help = "Restore InducteeDetailPage tags to match a JSON export of a DB backup"

    def add_arguments(self, parser):
        parser.add_argument("--json-file", default=DEFAULT_JSON_FILE)
        parser.add_argument(
            "--commit",
            action="store_true",
            help="Actually update pages (default dry-run)",
        )

    def handle(self, *args, **options):
        commit = options["commit"]
        path = Path(options["json_file"])
        if not path.is_file():
            raise CommandError(f"JSON file not found: {path}")

        pages = json.loads(path.read_text())

        not_found = 0
        already_ok = 0
        fixed = 0

        for entry in pages:
            slug = entry["slug"]
            page = InducteeDetailPage.objects.filter(slug=slug).first()
            if not page:
                self.stdout.write(
                    self.style.WARNING(f"! no InducteeDetailPage with slug={slug!r}")
                )
                not_found += 1
                continue

            target = set(entry["tags"])
            current = set(page.tags.names())

            if target == current:
                already_ok += 1
                continue

            to_add = target - current
            to_remove = current - target
            self.stdout.write(
                f"{page.title!r} ({slug}): +{sorted(to_add)} -{sorted(to_remove)}"
            )

            if not commit:
                fixed += 1
                continue

            page.tags.clear()
            if target:
                page.tags.add(*target)
            # ClusterTaggableManager .set()/.add() on a ParentalKey through-model
            # only stages the relation in memory - it isn't flushed to the DB
            # until the ClusterableModel is saved.
            page.save()
            fixed += 1

        self.stdout.write(
            f"\n{fixed} page(s) {'fixed' if commit else 'need fixing'}, "
            f"{already_ok} already OK, {not_found} slug(s) not found"
        )
        if not commit:
            self.stdout.write(
                self.style.WARNING("Dry run - re-run with --commit to apply.")
            )
