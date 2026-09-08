from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('marketplace', '0096_sitebanner_event_types')]

    operations = [
        migrations.AddField(
            model_name='sitebanner',
            name='access_mode',
            field=models.CharField(choices=[('free', 'Gratuit pour tous'), ('selected', 'Accès individuel'), ('paid', 'Payant via MicroCash')], default='free', max_length=20),
        ),
        migrations.AddField(
            model_name='sitebanner',
            name='access_price',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=15),
        ),
        migrations.CreateModel(
            name='SiteBannerAccess',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('banner', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='access_grants', to='marketplace.sitebanner')),
                ('granted_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='granted_site_banner_access', to='marketplace.user')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='site_banner_access_grants', to='marketplace.user')),
            ],
            options={'constraints': [models.UniqueConstraint(fields=('banner', 'user'), name='unique_site_banner_access')]},
        ),
        migrations.CreateModel(
            name='SiteBannerPayment',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('amount', models.DecimalField(decimal_places=2, max_digits=15)),
                ('status', models.CharField(choices=[('pending', 'En attente'), ('confirmed', 'Confirmé'), ('failed', 'Échoué')], default='pending', max_length=20)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('confirmed_at', models.DateTimeField(blank=True, null=True)),
                ('banner', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='payments', to='marketplace.sitebanner')),
                ('transaction', models.OneToOneField(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='site_banner_payment', to='marketplace.transaction')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='site_banner_payments', to='marketplace.user')),
            ],
            options={'constraints': [models.UniqueConstraint(fields=('banner', 'user'), name='unique_site_banner_payment')]},
        ),
        migrations.AlterField(
            model_name='sitebannerevent',
            name='event_type',
            field=models.CharField(max_length=30, choices=[
                ('impression', 'Impression'), ('click', 'Clic'), ('created', 'Création'), ('updated', 'Modification'), ('activated', 'Activation'), ('deactivated', 'Désactivation'), ('deleted', 'Suppression'), ('image_added', 'Ajout image'), ('image_replaced', 'Remplacement image'), ('image_deleted', 'Suppression image'), ('cropped', 'Recadrage'), ('scope_changed', 'Changement portée'), ('permission_granted', 'Attribution permission'), ('permission_revoked', 'Révocation permission'), ('access_mode_changed', 'Mode accès modifié'), ('access_granted', 'Accès accordé'), ('access_revoked', 'Accès révoqué'), ('payment_required', 'Paiement requis'), ('payment_confirmed', 'Paiement confirmé'), ('payment_failed', 'Paiement échoué'),
            ]),
        ),
    ]
