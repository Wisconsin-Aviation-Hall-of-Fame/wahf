"""
Recreates InducteeDetailPages that were accidentally deleted, from a JSON
export pulled out of an older pg_dump backup (see
restore_inductees_from_1226.json, generated from wahfdb-2025-12-26.sql).

The image (archives.WAHFImage) table was NOT affected by the deletion, but
titles have since been auto-renamed for some images (Wagtail derives a
title from the filename on upload, and re-uploads/re-titling since the
backup changed several) - so images are resolved by title against whatever
database this runs against, using the *current* title, not the backup's.
LocationTag rows are resolved by their slug-like `name` field, creating any
that don't already exist (using the lat/long captured in the backup).

Restored pages are recreated with their original `live` status.

Usage:
  python manage.py restore_deleted_inductees                       # dry run, report only
  python manage.py restore_deleted_inductees --commit
"""

import json
import uuid
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from archives.models import WAHFImage
from content.models import InducteeDetailPage, InducteeListPage, LocationTag

DEFAULT_JSON_FILE = "restore_inductees_from_1226.json"


class Command(BaseCommand):
    help = "Recreate InducteeDetailPages deleted by accident, from a JSON export of a DB backup"

    def add_arguments(self, parser):
        parser.add_argument("--json-file", default=DEFAULT_JSON_FILE)
        parser.add_argument("--parent-slug", default=None)
        parser.add_argument(
            "--commit",
            action="store_true",
            help="Actually create pages (default dry-run)",
        )

    def handle(self, *args, **options):
        commit = options["commit"]
        path = Path(options["json_file"])
        if not path.is_file():
            raise CommandError(f"JSON file not found: {path}")

        parent_page = self.get_parent_page(options["parent_slug"])
        self.stdout.write(
            f"Parent InducteeListPage: {parent_page.title!r} ({parent_page.url})"
        )

        inductees = json.loads(path.read_text())
        for inductee in inductees:
            self.process_inductee(inductee, parent_page, commit)

        if not commit:
            self.stdout.write(
                self.style.WARNING("\nDry run - re-run with --commit to create pages.")
            )

    def get_parent_page(self, parent_slug):
        qs = InducteeListPage.objects.all()
        if parent_slug:
            page = qs.filter(slug=parent_slug).first()
            if not page:
                raise CommandError(f"No InducteeListPage with slug={parent_slug!r}")
            return page
        count = qs.count()
        if count == 0:
            raise CommandError("No InducteeListPage exists")
        if count > 1:
            raise CommandError("Multiple InducteeListPages exist - pass --parent-slug")
        return qs.first()

    def resolve_image(self, title):
        if not title:
            return None
        image = WAHFImage.objects.filter(title=title).first()
        if not image:
            self.stdout.write(
                self.style.WARNING(f"    ! no WAHFImage titled {title!r}")
            )
        return image

    def resolve_body(self, blocks):
        resolved = []
        for block in blocks:
            block = dict(block)
            if block["type"] == "image":
                value = block["value"]
                title = value["_image_title"] if isinstance(value, dict) else None
                image = self.resolve_image(title)
                if not image:
                    continue
                block["value"] = image.pk
            block.setdefault("id", str(uuid.uuid4()))
            resolved.append(block)
        return resolved

    def resolve_locations(self, locations, commit):
        tags = []
        for loc in locations:
            if not commit:
                exists = LocationTag.objects.filter(name=loc["name"]).exists()
                if not exists:
                    self.stdout.write(f"    (would create LocationTag {loc['name']!r})")
                continue
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
        return tags

    def process_inductee(self, inductee, parent_page, commit):
        slug, title = inductee["slug"], inductee["title"]
        self.stdout.write(f"\n{title!r} ({slug})")

        existing = InducteeDetailPage.objects.filter(slug=slug).first()
        if existing:
            self.stdout.write(f"    -> already exists (id={existing.pk}), skipping")
            return

        photo = self.resolve_image(inductee["photo_title"])
        body = self.resolve_body(inductee["body"])
        gallery = self.resolve_body(inductee["gallery"])

        self.stdout.write(
            f"    live={inductee['live']} photo={inductee['photo_title']!r} "
            f"locations={[loc['location_name'] for loc in inductee['locations']]} "
            f"tags={inductee['tags']} {len(body)} body block(s), "
            f"{len(gallery)} gallery block(s)"
        )

        if not commit:
            self.resolve_locations(inductee["locations"], commit=False)
            return

        location_tags = self.resolve_locations(inductee["locations"], commit=True)

        with transaction.atomic():
            page = InducteeDetailPage(
                title=title,
                slug=slug,
                name=inductee["name"],
                first_name=inductee["first_name"],
                last_name=inductee["last_name"],
                tagline=inductee["tagline"] or "",
                body=body,
                gallery=gallery,
                inducted_date=inductee["inducted_date"],
                born_date=inductee["born_date"],
                died_date=inductee["died_date"],
                born_year=inductee["born_year"],
                died_year=inductee["died_year"],
                photo=photo,
                live=inductee["live"],
            )
            parent_page.add_child(instance=page)
            revision = page.save_revision()
            if inductee["live"]:
                revision.publish()

            if inductee["tags"]:
                page.tags.add(*inductee["tags"])
            if location_tags:
                page.locations.add(*location_tags)
            # ClusterTaggableManager .add() on a ParentalKey through-model only
            # stages the relation in memory - it isn't flushed to the DB until
            # the ClusterableModel is saved.
            if inductee["tags"] or location_tags:
                page.save()

        self.stdout.write(
            self.style.SUCCESS(f"    -> created InducteeDetailPage id={page.pk}")
        )
