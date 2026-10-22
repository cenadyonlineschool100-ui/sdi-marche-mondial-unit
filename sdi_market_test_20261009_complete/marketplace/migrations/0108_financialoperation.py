import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('marketplace', '0107_pushsubscription'),
    ]

    operations = [
        migrations.CreateModel(
            name='FinancialOperation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('operation', models.CharField(max_length=40)),
                ('idempotency_key', models.CharField(max_length=128)),
                ('request_hash', models.CharField(max_length=64)),
                ('result_model', models.CharField(blank=True, max_length=100)),
                ('result_pk', models.CharField(blank=True, max_length=64)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('actor', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='financial_operations', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddConstraint(
            model_name='financialoperation',
            constraint=models.UniqueConstraint(fields=('actor', 'operation', 'idempotency_key'), name='uniq_financial_operation_key'),
        ),
    ]
