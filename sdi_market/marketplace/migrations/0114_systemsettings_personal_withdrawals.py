from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('marketplace', '0113_sdisol_groups_and_multiple_memberships'),
    ]

    operations = [
        migrations.AddField(
            model_name='systemsettings',
            name='personal_withdrawals_enabled',
            field=models.BooleanField(
                default=True,
                verbose_name='Autoriser les nouveaux retraits personnels',
            ),
        ),
    ]
