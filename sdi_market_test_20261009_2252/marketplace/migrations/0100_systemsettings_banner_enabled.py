from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('marketplace', '0099_sitebanner_autoplay_enabled'),
    ]

    operations = [
        migrations.AddField(
            model_name='systemsettings',
            name='banner_enabled',
            field=models.BooleanField(default=True, verbose_name='Activer le système de bannière'),
        ),
    ]