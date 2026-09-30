from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('marketplace', '0105_siteconfiguration_screen_size_control_enabled'),
    ]

    operations = [
        migrations.AddField(
            model_name='persistentnotification',
            name='deduplication_key',
            field=models.CharField(blank=True, max_length=180, null=True, unique=True),
        ),
        migrations.AddField(
            model_name='persistentnotification',
            name='target_url',
            field=models.CharField(blank=True, max_length=500),
        ),
    ]
