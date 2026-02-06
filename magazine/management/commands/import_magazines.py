import glob
import os
import shutil

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db.utils import IntegrityError
from PIL import Image

from magazine.models import MagazineIssuePage, MagazinePage

# requires Poppler to be installed
# apt-get install poppler-utils


class Command(BaseCommand):
    def handle(self, *args, **options):
        for mag in MagazineIssuePage.objects.all():
            if not mag.download_pdf:
                print(f"{mag} has no PDF set")
                continue

            print(mag)

            base_dir = f"{settings.MAGAZINE_ROOT}/{mag.pk}"
            if not os.path.exists(base_dir):
                os.makedirs(base_dir)

            pdf_source_path = str(mag.download_pdf.file.file)
            pdf_dest_path = f"{base_dir}/issue.pdf"

            shutil.copyfile(pdf_source_path, pdf_dest_path)

            # Create images with L prefix
            os.system(f"cd {base_dir}; pdftoppm -jpeg {pdf_dest_path} L")

            # Generate text descriptions of all pages
            os.system(f"cd {base_dir}; pdftotext {pdf_dest_path} issue.txt")

            # Read in text description
            with open(f"{base_dir}/issue.txt", "r") as issue_text_file:
                issue_text_str = issue_text_file.read()
            text_by_page = issue_text_str.split("\f")  # page separator

            # Remove issue
            os.remove(pdf_dest_path)

            # Walk through all pages
            for filename in glob.glob(f"{base_dir}/L-*.jpg"):
                pagenum = int(
                    filename.replace(f"{base_dir}/", "")
                    .replace("L-", "")
                    .replace(".jpg", "")
                )

                try:
                    mp = MagazinePage.objects.create(
                        issue=mag, page=pagenum, text=text_by_page[pagenum - 1]
                    )
                except IntegrityError:
                    print(f"skip page {pagenum} - {filename}")
                    pass
                else:
                    # Resize images, create thumbnails
                    with Image.open(filename) as im:
                        im_thumb = im.copy()
                        im_thumb.thumbnail((125, 125))
                        im_thumb.save(
                            f"{settings.MAGAZINE_ROOT}/{mp.get_thumbnail_filename}"
                        )

                        im_small = im.copy()
                        im_small.thumbnail((200, 200))
                        im_small.save(
                            f"{settings.MAGAZINE_ROOT}/{mp.get_small_filename}"
                        )

                        im_medium = im.copy()
                        im_medium.thumbnail((600, 600))
                        im_medium.save(
                            f"{settings.MAGAZINE_ROOT}/{mp.get_medium_filename}"
                        )

                    print(f"{mag} - page {pagenum}")
