from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('marketplace', '0098_product_banner_block_reason_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='sitebanner',
            name='autoplay_enabled',
            field=models.BooleanField(default=True, verbose_name='Défilement automatique actif'),
        ),
    ]
