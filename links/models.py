from django.db import models


class ShortLink(models.Model):
    name = models.CharField(max_length=255)
    slug = models.SlugField(unique=True, help_text="Used in the short URL: /q/<slug>/")
    destination_url = models.URLField(max_length=2000)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    modified_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def short_url(self):
        return f"https://wahf.org/q/{self.slug}"

    @property
    def pk_url(self):
        return f"https://wahf.org/q/{self.pk}"


class LinkClickLog(models.Model):
    link = models.ForeignKey(ShortLink, on_delete=models.CASCADE, related_name="clicks")
    click_date = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    browser_info = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-click_date"]

    def __str__(self):
        return f"{self.link.name} – {self.click_date:%Y-%m-%d %H:%M}"
