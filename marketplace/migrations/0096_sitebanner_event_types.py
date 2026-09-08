from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [('marketplace', '0095_sitebanner_event_retention')]

    operations = [
        migrations.AlterField(
            model_name='sitebannerevent', name='event_type',
            field=models.CharField(max_length=30, choices=[
                ('impression', 'Impression'), ('click', 'Clic'), ('created', 'Création'), ('updated', 'Modification'),
                ('activated', 'Activation'), ('deactivated', 'Désactivation'), ('deleted', 'Suppression'),
                ('image_added', 'Ajout image'), ('image_replaced', 'Remplacement image'), ('image_deleted', 'Suppression image'),
                ('cropped', 'Recadrage'), ('scope_changed', 'Changement portée'),
                ('permission_granted', 'Attribution permission'), ('permission_revoked', 'Révocation permission'),
            ]),
        ),
    ]