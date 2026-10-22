from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('marketplace', '0034_add_delivery_confirmations'),
    ]

    operations = [
        migrations.AddField(
            model_name='wallet',
            name='balance_eur',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=15),
        ),
        migrations.AddField(
            model_name='wallet',
            name='commission_balance_eur',
            field=models.DecimalField(decimal_places=2, default=0, help_text='Comptes Livreur Multi-Devises - EUR', max_digits=15),
        ),
    ]
