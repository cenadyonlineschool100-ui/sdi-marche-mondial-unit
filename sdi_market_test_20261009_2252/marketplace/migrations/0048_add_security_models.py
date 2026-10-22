# Generated manually for missing security models

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('marketplace', '0047_securityincident_systemsettings_emergency_lockdown_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='SecurityEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_type', models.CharField(choices=[('login_success', 'Connexion réussie'), ('login_failed', 'Connexion échouée'), ('admin_access', 'Accès page admin'), ('api_error', 'Erreur API'), ('http_4xx', 'Erreur 4xx (client)'), ('http_5xx', 'Erreur 5xx (serveur)'), ('suspicious_access', 'Accès suspect'), ('brute_force', 'Brute force détecté'), ('malicious_payload', 'Payload malveillant'), ('other', 'Autre')], default='other', max_length=50)),
                ('source_ip', models.CharField(blank=True, max_length=50, null=True)),
                ('path', models.CharField(blank=True, max_length=255)),
                ('method', models.CharField(blank=True, max_length=10)),
                ('status_code', models.IntegerField(blank=True, null=True)),
                ('response_time_ms', models.IntegerField(blank=True, null=True)),
                ('user_agent', models.CharField(blank=True, max_length=500)),
                ('description', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='security_events', to='marketplace.user')),
            ],
            options={
                'verbose_name': 'Événement de sécurité',
                'verbose_name_plural': 'Événements de sécurité',
                'ordering': ['-created_at'],
                'indexes': [
                    models.Index(fields=['created_at'], name='marketplace_se_created_at_idx'),
                    models.Index(fields=['source_ip', 'created_at'], name='marketplace_se_source_ip_created_at_idx'),
                    models.Index(fields=['event_type', 'created_at'], name='marketplace_se_event_type_created_at_idx'),
                ],
            },
        ),
        migrations.CreateModel(
            name='IPBlocklist',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('ip_address', models.CharField(max_length=50, unique=True)),
                ('reason', models.CharField(blank=True, max_length=255)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('blocked_until', models.DateTimeField(blank=True, null=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='created_ip_blocks', to='marketplace.user')),
            ],
            options={
                'verbose_name': 'IP bloquée',
                'verbose_name_plural': 'IPs bloquées',
                'ordering': ['-created_at'],
            },
        ),
    ]