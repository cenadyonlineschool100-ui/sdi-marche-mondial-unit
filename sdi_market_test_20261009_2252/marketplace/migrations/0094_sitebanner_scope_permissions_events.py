from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('marketplace', '0093_sitebanner_carousel')]

    operations = [
        migrations.AddField(
            model_name='sitebanner', name='scope',
            field=models.CharField(choices=[('all', 'Toutes les boutiques'), ('selected', 'Boutiques sélectionnées')], default='all', max_length=20),
        ),
        migrations.AddField(
            model_name='sitebanner', name='shops',
            field=models.ManyToManyField(blank=True, related_name='site_banners', to='marketplace.shop'),
        ),
        migrations.CreateModel(
            name='SiteBannerPermission',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('can_manage', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('banner', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='permissions', to='marketplace.sitebanner')),
                ('granted_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='granted_site_banner_permissions', to='marketplace.user')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='site_banner_permissions', to='marketplace.user')),
            ],
            options={'constraints': [models.UniqueConstraint(fields=('banner', 'user'), name='unique_site_banner_permission')]},
        ),
        migrations.CreateModel(
            name='SiteBannerEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('event_type', models.CharField(choices=[('impression', 'Impression'), ('click', 'Clic'), ('created', 'Création'), ('updated', 'Modification'), ('activated', 'Activation'), ('deactivated', 'Désactivation'), ('deleted', 'Suppression'), ('image_replaced', 'Remplacement image'), ('permission_changed', 'Changement permission')], max_length=30)),
                ('session_key', models.CharField(blank=True, default='', max_length=40)),
                ('details', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('banner', models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, related_name='events', to='marketplace.sitebanner')),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='marketplace.user')),
            ],
        ),
    ]
