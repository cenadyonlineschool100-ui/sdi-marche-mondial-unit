import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('marketplace', '0115_systemsettings_desktop_display_mode_enabled_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='PayPalPayment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('paypal_order_id', models.CharField(blank=True, max_length=64, null=True, unique=True)),
                ('capture_id', models.CharField(blank=True, max_length=64, null=True, unique=True)),
                ('request_id', models.UUIDField(default=uuid.uuid4, editable=False, unique=True)),
                ('amount', models.DecimalField(decimal_places=2, max_digits=15)),
                ('currency', models.CharField(default='USD', max_length=3)),
                ('status', models.CharField(choices=[('created', 'Créé'), ('completed', 'Confirmé'), ('failed', 'Échoué')], default='created', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('captured_at', models.DateTimeField(blank=True, null=True)),
                ('order', models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name='paypal_payment', to='marketplace.order')),
                ('transaction', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='paypal_payment', to='marketplace.transaction')),
            ],
        ),
        migrations.CreateModel(
            name='PayPalWebhookEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_id', models.CharField(max_length=128, unique=True)),
                ('event_type', models.CharField(max_length=100)),
                ('processed_at', models.DateTimeField(blank=True, null=True)),
                ('received_at', models.DateTimeField(auto_now_add=True)),
            ],
        ),
    ]
