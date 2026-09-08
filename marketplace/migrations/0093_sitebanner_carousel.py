from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [('marketplace', '0092_fix_sitebanner_table')]

    operations = [
        migrations.AddField(
            model_name='sitebanner', name='display_mode',
            field=models.CharField(choices=[('static', 'Image statique'), ('carousel', 'Carrousel')], default='static', max_length=20),
        ),
        migrations.AddField(
            model_name='sitebanner', name='autoplay_seconds',
            field=models.PositiveSmallIntegerField(default=0, help_text='0 désactive la lecture automatique'),
        ),
        migrations.CreateModel(
            name='SiteBannerImage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('image', models.ImageField(upload_to='site_banner/%Y/%m/')),
                ('display_order', models.PositiveIntegerField(default=0)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('banner', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='images', to='marketplace.sitebanner')),
            ],
            options={'ordering': ['display_order', 'id']},
        ),
    ]