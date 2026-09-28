import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("content", "0048_alter_articlepage_body_alter_freeformpage_body"),
    ]

    operations = [
        migrations.AlterField(
            model_name="fourtyyearsstory",
            name="article",
            field=models.OneToOneField(
                blank=True,
                help_text="Link to an article OR an inductee page (not both).",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="fourty_article",
                to="content.articlepage",
            ),
        ),
        migrations.AddField(
            model_name="fourtyyearsstory",
            name="inductee_page",
            field=models.OneToOneField(
                blank=True,
                help_text="Link to an inductee page OR an article (not both).",
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="fourty_story",
                to="content.inducteedetailpage",
            ),
        ),
    ]
