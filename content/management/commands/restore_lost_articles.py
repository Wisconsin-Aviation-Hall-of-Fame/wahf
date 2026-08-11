"""
Recreates ArticlePages (and their "WAHF: 40 Years, 40 Stories" entries) lost
from production, from full Wayback Machine capture pages saved into a
restore/ directory.

Each source file is named "NN <Title> - Wisconsin Aviation Hall of Fame.html";
NN only controls the order files are processed in. The real
FourtyYearsStory.article_number and website_publish_date for each article
come from RESTORE_SCHEDULE below (an externally-assigned weekly posting
schedule), not from the filename or the article's own byline date. The
images these articles reference already exist in the live WAHFImage table -
this command only recreates the ArticlePage content and backfills any still-
blank WAHFImage.caption/.source fields using text recovered from the article
body (mainly <figcaption> and its embedded "Courtesy of ..."/"Photo by ..."
credit spans).

Restored pages are always created as unpublished drafts (an initial revision
is saved, but never published) so they can be reviewed in the Wagtail admin
before going live. Re-running is safe: an article already restored is
updated in place (to pick up parser fixes or schedule changes) rather than
skipped or duplicated.

The FourtyYearsStory.short_title and .image for each restored article are
taken from the "40 Years, 40 Stories" master list page (the wahf.org/40/
index that links out to all of these articles), not derived from the article
itself - the master list uses shorter, curated titles (e.g. "Archie
Henkelmann" instead of the article's full "The Archie Henkelmann Story") and
a wide banner-crop image distinct from the article's own thumbnail.

Usage:
  python manage.py restore_lost_articles                       # dry run, report only
  python manage.py restore_lost_articles --commit
  python manage.py restore_lost_articles --source-dir restore --parent-slug articles --commit
"""

import html as htmlmod
import re
import uuid
from datetime import date, datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from archives.models import WAHFImage
from content.models import ArticleAuthor, ArticleListPage, ArticlePage, FourtyYearsStory

DEFAULT_SOURCE_DIR = "restore"
DEFAULT_MASTER_LIST_GLOB = "master list*.html"

# The real FourtyYearsStory.article_number (#1 = Carl Guell, ascending in the
# same order as the wahf.org/40/ master list) and the weekly publish-date
# schedule for this restore batch - both assigned externally (a planning
# spreadsheet), not derivable from the Wayback captures themselves.
# website_publish_date drives sort order on the site and must be this
# schedule date, not the article's own historical byline date
# (ArticlePage.date, which stays as originally published).
RESTORE_SCHEDULE = {
    "wahf-founder-carl-guell": (date(2026, 1, 7), 1),
    "the-archie-henkelmann-story": (date(2026, 1, 14), 2),
    "the-shooting-down-of-admiral-yamamoto": (date(2026, 1, 21), 3),
    "bill-lotzer-and-gran-aire": (date(2026, 1, 28), 4),
    "milwaukees-steel-curtain": (date(2026, 2, 4), 5),
    "the-bob-lussow-story": (date(2026, 2, 11), 6),
    "arnold-ebneter-from-golden-age-of-aviation-to-world-record": (
        date(2026, 2, 18),
        7,
    ),
    "tales-of-the-aces": (date(2026, 2, 25), 8),
    "logging-time-with-paul-poberezny": (date(2026, 3, 4), 9),
    "lieutenant-gerald-stull-ditches-in-lake-monona": (date(2026, 3, 11), 10),
    "when-the-rescuers-become-rescued-major-knitter": (date(2026, 3, 18), 11),
    "a-stearman-homecoming": (date(2026, 3, 25), 12),
    "the-us-air-force-academy": (date(2026, 4, 1), 13),
    "gilbert-greens-flying-days": (date(2026, 4, 8), 14),
    "keep-em-flying-bouchards-four-generations-of-flight": (date(2026, 4, 15), 15),
}

# Wagtail appends an 8-char base32-ish suffix like "_3YIWYov" to dedupe
# colliding filenames on upload; also strips a leading hash segment used by
# some rendition filters (e.g. ".2e16d0ba.fill-100x100").
COLLISION_SUFFIX_RE = re.compile(r"_[A-Za-z0-9]{7,8}$")

DATE_FORMATS = ("%b %d, %Y", "%B %d, %Y")

MORE_STORIES_CARD_RE = re.compile(
    r'/articles/([^/\']+)/\'\s*;">.*?<p class="lead">\s*(.*?)\s*<br>',
    re.S,
)


def normalize(stem: str) -> str:
    return COLLISION_SUFFIX_RE.sub("", stem).lower()


def strip_rendition_suffix(stem: str) -> str:
    """Undo Wagtail's rendition-filename mangling, e.g.
    'Carl_Guells_training_squadron_Carl_is_standin.width-1200' ->
    'Carl_Guells_training_squadron_Carl_is_standin' (may still be truncated -
    matched later via prefix-fuzzy matching against real WAHFImage filenames)
    """
    prev = None
    s = stem
    while prev != s:
        prev = s
        s = re.sub(r"\.(?:width|height)-\d+$", "", s)
        s = re.sub(r"\.max-\d+x\d+$", "", s)
        s = re.sub(r"\.fill-\d+x\d+$", "", s)
        s = re.sub(r"\.[0-9a-f]{8}$", "", s)
        s = re.sub(r"\.original$", "", s)
    return s


def find_image_match(stem: str, candidates: dict[str, WAHFImage]):
    """candidates maps normalized-stem -> WAHFImage, built from both .title
    and the .file basename of every WAHFImage, so either can match."""
    normalized_target = normalize(stem)
    if normalized_target in candidates:
        return candidates[normalized_target], "exact"

    prefix_matches = {
        image.pk: image
        for key, image in candidates.items()
        if key.startswith(normalized_target) or normalized_target.startswith(key)
    }
    if len(prefix_matches) == 1:
        return next(iter(prefix_matches.values())), "fuzzy-prefix"

    return None, None


def wayback_url_strip(href: str) -> str:
    m = re.match(r"^/web/\d+(?:im_)?/(https?://.*)$", href)
    if not m:
        return href
    target = m.group(1)
    m2 = re.match(r"^https?://(?:www\.)?wahf\.org(/.*)$", target)
    if m2:
        return m2.group(1)
    return target


def clean_richtext(fragment: str) -> str:
    fragment = re.sub(
        r'href="([^"]+)"', lambda m: f'href="{wayback_url_strip(m.group(1))}"', fragment
    )
    return htmlmod.unescape(fragment).strip()


def strip_tags(fragment: str) -> str:
    return htmlmod.unescape(re.sub(r"<[^>]+>", " ", fragment))


def image_filename_from_src(src: str) -> str | None:
    m = re.search(r"/media/images/([^\"?]+)$", src)
    if not m:
        return None
    fname = m.group(1)
    stem = strip_rendition_suffix(Path(fname).stem)
    return stem + Path(fname).suffix


TOKEN_RE = re.compile(
    r'<p data-block-key="[^"]*">(?P<para>.*?)</p>'
    r'|<div class="article-image-container[^"]*">(?P<img>.*?)</div>'
    r"|<h(?P<hlevel>[234])>(?P<heading>.*?)</h\d>"
    r"|<blockquote>(?P<quote>.*?)</blockquote>"
    r'|<div class="editors-note[^"]*">(?P<note>.*?)</div>',
    re.S,
)


def parse_body_blocks(body_html: str) -> list[dict]:
    blocks = []
    for m in TOKEN_RE.finditer(body_html):
        if m.group("para") is not None:
            text = clean_richtext(m.group("para"))
            if text:
                # RichTextBlock needs an actual block-level wrapper - without it
                # the browser renders consecutive paragraph blocks as one
                # unbroken run of text.
                blocks.append({"kind": "paragraph", "value": f"<p>{text}</p>"})
        elif m.group("img") is not None:
            inner = m.group("img")
            src_m = re.search(r'src="([^"]+)"', inner)
            if not src_m:
                continue
            filename = image_filename_from_src(src_m.group(1))
            fig_m = re.search(r"<figcaption>(.*?)</figcaption>", inner, re.S)
            caption, source = None, None
            if fig_m:
                fig_inner = fig_m.group(1)
                credit_m = re.search(
                    r'<span class="image-credit">(.*?)</span>', fig_inner, re.S
                )
                if credit_m:
                    source = strip_tags(credit_m.group(1)).strip()
                    fig_inner = fig_inner.replace(credit_m.group(0), "")
                caption = strip_tags(fig_inner).strip() or None
            blocks.append(
                {
                    "kind": "image",
                    "filename": filename,
                    "caption": caption,
                    "source": source,
                }
            )
        elif m.group("heading") is not None:
            text = strip_tags(m.group("heading")).strip()
            if text:
                blocks.append({"kind": "heading", "value": text})
        elif m.group("quote") is not None:
            text = strip_tags(m.group("quote")).strip()
            if text:
                blocks.append({"kind": "blockquote", "value": text})
        elif m.group("note") is not None:
            inner = re.sub(
                r'<p class="editors-note-header">.*?</p>',
                "",
                m.group("note"),
                flags=re.S,
            )
            text = strip_tags(inner).strip()
            if text:
                blocks.append({"kind": "editorsnote", "value": text})
    return blocks


def parse_slug(html_text: str) -> str | None:
    m = re.search(r'og:url"\s+content="([^"]+)"', html_text)
    if not m:
        return None
    target = wayback_url_strip(re.sub(r"^https://web\.archive\.org", "", m.group(1)))
    m2 = re.match(r"^/articles/([^/]+)/?$", target)
    return m2.group(1) if m2 else target


def parse_date(date_str: str):
    cleaned = date_str.replace(".", "").strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, fmt).date()
        except ValueError:
            continue
    return None


def parse_article(path: Path) -> dict:
    html_text = path.read_text(encoding="utf-8")

    title_m = re.search(
        r'<div class="page-title-container">.*?<h1>(.*?)</h1>(?:\s*<h2>(.*?)</h2>)?',
        html_text,
        re.S,
    )
    author_m = re.search(r'text-bg-info">\s*By ([^<]+?)\s*</span>', html_text)
    date_m = re.search(r'text-bg-secondary">\s*([^<]+?)\s*</span>', html_text)
    badge_m = re.search(r'text-bg-warning">\s*([^<]+?)\s*</span>', html_text)
    desc_m = re.search(r'<meta name="description" content="([^"]*)"', html_text)

    body_m = re.search(
        r'<div class="article-body">(.*?)<div style="clear:both">', html_text, re.S
    )

    about_img_m = re.search(
        r'<div class="col-md-3">\s*<img[^>]*alt="([^"]*)"[^>]*src="([^"]+)"', html_text
    )
    about_box_m = re.search(
        r'<div class="col p-2">(.*?)</div>\s*</div>\s*</div>\s*</div>', html_text, re.S
    )
    about_box = about_box_m.group(1) if about_box_m else ""
    about_email_m = re.search(r'<i>\s*<a[^>]*mailto:([^"]+)"', about_box)
    about_blurb_m = re.search(
        r'<p>\s*<p data-block-key="[^"]*">(.*?)</p>\s*</p>', about_box, re.S
    )

    return {
        "number": int(path.name.split(" ", 1)[0]),
        "path": path,
        "slug": parse_slug(html_text),
        "title": htmlmod.unescape(title_m.group(1)).strip() if title_m else None,
        "subtitle": (
            htmlmod.unescape(title_m.group(2)).strip()
            if title_m and title_m.group(2)
            else ""
        ),
        "author_name": (
            htmlmod.unescape(author_m.group(1)).strip() if author_m else None
        ),
        "date": parse_date(date_m.group(1)) if date_m else None,
        "top_badge": badge_m.group(1).strip() if badge_m else "",
        "short_description": (
            htmlmod.unescape(desc_m.group(1)).strip() if desc_m else ""
        ),
        "blocks": parse_body_blocks(body_m.group(1)) if body_m else [],
        "about_author_image_filename": (
            image_filename_from_src(about_img_m.group(2)) if about_img_m else None
        ),
        "about_author_email": about_email_m.group(1) if about_email_m else "",
        "about_author_blurb": (
            clean_richtext(about_blurb_m.group(1)) if about_blurb_m else ""
        ),
    }


MASTER_LIST_ITEM_RE = re.compile(
    r'<div class="article-40th-item" onclick="window\.location=\'/articles/(?P<slug>[^/]+)/\'">\s*'
    r'<div class="image-wrapper">\s*<img[^>]*src="(?P<src>[^"]+)"[^>]*>\s*</div>\s*'
    r'<div class="item-text p-3">\s*<h2>\s*#(?P<num>\d+)\s*-\s*(?P<short_title>.*?)\s*</h2>',
    re.S,
)


def parse_master_list(path: Path) -> dict[str, dict]:
    """Parses the wahf.org/40/ "40 Years, 40 Stories" index page into
    slug -> {number, short_title, image_filename}."""
    html_text = path.read_text(encoding="utf-8")
    entries = {}
    for m in MASTER_LIST_ITEM_RE.finditer(html_text):
        entries[m.group("slug")] = {
            "number": int(m.group("num")),
            "short_title": htmlmod.unescape(m.group("short_title")).strip(),
            "image_filename": image_filename_from_src(m.group("src")),
        }
    return entries


def build_more_stories_lookup(paths: list[Path]) -> dict[str, str]:
    """Other restore files' "More Stories" related-article cards echo this
    article's own short_description, for the (common) case where the file's
    own <meta name="description"> is missing."""
    lookup: dict[str, str] = {}
    for path in paths:
        html_text = path.read_text(encoding="utf-8")
        for m in MORE_STORIES_CARD_RE.finditer(html_text):
            slug, lead_raw = m.group(1), m.group(2)
            if slug in lookup:
                continue
            lead_text = re.sub(r"\s+", " ", strip_tags(lead_raw)).strip()
            if lead_text:
                lookup[slug] = lead_text
    return lookup


class Command(BaseCommand):
    help = "Recreate lost ArticlePages (as drafts) from Wayback captures in restore/"

    def add_arguments(self, parser):
        parser.add_argument(
            "--source-dir",
            default=DEFAULT_SOURCE_DIR,
            help=f"Directory of 'NN <Title>....html' Wayback captures (default: {DEFAULT_SOURCE_DIR})",
        )
        parser.add_argument(
            "--master-list",
            default=None,
            help="Path to the saved 'wahf.org/40/' master list capture, used for each "
            "restored article's FourtyYearsStory short_title/image (default: "
            f"auto-detect a single '{DEFAULT_MASTER_LIST_GLOB}' file in the current dir)",
        )
        parser.add_argument(
            "--parent-slug",
            default=None,
            help="Slug of the ArticleListPage to create restored articles under (default: "
            "auto-detect if only one exists)",
        )
        parser.add_argument(
            "--commit",
            action="store_true",
            help="Actually create pages/rows (default is dry-run only)",
        )

    def handle(self, *args, **options):
        commit = options["commit"]
        source_dir = Path(options["source_dir"])
        if not source_dir.is_dir():
            raise CommandError(f"Source dir does not exist: {source_dir}")

        parent_page = self.get_parent_page(options["parent_slug"])
        self.stdout.write(
            f"Parent ArticleListPage: {parent_page.title!r} ({parent_page.url})"
        )

        master_list_entries = self.load_master_list(options["master_list"])

        paths = sorted(source_dir.glob("*.html"))
        if not paths:
            self.stdout.write(
                self.style.WARNING(f"No .html files found in {source_dir}")
            )
            return

        articles = [parse_article(p) for p in paths]
        articles.sort(key=lambda a: a["number"])

        more_stories_lookup = build_more_stories_lookup(paths)

        image_candidates = self.build_image_candidates()

        for article in articles:
            self.process_article(
                article,
                parent_page,
                image_candidates,
                more_stories_lookup,
                master_list_entries,
                commit,
            )

        if not commit:
            self.stdout.write(
                self.style.WARNING("\nDry run - re-run with --commit to create pages.")
            )

    def load_master_list(self, master_list_option) -> dict[str, dict]:
        if master_list_option:
            path = Path(master_list_option)
            if not path.is_file():
                raise CommandError(f"--master-list file not found: {path}")
        else:
            matches = sorted(Path(".").glob(DEFAULT_MASTER_LIST_GLOB))
            if not matches:
                self.stdout.write(
                    self.style.WARNING(
                        f"No '{DEFAULT_MASTER_LIST_GLOB}' file found - FourtyYearsStory rows "
                        "will fall back to the article's own title/first image."
                    )
                )
                return {}
            if len(matches) > 1:
                raise CommandError(
                    f"Multiple '{DEFAULT_MASTER_LIST_GLOB}' files found - pass --master-list"
                )
            path = matches[0]

        entries = parse_master_list(path)
        self.stdout.write(f"Master list: {path} ({len(entries)} entries)")
        return entries

    def get_parent_page(self, parent_slug):
        qs = ArticleListPage.objects.all()
        if parent_slug:
            page = qs.filter(slug=parent_slug).first()
            if not page:
                raise CommandError(f"No ArticleListPage with slug={parent_slug!r}")
            return page

        count = qs.count()
        if count == 0:
            raise CommandError(
                "No ArticleListPage exists - create one first, or pass --parent-slug"
            )
        if count > 1:
            slugs = ", ".join(qs.values_list("slug", flat=True))
            raise CommandError(
                f"Multiple ArticleListPages exist ({slugs}) - pass --parent-slug to pick one"
            )
        return qs.first()

    def build_image_candidates(self) -> dict[str, WAHFImage]:
        candidates: dict[str, WAHFImage] = {}
        for image in WAHFImage.objects.all():
            for raw_stem in (
                Path(image.file.name).stem if image.file else None,
                image.title,
            ):
                if not raw_stem:
                    continue
                key = normalize(raw_stem)
                # Prefer the first (exact-title) match if of two images
                # collide after normalization - ambiguous either way.
                candidates.setdefault(key, image)
        return candidates

    def match_image(self, filename, image_candidates, label):
        if not filename:
            return None, None
        image, confidence = find_image_match(Path(filename).stem, image_candidates)
        if not image:
            self.stdout.write(
                self.style.WARNING(
                    f"    ! no WAHFImage match for {label} ({filename!r})"
                )
            )
        return image, confidence

    def process_article(
        self,
        article,
        parent_page,
        image_candidates,
        more_stories_lookup,
        master_list_entries,
        commit,
    ):
        slug, title = article["slug"], article["title"]
        self.stdout.write(f"\n{title!r} ({slug})")

        if not slug or not title:
            self.stdout.write(
                self.style.ERROR("    ! could not parse slug/title, skipping")
            )
            return

        schedule_entry = RESTORE_SCHEDULE.get(slug)
        if not schedule_entry:
            self.stdout.write(
                self.style.ERROR(
                    "    ! no RESTORE_SCHEDULE entry for this slug - skipping "
                    "(article_number/website_publish_date are required, add it to RESTORE_SCHEDULE)"
                )
            )
            return
        website_publish_date, article_number = schedule_entry

        master_entry = master_list_entries.get(slug)
        if not master_entry:
            self.stdout.write(
                self.style.WARNING(
                    "    ! not found in master list - using article's own title/image"
                )
            )

        existing_page = ArticlePage.objects.filter(slug=slug).first()
        if existing_page:
            self.stdout.write(
                f"    -> already restored (id={existing_page.pk}), updating in place"
            )

        short_description = article["short_description"]
        if not short_description:
            short_description = more_stories_lookup.get(slug, "")
            if short_description:
                self.stdout.write(
                    "    (short_description recovered from another article's 'More Stories' card)"
                )
        if not short_description and article["blocks"]:
            first_para = next(
                (b["value"] for b in article["blocks"] if b["kind"] == "paragraph"), ""
            )
            short_description = strip_tags(first_para)[:300].strip()
            if short_description:
                self.stdout.write(
                    self.style.WARNING(
                        "    ! no short_description found anywhere - auto-derived from first "
                        "paragraph, review/rewrite in admin"
                    )
                )

        body_blocks = []
        first_image = None
        for block in article["blocks"]:
            if block["kind"] == "image":
                image, confidence = self.match_image(
                    block["filename"],
                    image_candidates,
                    f"body image {block['filename']!r}",
                )
                if not image:
                    continue
                self.stdout.write(
                    f"    - image {block['filename']!r} -> {image} ({confidence})"
                )
                first_image = first_image or image
                body_blocks.append(
                    {"type": "image", "value": image.pk, "id": str(uuid.uuid4())}
                )
                if commit:
                    self.update_image_caption_source(
                        image, block["caption"], block["source"]
                    )
            elif block["kind"] == "paragraph":
                body_blocks.append(
                    {
                        "type": "paragraph",
                        "value": block["value"],
                        "id": str(uuid.uuid4()),
                    }
                )
            elif block["kind"] == "heading":
                body_blocks.append(
                    {
                        "type": "heading",
                        "value": block["value"],
                        "id": str(uuid.uuid4()),
                    }
                )
            elif block["kind"] == "blockquote":
                body_blocks.append(
                    {
                        "type": "blockquote",
                        "value": {"quote": block["value"]},
                        "id": str(uuid.uuid4()),
                    }
                )
            elif block["kind"] == "editorsnote":
                body_blocks.append(
                    {
                        "type": "editorsnote",
                        "value": {"note": block["value"]},
                        "id": str(uuid.uuid4()),
                    }
                )

        author_image = None
        if article["about_author_image_filename"]:
            author_image, confidence = self.match_image(
                article["about_author_image_filename"],
                image_candidates,
                f"author photo {article['about_author_image_filename']!r}",
            )
            if author_image:
                self.stdout.write(
                    f"    - author photo -> {author_image} ({confidence})"
                )

        story_short_title = title
        story_image = first_image
        if master_entry:
            story_short_title = master_entry["short_title"] or title
            if master_entry["image_filename"]:
                matched, confidence = self.match_image(
                    master_entry["image_filename"],
                    image_candidates,
                    f"40th list image {master_entry['image_filename']!r}",
                )
                if matched:
                    self.stdout.write(
                        f"    - 40th list image -> {matched} ({confidence})"
                    )
                    story_image = matched

        self.stdout.write(
            f"    #{article_number} post={website_publish_date} {len(body_blocks)} body "
            f"block(s), author={article['author_name']!r}, date={article['date']}, "
            f"badge={article['top_badge']!r}"
        )

        if not commit:
            return

        conflicting_story = (
            FourtyYearsStory.objects.filter(article_number=article_number)
            .exclude(article__slug=slug)
            .first()
        )
        if conflicting_story:
            self.stdout.write(
                self.style.ERROR(
                    f"    ! article_number={article_number} is already used by "
                    f"{conflicting_story.article.slug!r} (FourtyYearsStory pk="
                    f"{conflicting_story.pk}) - skipping, fix RESTORE_SCHEDULE and re-run"
                )
            )
            return

        with transaction.atomic():
            author = self.get_or_update_author(
                article["author_name"],
                author_image,
                article["about_author_email"],
                article["about_author_blurb"],
            )

            field_values = dict(
                title=title,
                subtitle=article["subtitle"],
                author=author,
                date=article["date"],
                website_publish_date=website_publish_date,
                image=first_image,
                short_description=short_description,
                top_badge=article["top_badge"],
                body=body_blocks,
            )

            if existing_page:
                for field, value in field_values.items():
                    setattr(existing_page, field, value)
                existing_page.save()
                existing_page.save_revision()
                page = existing_page
                action = "updated"
            else:
                page = ArticlePage(slug=slug, live=False, **field_values)
                parent_page.add_child(instance=page)
                page.save_revision()
                action = "created"

            FourtyYearsStory.objects.update_or_create(
                article=page,
                defaults={
                    "article_number": article_number,
                    "short_title": story_short_title[:250],
                    "image": story_image,
                },
            )

        self.stdout.write(
            self.style.SUCCESS(f"    -> {action} draft ArticlePage id={page.pk}")
        )

    def get_or_update_author(self, name, image, email, blurb):
        if not name:
            return None
        author, created = ArticleAuthor.objects.get_or_create(name=name)
        changed = False
        if image and not author.image_id:
            author.image = image
            changed = True
        if email and not author.contact_email:
            author.contact_email = email
            changed = True
        if blurb and not author.about_blurb:
            author.about_blurb = blurb
            changed = True
        if changed:
            author.save()
        return author

    def update_image_caption_source(self, image, caption, source):
        changed = False
        if caption and not image.caption:
            image.caption = caption[:255]
            changed = True
        if source and not image.source:
            image.source = source[:255]
            changed = True
        if changed:
            image.save(update_fields=["caption", "source"])
