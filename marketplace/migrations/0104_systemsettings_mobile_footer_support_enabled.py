from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('marketplace', '0103_siteconfiguration_is_active_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='systemsettings',
            name='mobile_footer_support_enabled',
            field=models.BooleanField(
                default=True,
                verbose_name='⭐ FC - Afficher le footer mobile/tablette et la carte Support SDI'
            ),
        ),
    ]
