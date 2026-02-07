import glob
import os

from django.conf import settings
from django.core.management.base import BaseCommand
from PIL import Image


class Command(BaseCommand):
    help = "Generates OG preview images aligned to the top of the canvas."

    def handle(self, *args, **options):
        # Open Graph recommended size
        TARGET_WIDTH = 1300
        TARGET_HEIGHT = 630

        count = 0
        for large_path in glob.glob(f"{settings.MAGAZINE_ROOT}/*/L-*.jpg"):
            directory = os.path.dirname(large_path)
            filename = os.path.basename(large_path)

            og_filename = filename.replace("L-", "OG-", 1)
            og_path = os.path.join(directory, og_filename)

            if os.path.exists(og_path):
                continue

            try:
                with Image.open(large_path) as img:
                    # 1. Calculate height to maintain aspect ratio based on new width
                    w_percent = TARGET_WIDTH / float(img.size[0])
                    h_size = int((float(img.size[1]) * float(w_percent)))

                    # 2. Resize the image to the full target width
                    # This will make the image very tall (since it's a magazine page)
                    img = img.resize((TARGET_WIDTH, h_size), Image.Resampling.LANCZOS)

                    # 3. Define the crop box (left, upper, right, lower)
                    # We keep the top at 0 and chop the bottom at 630px
                    crop_box = (0, 0, TARGET_WIDTH, TARGET_HEIGHT)
                    og_img = img.crop(crop_box)

                    # 4. Save the result
                    og_img.save(og_path, "JPEG", quality=90)

                self.stdout.write(self.style.SUCCESS(f"Generated: {og_path}"))
                count += 1

            except Exception as e:
                self.stderr.write(
                    self.style.ERROR(f"Failed to process {filename}: {e}")
                )

        self.stdout.write(
            self.style.SUCCESS(f"Finished. Total new images generated: {count}")
        )
