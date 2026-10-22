from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('marketplace', '0037_fix_exchange_rate_columns'),
    ]

    operations = [
        migrations.AddField(
            model_name='order',
            name='blocked_amount',
            field=models.DecimalField(default=0, max_digits=15, decimal_places=2),
        ),
        migrations.AddField(
            model_name='order',
            name='payment_method',
            field=models.CharField(choices=[
                ('htg_wallet', 'HTG - Portefeuille / MonCash / NatCash'),
                ('htg_moncash', 'HTG - MonCash'),
                ('htg_natcash', 'HTG - NatCash'),
                ('htg_cod', 'HTG - Cash à la livraison'),
                ('htg_transfer', 'HTG - Virement local HTG'),
                ('dop_tpag', 'DOP - tPago'),
                ('dop_local_transfer', 'DOP - Virement local DOP'),
                ('int_card', 'International - Carte Visa/Mastercard'),
                ('int_paypal', 'International - PayPal'),
            ], default='htg_wallet', max_length=50),
        ),
        migrations.AddField(
            model_name='order',
            name='payment_status',
            field=models.CharField(choices=[
                ('pending', 'En attente'),
                ('approved', 'Confirmé'),
                ('failed', 'Échoué'),
            ], default='pending', max_length=20),
        ),
    ]
