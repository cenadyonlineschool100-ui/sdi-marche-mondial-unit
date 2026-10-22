from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('marketplace', '0109_tikane_currency'),
    ]

    operations = [
        migrations.AddField(
            model_name='systemsettings',
            name='tikane_withdrawals_enabled',
            field=models.BooleanField(
                default=True,
                verbose_name='Autoriser les nouveaux retraits Ti Kanè',
            ),
        ),
        migrations.AddField(
            model_name='systemsettings',
            name='agent_wallet_withdrawals_enabled',
            field=models.BooleanField(
                default=True,
                verbose_name='Autoriser les nouveaux retraits des commissions agent',
            ),
        ),
    ]
