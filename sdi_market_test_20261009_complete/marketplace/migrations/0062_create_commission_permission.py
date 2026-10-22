# Créer la permission personnalisée pour la gestion des commissions
from django.db import migrations


def create_permission(apps, schema_editor):
    """Créer la permission personnalisée"""
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')
    User = apps.get_model('marketplace', 'User')
    content_type = ContentType.objects.get_for_model(User)
    
    permission, created = Permission.objects.get_or_create(
        codename='manage_agent_commissions',
        defaults={
            'name': 'Can manage agent commissions',
            'content_type': content_type,
        }
    )
    
    if created:
        print("Permission 'manage_agent_commissions' créée avec succès.")
    else:
        print("La permission 'manage_agent_commissions' existe déjà.")


def delete_permission(apps, schema_editor):
    """Supprimer la permission personnalisée"""
    Permission = apps.get_model('auth', 'Permission')
    Permission.objects.filter(codename='manage_agent_commissions').delete()


class Migration(migrations.Migration):
    dependencies = [
        ('marketplace', '0061_adminsetting_depositlimit_agentcommission_and_more'),
    ]

    operations = [
        migrations.RunPython(create_permission, delete_permission),
    ]
