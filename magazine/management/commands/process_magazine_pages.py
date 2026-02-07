import json
import os
import time

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from google import genai
from google.genai import types

from magazine.models import MagazineIssuePage, MagazinePage


def process_data(magazine, data):
    print(magazine)
    for p in data:
        print(
            p["page_number"],
            p.get("page_title"),
            p.get("story_title"),
            p.get("story_author"),
        )
        print("   - ", p.get("story_teaser"))

        MagazinePage.objects.filter(issue=magazine, page=p["page_number"]).update(
            ai_page_title=p["page_title"][:250] if p.get("page_title") else None,
            ai_story_title=p["story_title"][:250] if p.get("story_title") else None,
            ai_story_author=p["story_author"][:250] if p.get("story_author") else None,
            ai_story_summary=p.get("story_teaser"),
            ai_data=p,
        )

    magazine.ai_data = data
    magazine.ai_processed_datetime = timezone.now()
    magazine.save()


class Command(BaseCommand):
    help = "Extracts magazine metadata into strictly structured JSON using Gemini."

    def handle(self, *args, **options):
        client = genai.Client(api_key=settings.GEMINI_API_KEY)

        magazine_qs = (
            MagazineIssuePage.objects.filter(ai_processed_datetime__isnull=True)
            .order_by("-date")
            .all()
        )
        for magazine in magazine_qs:
            pdf_path = f"{settings.MEDIA_ROOT}/{magazine.download_pdf.file}"
            pdf_name = pdf_path.rsplit("/", 1)[1]

            self.stdout.write(self.style.SUCCESS(f"Working on {pdf_name}"))

            try:
                # 1. Upload file using the new File API
                # In the new SDK, this is much more streamlined
                with open(pdf_path, "rb") as f:
                    uploaded_file = client.files.upload(
                        file=f,
                        config={
                            "mime_type": "application/pdf",
                            "display_name": pdf_name,
                        },
                    )

                # 2. Generate content with structured JSON
                # The new SDK handles 'response_mime_type' inside a config object
                response = client.models.generate_content(
                    model="gemini-2.5-flash-lite",
                    contents=[
                        uploaded_file,
                        "Extract page metadata: page_number, page_title, story_title, story_author, story_teaser.",
                    ],
                    config=types.GenerateContentConfig(
                        system_instruction=(
                            "You are a professional metadata librarian. Your task is to extract "
                            "concise page-level summaries for a magazine archive. "
                            "CRITICAL STYLE RULES:\n"
                            "1. NEVER start a story_teaser with 'This article', 'This section', 'This page', or 'This announcement'.\n"
                            "2. JUMP DIRECTLY into the content. Start with an active verb or the subject.\n"
                            "3. Use varied sentence structures to ensure a natural flow.\n"
                            "4. Output strictly valid JSON with this schema: "
                            "[{'page_number': int, 'page_title': str, 'story_title': str, 'story_author': str, 'story_teaser': str}]"
                        ),
                        response_mime_type="application/json",
                    ),
                )

                # 3. Save the result
                output_path = os.path.join(
                    f"{settings.MEDIA_ROOT}/documents-json/",
                    pdf_name.replace(".pdf", ".json"),
                )
                with open(output_path, "w") as f:
                    # The new response object is Pydantic-based
                    f.write(response.text)

                response_json = json.loads(response.text)
                process_data(magazine, response_json)

                self.stdout.write(self.style.SUCCESS(f"Indexed {pdf_name}"))

                time.sleep(4)  # Rate limit safety

            except Exception as e:
                self.stderr.write(f"Error: {e}")
