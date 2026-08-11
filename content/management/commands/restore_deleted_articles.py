"""
Recreates ArticlePages that were accidentally deleted (unrelated to the
"40 Years, 40 Stories" batch) from a JSON export pulled out of an older
pg_dump backup (see restore_deleted_articles.json, generated from
wahf_20260805.dump).

The image (archives.WAHFImage) and author (content.ArticleAuthor) tables
were NOT affected by the deletion, so this only needs to recreate the
ArticlePage rows themselves - images/authors are resolved by title/name
against whatever database this runs against, not by trusting the raw
foreign key ids from the backup (those ids may not line up between the
scratch restore database and wherever this command is actually run).

Restored pages are recreated with their original `live` status (these are
genuinely-published articles being restored, not new drafts).

Usage:
  python manage.py restore_deleted_articles                       # dry run, report only
  python manage.py restore_deleted_articles --commit
  python manage.py restore_deleted_articles --json-file restore_deleted_articles.json --commit
"""

import json
import uuid
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from archives.models import WAHFImage
from content.models import ArticleAuthor, ArticleListPage, ArticlePage

DEFAULT_JSON_FILE = "restore_deleted_articles.json"


class Command(BaseCommand):
    help = (
        "Recreate ArticlePages deleted by accident, from a JSON export of a DB backup"
    )

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
            f"Parent ArticleListPage: {parent_page.title!r} ({parent_page.url})"
        )

        articles = json.loads(path.read_text())
        for article in articles:
            self.process_article(article, parent_page, commit)

        if not commit:
            self.stdout.write(
                self.style.WARNING("\nDry run - re-run with --commit to create pages.")
            )

    def get_parent_page(self, parent_slug):
        qs = ArticleListPage.objects.all()
        if parent_slug:
            page = qs.filter(slug=parent_slug).first()
            if not page:
                raise CommandError(f"No ArticleListPage with slug={parent_slug!r}")
            return page
        count = qs.count()
        if count == 0:
            raise CommandError("No ArticleListPage exists")
        if count > 1:
            raise CommandError("Multiple ArticleListPages exist - pass --parent-slug")
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

    def resolve_body(self, body):
        resolved = []
        for block in body:
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

    def process_article(self, article, parent_page, commit):
        slug, title = article["slug"], article["title"]
        self.stdout.write(f"\n{title!r} ({slug})")

        existing = ArticlePage.objects.filter(slug=slug).first()
        if existing:
            self.stdout.write(f"    -> already exists (id={existing.pk}), skipping")
            return

        image = self.resolve_image(article["image_title"])
        body = self.resolve_body(article["body"])

        author = None
        if article["author_name"]:
            author, _ = ArticleAuthor.objects.get_or_create(name=article["author_name"])
            if article["author_email"] and not author.contact_email:
                author.contact_email = article["author_email"]
                if commit:
                    author.save()

        self.stdout.write(
            f"    live={article['live']} author={article['author_name']!r} "
            f"image={article['image_title']!r} tags={article['tags']} "
            f"{len(body)} body block(s)"
        )

        if not commit:
            return

        with transaction.atomic():
            page = ArticlePage(
                title=title,
                slug=slug,
                subtitle=article["subtitle"] or "",
                author=author,
                date=article["date"],
                website_publish_date=article["website_publish_date"],
                image=image,
                short_description=article["short_description"] or "",
                top_badge=article["top_badge"] or "",
                body=body,
                live=article["live"],
            )
            parent_page.add_child(instance=page)
            revision = page.save_revision()
            if article["live"]:
                revision.publish()

            if article["tags"]:
                page.tags.add(*article["tags"])

        self.stdout.write(
            self.style.SUCCESS(f"    -> created ArticlePage id={page.pk}")
        )
