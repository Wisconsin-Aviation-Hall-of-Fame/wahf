"""
Management command to find and fix malformed image embeds in rich text content.

A Wagtail RichTextBlock image embed should look like:
  <embed embedtype="image" id="123" format="fullwidth" alt="..."/>

If the `id` attribute is missing, Wagtail's reference index update will crash
with: KeyError: 'id'

This command scans all rich text content and removes any image embeds missing
the `id` attribute.

Usage:
  python manage.py fix_richtext_image_embeds          # dry run, report only
  python manage.py fix_richtext_image_embeds --fix    # apply fixes
"""

import json
import re

from django.core.management.base import BaseCommand

from content.models import (
    ArticleAuthor,
    ArticlePage,
    FourtyYearsFourtyStoriesListPage,
    FreeformPage,
    InducteeDetailPage,
    KohnProjectPage,
    ScholarshipPage,
    ScholarshipRecipient,
)

# Matches <embed embedtype="image" .../> where id= is absent
MALFORMED_IMAGE_EMBED_RE = re.compile(
    r'<embed\b(?=[^>]*\bembedtype=["\']image["\'])(?![^>]*\bid=["\'])[^>]*/>'
)


def find_malformed_embeds(html: str) -> list[str]:
    return MALFORMED_IMAGE_EMBED_RE.findall(html)


def remove_malformed_embeds(html: str) -> str:
    return MALFORMED_IMAGE_EMBED_RE.sub("", html)


class Command(BaseCommand):
    help = (
        "Find (and optionally remove) image embeds missing an id attribute in rich text"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--fix",
            action="store_true",
            help="Remove malformed image embeds (default is dry-run only)",
        )

    def handle(self, *args, **options):
        fix = options["fix"]
        total_issues = 0

        # --- RichTextField models ---
        rich_text_fields = [
            (ArticleAuthor, "about_blurb", "pk"),
            (KohnProjectPage, "fundraising_status", "pk"),
            (KohnProjectPage, "business_donors", "pk"),
            (KohnProjectPage, "individual_donors", "pk"),
            (KohnProjectPage, "silent_auction_donors", "pk"),
            (KohnProjectPage, "special_donors", "pk"),
            (ScholarshipRecipient, "blurb", "pk"),
        ]

        for ModelClass, field_name, id_field in rich_text_fields:
            for instance in ModelClass.objects.all():
                html = getattr(instance, field_name) or ""
                matches = find_malformed_embeds(html)
                if matches:
                    total_issues += len(matches)
                    self.stdout.write(
                        self.style.WARNING(
                            f"{ModelClass.__name__} pk={instance.pk} field={field_name}: "
                            f"{len(matches)} malformed embed(s): {matches}"
                        )
                    )
                    if fix:
                        setattr(instance, field_name, remove_malformed_embeds(html))
                        instance.save(update_fields=[field_name])
                        self.stdout.write("  -> fixed")

        # --- StreamField models (paragraph RichTextBlock) ---
        stream_field_models = [
            (ArticlePage, "body"),
            (FourtyYearsFourtyStoriesListPage, "body"),
            (ScholarshipPage, "body"),
            (InducteeDetailPage, "body"),
            (FreeformPage, "body"),
        ]

        for ModelClass, field_name in stream_field_models:
            for instance in ModelClass.objects.all():
                raw = (
                    instance.__class__.objects.filter(pk=instance.pk)
                    .values_list(field_name, flat=True)
                    .first()
                )
                if not raw:
                    continue

                # use_json_field=True returns a Python list; older fields return a string
                if isinstance(raw, str):
                    try:
                        blocks = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                else:
                    blocks = raw

                if not isinstance(blocks, list):
                    continue

                changed = False
                for block in blocks:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") != "paragraph":
                        continue
                    value = block.get("value", "")
                    if not isinstance(value, str):
                        continue
                    matches = find_malformed_embeds(value)
                    if matches:
                        total_issues += len(matches)
                        self.stdout.write(
                            self.style.WARNING(
                                f"{ModelClass.__name__} pk={instance.pk} field={field_name} "
                                f"block id={block.get('id', '?')}: "
                                f"{len(matches)} malformed embed(s): {matches}"
                            )
                        )
                        if fix:
                            block["value"] = remove_malformed_embeds(value)
                            changed = True

                if fix and changed:
                    # use_json_field=True expects a Python list; string fields expect JSON
                    save_value = (
                        blocks if not isinstance(raw, str) else json.dumps(blocks)
                    )
                    ModelClass.objects.filter(pk=instance.pk).update(
                        **{field_name: save_value}
                    )
                    self.stdout.write(
                        f"  -> fixed {ModelClass.__name__} pk={instance.pk}"
                    )

        if total_issues == 0:
            self.stdout.write(self.style.SUCCESS("No malformed image embeds found."))
        elif not fix:
            self.stdout.write(
                self.style.WARNING(
                    f"\nFound {total_issues} malformed embed(s). "
                    f"Run with --fix to remove them."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(f"\nFixed {total_issues} malformed embed(s).")
            )
