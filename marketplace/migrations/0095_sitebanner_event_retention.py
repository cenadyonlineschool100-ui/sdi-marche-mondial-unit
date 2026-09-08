from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('marketplace', '0094_sitebanner_scope_permissions_events')]

    operations = [
        migrations.AlterField(
            model_name='sitebannerevent', name='banner',
            field=models.ForeignKey(null=True, on_delete=models.SET_NULL, related_name='events', to='marketplace.sitebanner'),
        ),
        migrations.AlterField(
            model_name='sitebannerevent', name='event_type',
            field=models.CharField(max_length=30, choices=[
                ('impression', 'Impression'), ('click', 'Clic'), ('created', 'Création'), ('updated', 'Modification'),
                ('activated', 'Activation'), ('deactivated', 'Désactivation'), ('deleted', 'Suppression'),
                ('image_added', 'Ajout image'), ('image_replaced', 'Remplacement image'), ('image_deleted', 'Suppression image'), ('cropped', 'Recadrage'),
                ('scope_changed', 'Changement portée'), ('permission_granted', 'Attribution permission'), ('permission_revoked', 'Révocation permission'),
            ]),
        ),
    ]