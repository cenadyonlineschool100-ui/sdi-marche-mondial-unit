from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('marketplace', '0041_systemsettings_microsdicash_account_name_and_more'),
    ]

    def update_microsdicash_instructions(apps, schema_editor):
        SystemSettings = apps.get_model('marketplace', 'SystemSettings')
        try:
            settings = SystemSettings.objects.get(pk=1)
            old_text = 'Rechargez votre compte via l’administration SDI Marché Mondial ou via un agent local.'
            if settings.microsdicash_payment_instructions.strip() == old_text:
                settings.microsdicash_payment_instructions = 'Rechargez votre compte via l’administration SDI Marché Mondial ou via un agent local. Vous pouvez aussi envoyer l’argent sur MonCash et télécharger le reçu ici.'
                settings.save()
        except SystemSettings.DoesNotExist:
            pass

    operations = [
        migrations.AddField(
            model_name='profile',
            name='receipt_proof',
            field=models.ImageField(blank=True, null=True, upload_to='receipt_uploads/', verbose_name='Reçu MonCash'),
        ),
        migrations.RunPython(update_microsdicash_instructions, reverse_code=migrations.RunPython.noop),
    ]
