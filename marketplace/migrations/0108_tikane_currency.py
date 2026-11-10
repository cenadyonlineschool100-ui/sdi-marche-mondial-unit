from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('marketplace', '0107_pushsubscription'),
    ]

    operations = [
        migrations.AddField(
            model_name='tikaneaccessrequest',
            name='currency',
            field=models.CharField(
                choices=[('USD', 'USD'), ('HTG', 'HTG'), ('DOP', 'DOP'), ('EUR', 'EUR')],
                max_length=3,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name='tikaneaccount',
            name='currency',
            field=models.CharField(
                choices=[('USD', 'USD'), ('HTG', 'HTG'), ('DOP', 'DOP'), ('EUR', 'EUR')],
                max_length=3,
                null=True,
            ),
        ),
    ]