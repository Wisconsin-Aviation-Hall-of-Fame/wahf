import asyncio
from io import BytesIO
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
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
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

        try:
            # 1. Scrape HTML for metadata
            response = requests.get(
                link.url, headers=headers, timeout=15, allow_redirects=True
            )
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            # Extract Title & Description
            og_title = soup.find("meta", property="og:title")
            og_desc = soup.find("meta", property="og:description")

            link.domain = get_domain_from_url(link.url)
            link.title = (
                og_title.get("content")
                if og_title
                else (soup.title.string if soup.title else "")
            )[:249]
            link.description = og_desc.get("content") if og_desc else ""
            link.save()

            # 2. Check for OG Image
            og_img = soup.find("meta", property="og:image")

            if og_img and og_img.get("content"):
                img_url = urljoin(link.url, og_img.get("content"))
                self.stdout.write(f"Downloading OG image: {img_url}")

                img_res = requests.get(img_url, headers=headers, timeout=10)
                if img_res.status_code == 200:
                    file_name = f"preview_{link.id}.jpg"

                    img = Image.open(BytesIO(img_res.content))
                    # You might want to use .thumbnail() here to maintain aspect ratio
                    # if the site's OG image isn't exactly 1200x630
                    img.thumbnail((600, 315), Image.Resampling.LANCZOS)

                    buffer = BytesIO()
                    img.convert("RGB").save(
                        buffer, format="JPEG", quality=85, optimize=True
                    )

                    link.image.save(
                        file_name, ContentFile(buffer.getvalue()), save=False
                    )
                    link.downloaded_datetime = timezone.now()
                    link.save()
                    return  # Exit successfully

            # 3. Fallback: Playwright Screenshot
            self.stdout.write("OG image missing or failed. Using Playwright...")
            asyncio.run(self.capture_screenshot_async(link))

        except Exception as e:
            self.stderr.write(
                self.style.ERROR(f"Failed to process {link.url}: {str(e)}")
            )

    async def capture_screenshot_async(self, link):
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(viewport={"width": 1200, "height": 630})
            page = await context.new_page()

            try:
                await page.goto(link.url, wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(2000)

                # 1. Capture original full-res bytes
                screenshot_bytes = await page.screenshot(type="jpeg", quality=90)

                # 2. Open with Pillow and resize
                img = Image.open(BytesIO(screenshot_bytes))

                # We use LANCZOS for high-quality downsampling
                resized_img = img.resize((600, 315), Image.Resampling.LANCZOS)

                # 3. Save resized image back to a Buffer
                buffer = BytesIO()
                resized_img.save(buffer, format="JPEG", quality=85, optimize=True)

                # 4. Save to Django ImageField
                file_name = f"pageimg_{link.id}.jpg"
                link.image.save(file_name, ContentFile(buffer.getvalue()), save=False)
                link.downloaded_datetime = timezone.now()
                await link.asave()

            except Exception as e:
                self.stderr.write(f"Playwright error: {e}")
            finally:
                await browser.close()
