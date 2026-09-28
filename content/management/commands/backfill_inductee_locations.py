"""
Re-attaches InducteeDetailPage -> LocationTag relations that were lost -
these are NOT deleted pages (the pages themselves are fine), just the
"locations" tagging on them (used for the Hall of Fame map feature).

The Dec 26, 2025 backup (wahfdb-2025-12-26.sql) has 164 page/location links
across 68 distinct LocationTag rows; current production has only a handful.
Source data: restore_inductee_locations_from_1226.json, generated from that
backup (see restore_deleted_inductees.py for the sibling "recreate missing
pages entirely" command - this one only touches the location tagging on
pages that already exist).

Matches pages by slug (skips slugs not found - some are legitimate renames,
see restore_deleted_inductees.py's docstring) and LocationTag rows by their
slug-like `name` field, creating any that don't already exist using the
lat/long captured in the backup. Idempotent: pages that already have a given
location tagged are left alone.

Usage:
  python manage.py backfill_inductee_locations                       # dry run, report only
  python manage.py backfill_inductee_locations --commit
"""

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from content.models import InducteeDetailPage, LocationTag

DEFAULT_JSON_FILE = "restore_inductee_locations_from_1226.json"


class Command(BaseCommand):
    help = "Re-attach InducteeDetailPage locations lost from production, from a JSON export of a DB backup"

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
        link_count = 0

        for entry in pages:
            slug = entry["slug"]
            page = InducteeDetailPage.objects.filter(slug=slug).first()
            if not page:
                self.stdout.write(
                    self.style.WARNING(f"! no InducteeDetailPage with slug={slug!r}")
                )
                not_found += 1
                continue

            existing_names = set(page.locations.values_list("name", flat=True))
            missing = [
                loc for loc in entry["locations"] if loc["name"] not in existing_names
            ]

            if not missing:
                already_ok += 1
                continue

            self.stdout.write(
                f"{page.title!r} ({slug}): missing {[m['location_name'] for m in missing]}"
            )

            if not commit:
                fixed += 1
                link_count += len(missing)
                continue

            tags = []
            for loc in missing:
                tag, created = LocationTag.objects.get_or_create(
                    name=loc["name"],
                    defaults={
                        "location_name": loc["location_name"],
                        "latitude": loc["latitude"],
                        "longitude": loc["longitude"],
                    },
                )
                if created:
                    self.stdout.write(f"    + created LocationTag {loc['name']!r}")
                tags.append(tag)

            page.locations.add(*tags)
            # ClusterTaggableManager .add() on a ParentalKey through-model
            # only stages the relation in memory - it isn't flushed to the
            # DB until the ClusterableModel is saved.
            page.save()
            self.stdout.write(
                self.style.SUCCESS(f"    -> attached {len(tags)} location(s)")
            )
            fixed += 1
            link_count += len(tags)

        self.stdout.write(
            f"\n{fixed} page(s) {'fixed' if commit else 'need fixing'} "
            f"({link_count} link(s)), {already_ok} already OK, {not_found} slug(s) not found"
        )
        if not commit:
            self.stdout.write(
                self.style.WARNING("Dry run - re-run with --commit to apply.")
            )
