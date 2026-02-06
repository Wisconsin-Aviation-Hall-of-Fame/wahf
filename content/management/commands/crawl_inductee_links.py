import asyncio
from io import BytesIO
from urllib.parse import urlparse

from django.core.files.base import ContentFile
from django.core.management.base import BaseCommand
from django.utils import timezone
from PIL import Image
from playwright.async_api import async_playwright

from content.models import InducteeOutboundLink


def get_domain_from_url(url: str) -> str:
    domain = urlparse(url).netloc
    clean_domain = domain.replace("www.", "")
    return clean_domain


class Command(BaseCommand):
    help = "Scrapes OpenGraph tags or screenshots outbound links"

    def handle(self, *args, **options):
        # Find links missing a title or an image

        links_qs = InducteeOutboundLink.objects.filter(downloaded_datetime__isnull=True)

        if not links_qs.exists():
            self.stdout.write(self.style.SUCCESS("No links to process."))
            return

        for link in links_qs:
            self.stdout.write(f"Processing: {link.url}")
            self.process_link(link)

    def process_link(self, link):
        asyncio.run(self.capture_screenshot_async(link))
        try:
            pass
        except Exception as e:
            self.stderr.write(f"Error: {e}")

    async def capture_screenshot_async(self, link):
        # try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                viewport={"width": 1200, "height": 630},
            )
            page = await context.new_page()

            await page.goto(link.url, wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)

            title = await page.evaluate(
                "() => document.querySelector('meta[property=\"og:title\"]')?.content || document.title"
            )
            desc = await page.evaluate(
                "() => document.querySelector('meta[property=\"og:description\"]')?.content || ''"
            )
            og_img_url = await page.evaluate(
                "() => document.querySelector('meta[property=\"og:image\"]')?.content || ''"
            )

            link.domain = get_domain_from_url(link.url)
            link.title = title[:249]
            link.description = desc
            link.downloaded_datetime = timezone.now()
            await link.asave()

            final_image_bytes = None

            if og_img_url:
                self.stdout.write(f"Found OG Image: {og_img_url}")
                try:
                    # We use the browser to fetch the image to maintain the same session/headers
                    img_response = await page.request.get(og_img_url)
                    if img_response.status == 200:
                        final_image_bytes = await img_response.body()
                except Exception as e:
                    self.stdout.write(
                        f"OG Image download failed, falling back to screenshot: {e}"
                    )

            # Fallback to screenshot if OG download failed or didn't exist
            if not final_image_bytes:
                self.stdout.write("Capturing full page screenshot...")
                final_image_bytes = await page.screenshot(type="jpeg", quality=90)

            img = Image.open(BytesIO(final_image_bytes))
            img.thumbnail((600, 315), Image.Resampling.LANCZOS)
            buffer = BytesIO()
            img.convert("RGB").save(buffer, format="JPEG", quality=85, optimize=True)

            file_name = f"pageimg_{link.id}.jpg"
            link.image.save(file_name, ContentFile(buffer.getvalue()), save=False)
            await link.asave()

            # except Exception as e:
            #
            #    self.stderr.write(f"error: {e}")
            # finally:

            await browser.close()
