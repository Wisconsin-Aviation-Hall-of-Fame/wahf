"""
Management command to recover orphaned image/document files after the
production database was rolled back.

A filesystem-level copy of media/ taken before the rollback survived on the
server even though the DB rows referencing those files did not. This command
copies any image/document files present in that recovery copy but missing
from the live media directory into place, and creates matching Wagtail
Image/Document rows for them so they show up in the admin media libraries.

Since the original titles/captions were only ever stored in the lost DB
rows, imported items are titled from their filename and get no other
metadata. Files are processed oldest-to-newest by filesystem modification
time, and each row's created_at is set from that same mtime, so the admin's
chronological ordering reflects real upload history rather than import
order - this is meant to help match recovered files back to the content
they belonged to.

Usage:
  python manage.py import_recovered_media                     # dry run, report only
  python manage.py import_recovered_media --commit             # copy files + create rows
  python manage.py import_recovered_media --source /path/to/media --commit
"""

import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from django.core.management.base import BaseCommand
from wagtail.documents import get_document_model
from wagtail.images import get_image_model

IMAGE_SUBDIR = "original_images"
DOCUMENT_SUBDIR = "documents"
DEFAULT_SOURCE = "/home/wahf/newer-copy-static/media"


@dataclass
class Candidate:
    path: Path
    mtime: datetime


def titleize(filename: str) -> str:
    return Path(filename).stem.replace("_", " ").replace("-", " ").strip()


def collect_candidates(source_dir: Path, dest_dir: Path) -> list[Candidate]:
    if not source_dir.is_dir():
        return []

    existing = {p.name for p in dest_dir.iterdir()} if dest_dir.is_dir() else set()
    candidates = [
        Candidate(
            path=p, mtime=datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)
        )
        for p in source_dir.iterdir()
        if p.is_file() and p.name not in existing
    ]
    candidates.sort(key=lambda c: c.mtime)
    return candidates


class Command(BaseCommand):
    help = "Import orphaned image/document files (from a pre-rollback media copy) into Wagtail"

    def add_arguments(self, parser):
        parser.add_argument(
            "--source",
            default=DEFAULT_SOURCE,
            help=f"Path to the recovered media/ directory (default: {DEFAULT_SOURCE})",
        )
        parser.add_argument(
            "--commit",
            action="store_true",
            help="Actually copy files and create rows (default is dry-run only)",
        )

    def handle(self, *args, **options):
        source = Path(options["source"])
        commit = options["commit"]

        image_model = get_image_model()
        document_model = get_document_model()

        media_root = Path(image_model._meta.get_field("file").storage.location)

        self.import_images(
            candidates=collect_candidates(
                source / IMAGE_SUBDIR, media_root / IMAGE_SUBDIR
            ),
            dest_dir=media_root / IMAGE_SUBDIR,
            image_model=image_model,
            commit=commit,
        )
        self.import_documents(
            candidates=collect_candidates(
                source / DOCUMENT_SUBDIR, media_root / DOCUMENT_SUBDIR
            ),
            dest_dir=media_root / DOCUMENT_SUBDIR,
            document_model=document_model,
            commit=commit,
        )

    def import_images(self, candidates, dest_dir, image_model, commit):
        if not candidates:
            self.stdout.write("No orphaned images to import.")
            return

        self.stdout.write(f"\n{len(candidates)} image(s) to import (oldest first):")
        created = 0
        for c in candidates:
            rel_path = f"{IMAGE_SUBDIR}/{c.path.name}"
            self.stdout.write(f"  {c.mtime.date()}  {c.path.name}")

            if not commit:
                continue

            if image_model.objects.filter(file=rel_path).exists():
                self.stdout.write("    -> skipped (row already exists)")
                continue

            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_path = dest_dir / c.path.name
            if not dest_path.exists():
                shutil.copy2(c.path, dest_path)

            from PIL import Image as PILImage

            with PILImage.open(dest_path) as pil_image:
                width, height = pil_image.size

            image = image_model(
                title=titleize(c.path.name),
                width=width,
                height=height,
                created_at=c.mtime,
            )
            image.file.name = rel_path
            image.save()
            created += 1
            self.stdout.write(f"    -> created WAHFImage id={image.pk}")

        if commit:
            self.stdout.write(self.style.SUCCESS(f"Created {created} image row(s)."))
        else:
            self.stdout.write(
                self.style.WARNING("Dry run - re-run with --commit to import.")
            )

    def import_documents(self, candidates, dest_dir, document_model, commit):
        if not candidates:
            self.stdout.write("No orphaned documents to import.")
            return

        self.stdout.write(f"\n{len(candidates)} document(s) to import (oldest first):")
        created = 0
        for c in candidates:
            rel_path = f"{DOCUMENT_SUBDIR}/{c.path.name}"
            self.stdout.write(f"  {c.mtime.date()}  {c.path.name}")

            if not commit:
                continue

            if document_model.objects.filter(file=rel_path).exists():
                self.stdout.write("    -> skipped (row already exists)")
                continue

            dest_dir.mkdir(parents=True, exist_ok=True)
            dest_path = dest_dir / c.path.name
            if not dest_path.exists():
                shutil.copy2(c.path, dest_path)

            document = document_model(
                title=titleize(c.path.name),
                created_at=c.mtime,
            )
            document.file.name = rel_path
            document.save()
            created += 1
            self.stdout.write(f"    -> created Document id={document.pk}")

        if commit:
            self.stdout.write(self.style.SUCCESS(f"Created {created} document row(s)."))
        else:
            self.stdout.write(
                self.style.WARNING("Dry run - re-run with --commit to import.")
            )
