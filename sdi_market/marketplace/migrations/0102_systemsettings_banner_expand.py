from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ('marketplace', '0101_prioritygroup_product_banner_priority_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='systemsettings',
            name='banner_expand_enabled',
            field=models.BooleanField(default=False, verbose_name='Autoriser l’agrandissement du Banner'),
        ),
        migrations.AddField(
            model_name='systemsettings',
            name='banner_normal_height',
            field=models.PositiveIntegerField(default=150, verbose_name='Hauteur normale du Banner'),
        ),
        migrations.AddField(
            model_name='systemsettings',
            name='banner_expanded_height',
            field=models.PositiveIntegerField(default=220, verbose_name='Hauteur agrandie du Banner'),
        ),
    ]