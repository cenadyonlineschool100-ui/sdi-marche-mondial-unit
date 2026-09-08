from django.db import migrations, models
import django.db.models.deletion
from django.conf import settings

class Migration(migrations.Migration):

    dependencies = [
        ('marketplace', '0018_product_custom_image_alter_product_image'),
    ]

    operations = [
        migrations.CreateModel(
            name='ChatGroup',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200)),
                ('slug', models.SlugField(max_length=200, unique=True)),
                ('description', models.TextField(blank=True, default='')),
                ('is_global', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('participants', models.ManyToManyField(blank=True, related_name='chat_groups', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Groupe de chat',
                'verbose_name_plural': 'Groupes de chat',
            },
        ),
        migrations.CreateModel(
            name='ChatMessage',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('content', models.TextField(blank=True)),
                ('image', models.ImageField(blank=True, null=True, upload_to='chat/messages/%Y/%m/')),
                ('is_system', models.BooleanField(default=False)),
                ('is_advertisement', models.BooleanField(default=False)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('group', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='messages', to='marketplace.chatgroup')),
                ('product', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='shared_in_messages', to='marketplace.product')),
                ('sender', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='chat_messages', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Message de chat',
                'verbose_name_plural': 'Messages de chat',
                'ordering': ['created_at'],
            },
        ),
    ]
