"""
Recreates ArticlePages for stories recovered via a live-page web scrape
(wahf_recovered_articles.json), for articles that returned 404 in the CMS
but were still reachable at the time of the scrape (e.g. via CDN/edge cache
after their underlying database rows were lost).

Unlike restore_lost_articles.py (verbatim Wayback HTML) and
restore_deleted_articles.py (verbatim DB backup rows), this source is
LLM-extracted/cleaned text, not exact original markup - see the JSON's own
"recovery_note" field. Treat body wording as approximate. Images are matched
against WAHFImage by title (exact, then a single-candidate prefix fallback)
since the JSON's "filename_label" values are described as approximate too;
any image that can't be matched is left out of the body and reported on
stdout instead, with its caption/credit, so it can be sourced/uploaded and
added by hand later.

Restored pages are ALWAYS created as unpublished drafts regardless of any
original status, since content fidelity isn't guaranteed - review before
publishing. All matched images are placed together right after the first
paragraph (the source has no per-image position data to preserve).

FourtyYearsStory rows are only created for slugs present in RESTORE_SCHEDULE
below (the continuation of the same "40 Years, 40 Stories" posting schedule
used by restore_lost_articles.py, numbers 16+) - any article not in that
schedule is still created as a normal ArticlePage, just without a 40th-story
entry.

Usage:
  python manage.py restore_scraped_articles                       # dry run, report only
  python manage.py restore_scraped_articles --commit
"""

import json
import re
import uuid
from datetime import date
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from archives.models import WAHFImage
from content.models import ArticleAuthor, ArticleListPage, ArticlePage, FourtyYearsStory

DEFAULT_JSON_FILE = "wahf_recovered_articles.json"

# Continuation of RESTORE_SCHEDULE in restore_lost_articles.py (which covers
# #1-15). Same externally-assigned weekly posting schedule; short_title is
# the curated title from that same planning spreadsheet, not the article's
# own (sometimes longer) title.
RESTORE_SCHEDULE = {
    "worn-out-engine-now-a-showpiece-wild-rose-airport": (
        date(2026, 4, 22),
        16,
        "Worn Out Engine Now a Showpiece",
    ),
    "marc-mitscher-father-of-naval-airpower": (
        date(2026, 4, 29),
        17,
        "Marc Mitscher, Father of Naval Airpower",
    ),
    "from-hayfield-to-vibrant-airpark-waunakee-airport": (
        date(2026, 5, 6),
        18,
        "From Hayfield to Vibrant Airpark",
    ),
    "guided-by-wasp-wings-caroline-blaze-jensen": (
        date(2026, 5, 13),
        19,
        "Guided by WASP Wings",
    ),
    "how-i-got-to-oshkosh-pete-combs": (
        date(2026, 5, 20),
        20,
        "To Oshkosh in a DC-3",
    ),
    "wisconsins-own-b-25-story": (date(2026, 5, 27), 21, "B-25 at MKE"),
    "air-refueling-the-receivers-view": (date(2026, 6, 3), 22, "Air Refueling"),
    "bringing-history-home-piper-vagabond-sn-1": (
        date(2026, 6, 10),
        23,
        "Vagabond No. 1",
    ),
    "boy-general-from-milwaukee-general-vandenberg": (
        date(2026, 6, 17),
        24,
        "Vandenberg",
    ),
}

# Wagtail appends an 8-char base32-ish suffix like "_3YIWYov" to dedupe
# colliding filenames on upload; also strips a leading hash segment used by
# some rendition filters (e.g. ".2e16d0ba.fill-100x100").
COLLISION_SUFFIX_RE = re.compile(r"_[A-Za-z0-9]{7,8}$")

# Cuts a hedged/inferred attribution down to the plain name, e.g.
# "Gary Dikkers (inferred from photo credits...)" -> "Gary Dikkers". The
# full original text is still shown on stdout so the hedge isn't silently lost.
AUTHOR_HEDGE_RE = re.compile(r"\s*\(.*$")


def normalize(stem: str) -> str:
    return COLLISION_SUFFIX_RE.sub("", stem).lower().replace(" ", "_").replace("-", "_")


def find_image_match(label: str, candidates: dict[str, WAHFImage]):
    key = normalize(label)
    if key in candidates:
        return candidates[key], "exact"
    prefix_matches = {
        image.pk: image
        for k, image in candidates.items()
        if k.startswith(key) or key.startswith(k)
    }
    if len(prefix_matches) == 1:
        return next(iter(prefix_matches.values())), "fuzzy-prefix"
    return None, None


class Command(BaseCommand):
    help = "Recreate ArticlePages from a live-page web scrape JSON (see wahf_recovered_articles.json)"

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

        image_candidates = self.build_image_candidates()

        data = json.loads(path.read_text())
        for article in data["articles"]:
            self.process_article(article, parent_page, image_candidates, commit)

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

    def build_image_candidates(self) -> dict[str, WAHFImage]:
        candidates: dict[str, WAHFImage] = {}
        for image in WAHFImage.objects.all():
            for raw_stem in (
                Path(image.file.name).stem if image.file else None,
                image.title,
            ):
                if raw_stem:
                    candidates.setdefault(normalize(raw_stem), image)
        return candidates

    def process_article(self, article, parent_page, image_candidates, commit):
        slug = article["url"].rstrip("/").rsplit("/", 1)[-1]
        title = article["title"]
        self.stdout.write(f"\n{title!r} ({slug})")

        existing = ArticlePage.objects.filter(slug=slug).first()
        if existing:
            self.stdout.write(f"    -> already exists (id={existing.pk}), skipping")
            return

        schedule_entry = RESTORE_SCHEDULE.get(slug)
        website_publish_date = article_number = story_short_title = None
        if schedule_entry:
            website_publish_date, article_number, story_short_title = schedule_entry
        else:
            self.stdout.write(
                self.style.WARNING(
                    "    ! no RESTORE_SCHEDULE entry - creating as a plain article, no 40th-story number"
                )
            )

        author_name = None
        if article["author"]:
            author_name = AUTHOR_HEDGE_RE.sub("", article["author"]).strip()
            if author_name != article["author"]:
                self.stdout.write(
                    self.style.WARNING(
                        f"    ! hedged author attribution: {article['author']!r}"
                    )
                )

        matched_images = []
        missing_images = []
        for im in article["images"]:
            image, confidence = find_image_match(im["filename_label"], image_candidates)
            if image:
                matched_images.append((image, confidence))
            else:
                missing_images.append(im)

        for image, confidence in matched_images:
            self.stdout.write(f"    - image matched -> {image} ({confidence})")
        for im in missing_images:
            self.stdout.write(
                self.style.WARNING(
                    f"    ! no image match for {im['filename_label']!r} - caption="
                    f"{im['caption']!r} credit={im['credit']!r} (needs manual upload)"
                )
            )

        paragraphs = [p.strip() for p in article["body"].split("\n\n") if p.strip()]
        short_description = paragraphs[0][:300] if paragraphs else ""

        self.stdout.write(
            f"    #{article_number} post={website_publish_date} author={author_name!r} "
            f"date_published={article['date_published']} {len(paragraphs)} paragraph(s), "
            f"{len(matched_images)}/{len(article['images'])} image(s) matched"
        )

        if not commit:
            return

        with transaction.atomic():
            author = None
            if author_name:
                author, _ = ArticleAuthor.objects.get_or_create(name=author_name)

            body = []
            for image, _confidence in matched_images:
                body.append(
                    {"type": "image", "value": image.pk, "id": str(uuid.uuid4())}
                )
            for p in paragraphs:
                body.append(
                    {
                        "type": "paragraph",
                        "value": f"<p>{p}</p>",
                        "id": str(uuid.uuid4()),
                    }
                )

            page = ArticlePage(
                title=title,
                slug=slug,
                subtitle=article["subtitle"] or "",
                author=author,
                date=article["date_published"],
                website_publish_date=website_publish_date or article["date_published"],
                image=matched_images[0][0] if matched_images else None,
                short_description=short_description,
                top_badge="WAHF: 40 YEARS, 40 STORIES" if schedule_entry else "",
                body=body,
                live=False,
            )
            parent_page.add_child(instance=page)
            page.save_revision()

            if schedule_entry:
                FourtyYearsStory.objects.update_or_create(
                    article=page,
                    defaults={
                        "article_number": article_number,
                        "short_title": story_short_title[:250],
                        "image": matched_images[0][0] if matched_images else None,
                    },
                )

        self.stdout.write(
            self.style.SUCCESS(f"    -> created draft ArticlePage id={page.pk}")
        )
