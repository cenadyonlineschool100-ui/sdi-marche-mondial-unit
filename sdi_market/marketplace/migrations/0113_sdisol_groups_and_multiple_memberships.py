import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


def create_groups_and_backfill_members(apps, schema_editor):
    database = schema_editor.connection.alias
    SDISolGroup = apps.get_model('marketplace', 'SDISolGroup')
    SDISolPlan = apps.get_model('marketplace', 'SDISolPlan')
    SDISolMember = apps.get_model('marketplace', 'SDISolMember')

    for plan in SDISolPlan.objects.using(database).all().iterator():
        group, _ = SDISolGroup.objects.using(database).get_or_create(plan_id=plan.pk)
        members = SDISolMember.objects.using(database).filter(
            plan_id=plan.pk,
            active=True,
            admin_approved=True,
        ).order_by('position', 'joined_at', 'pk')
        for group_position, member in enumerate(members.iterator(), start=1):
            SDISolMember.objects.using(database).filter(pk=member.pk).update(
                group_id=group.pk,
                group_position=group_position,
            )
        SDISolMember.objects.using(database).filter(
            plan_id=plan.pk,
            active=False,
            admin_approved=True,
        ).update(
            group_id=group.pk,
            group_position=models.F('position'),
        )

    SDISolMember.objects.using(database).filter(
        plan_id__isnull=True,
        admin_approved=True,
    ).update(group_position=models.F('position'))


class Migration(migrations.Migration):
    dependencies = [
        ('marketplace', '0112_seed_sdi_sol_plans'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='SDISolGroup',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('plan', models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name='sdi_group',
                    to='marketplace.sdisolplan',
                )),
            ],
            options={
                'verbose_name': 'SDI Sol Group',
                'verbose_name_plural': 'SDI Sol Groups',
            },
        ),
        migrations.AlterField(
            model_name='sdisolmember',
            name='user',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='sdi_sol_members',
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.AddField(
            model_name='sdisolmember',
            name='group',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='members',
                to='marketplace.sdisolgroup',
            ),
        ),
        migrations.AddField(
            model_name='sdisolmember',
            name='group_position',
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='sdisolmember',
            name='admin_rejected',
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(create_groups_and_backfill_members, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name='sdisolmember',
            constraint=models.UniqueConstraint(
                condition=models.Q(('active', True)),
                fields=('user', 'plan'),
                name='uniq_active_sdi_sol_user_plan',
            ),
        ),
        migrations.AddConstraint(
            model_name='sdisolmember',
            constraint=models.UniqueConstraint(
                condition=models.Q(('active', True), ('admin_approved', True)),
                fields=('group', 'group_position'),
                name='uniq_active_sdi_sol_group_place',
            ),
        ),
    ]
