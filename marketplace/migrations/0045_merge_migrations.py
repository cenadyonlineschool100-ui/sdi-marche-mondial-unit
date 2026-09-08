from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('marketplace', '0011_productimage'),
        ('marketplace', '0044_profile_withdrawal_codes'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='price_input_currency',
            field=models.CharField(
                choices=[
                    ('USD', 'USD ($)'),
                    ('HTG', 'Gourdes (HTG)'),
                    ('DOP', 'Peso Dominicain (DOP)'),
                    ('EUR', 'Euro (€)')
                ],
                default='USD',
                help_text='Devise saisie par le vendeur',
                max_length=3
            ),
        ),
    ]