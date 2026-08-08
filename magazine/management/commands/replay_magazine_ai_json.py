"""
Replays previously-saved Gemini responses (media/documents-json/*.json,
written as a side effect of `process_magazine_pages`) against MagazinePage
rows, instead of re-calling the Gemini API.

Useful after a DB rollback wiped ai_* fields/MagazinePage rows for issues
that were already processed before: their JSON output usually still exists
in an older filesystem copy of media/documents-json/, so it can be replayed
for free rather than re-querying Gemini (which costs quota and produces
different wording each time).

Usage:
  python manage.py replay_magazine_ai_json                        # dry run, all unprocessed issues
  python manage.py replay_magazine_ai_json --issue 281 --issue 282
  python manage.py replay_magazine_ai_json --commit
  python manage.py replay_magazine_ai_json --source-json-dir /path/to/documents-json --commit
"""

import json
import re
import shutil
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from magazine.management.commands.process_magazine_pages import process_data
from magazine.models import MagazineIssuePage

DEFAULT_SOURCE_JSON_DIR = "/home/wahf/newer-copy-static/media/documents-json"

# Wagtail appends an 8-char base32-ish suffix like "_3YIWYov" to dedupe
# colliding filenames on upload.
COLLISION_SUFFIX_RE = re.compile(r"_[A-Za-z0-9]{7,8}$")


def normalize(stem: str) -> str:
    return COLLISION_SUFFIX_RE.sub("", stem).lower()


def find_match(pdf_stem: str, candidates: dict[str, Path]):
    if pdf_stem in candidates:
        return candidates[pdf_stem], "exact"

    normalized_target = normalize(pdf_stem)
    fuzzy = [
        (name, path)
        for name, path in candidates.items()
        if normalize(name) == normalized_target
    ]
    if len(fuzzy) == 1:
        return fuzzy[0][1], "fuzzy"
    return None, None


class Command(BaseCommand):
    help = "Replay saved Gemini JSON output against MagazinePage rows instead of re-calling the API"

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-json-dir",
            default=DEFAULT_SOURCE_JSON_DIR,
            help=f"Directory of backed-up *.json Gemini responses (default: {DEFAULT_SOURCE_JSON_DIR})",
        )
        parser.add_argument(
            "--issue",
            action="append",
            type=int,
            dest="issues",
            help=(
                "MagazineIssuePage pk to process (repeatable). Default: all "
                "issues with ai_processed_datetime still null."
            ),
        )
        parser.add_argument(
            "--commit",
            action="store_true",
            help="Actually apply matched JSON (default is dry-run only)",
        )

    def handle(self, *args, **options):
        commit = options["commit"]
        source_dir = Path(options["source_json_dir"])
        candidates = {p.stem: p for p in source_dir.glob("*.json")}

        magazines = MagazineIssuePage.objects.order_by("date")
        if options["issues"]:
            magazines = magazines.filter(pk__in=options["issues"])
        else:
            magazines = magazines.filter(ai_processed_datetime__isnull=True)

        dest_dir = Path(settings.MEDIA_ROOT) / "documents-json"

        for magazine in magazines:
            if not magazine.download_pdf:
                self.stdout.write(f"{magazine} - no download_pdf, skipping")
                continue

            pdf_stem = Path(magazine.download_pdf.file.name).stem
            match, confidence = find_match(pdf_stem, candidates)

            if not match:
                self.stdout.write(
                    self.style.WARNING(
                        f"{magazine} - no JSON match for '{pdf_stem}', skipping"
                    )
                )
                continue

            self.stdout.write(
                f"{magazine} - matched {match.name} ({confidence}) - "
                f"{magazine.pages.count()} existing page(s)"
            )

            if not commit:
                continue

            data = json.loads(match.read_text())
            if len(data) != magazine.pages.count():
                self.stdout.write(
                    self.style.WARNING(
                        f"  -> page count mismatch: json has {len(data)}, "
                        f"MagazinePage has {magazine.pages.count()}"
                    )
                )

            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_path = dest_dir / match.name
            if not dest_path.exists():
                shutil.copy2(match, dest_path)

            process_data(magazine, data)
            self.stdout.write(f"  -> applied to {magazine}")

        if not commit:
            self.stdout.write(
                self.style.WARNING("Dry run - re-run with --commit to apply.")
            )
