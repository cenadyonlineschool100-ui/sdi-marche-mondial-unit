# Generated manually for delivery confirmation fields

from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('marketplace', '0033_persistentnotification'),
    ]

    operations = [
        migrations.AddField(
            model_name='deliveryassignment',
            name='driver_confirmed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='deliveryassignment',
            name='driver_confirmed_delivery',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='order',
            name='buyer_confirmed_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='order',
            name='buyer_confirmed_delivery',
            field=models.BooleanField(default=False),
        ),
    ]