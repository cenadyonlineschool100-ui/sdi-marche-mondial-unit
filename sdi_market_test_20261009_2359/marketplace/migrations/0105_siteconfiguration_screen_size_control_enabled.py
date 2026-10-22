from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('marketplace', '0104_systemsettings_mobile_footer_support_enabled'),
    ]

    operations = [
        migrations.AddField(
            model_name='siteconfiguration',
            name='screen_size_control_enabled',
            field=models.BooleanField(
                default=False,
                verbose_name='Taille écran + / - activée',
            ),
        ),
    ]
