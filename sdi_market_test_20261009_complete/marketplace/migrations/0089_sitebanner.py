from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('marketplace', '0088_real_estate_auto_loan'),
    ]

    operations = [
        migrations.CreateModel(
            name='SiteBanner',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', models.CharField(default='Offre du moment', max_length=120, verbose_name='Titre')),
                ('subtitle', models.CharField(blank=True, default='', max_length=220, verbose_name='Sous-titre')),
                ('button_text', models.CharField(default='Voir le produit', max_length=40, verbose_name='Texte du bouton')),
                ('image', models.ImageField(blank=True, null=True, upload_to='site_banner/%Y/%m/', verbose_name='Image de la bannière')),
                ('is_active', models.BooleanField(default=True, verbose_name='Activer la bannière')),
                ('display_order', models.PositiveIntegerField(default=0)),
                ('start_date', models.DateTimeField(blank=True, null=True)),
                ('end_date', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('product', models.ForeignKey(help_text='Produit réel affiché dans la bannière', on_delete=django.db.models.deletion.CASCADE, related_name='site_banners', to='marketplace.product')),
            ],
            options={
                'verbose_name': 'Bannière du site',
                'verbose_name_plural': 'Bannières du site',
                'ordering': ['display_order', '-created_at'],
            },
        ),
    ]
