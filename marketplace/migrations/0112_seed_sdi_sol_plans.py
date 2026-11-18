from django.db import migrations


DEFAULT_PLANS = (
    ('SDI Sol Microtech - 15 jours', 15),
    ('SDI Sol Microtech - 30 jours', 30),
    ('SDI Sol Microtech - 60 jours', 60),
    ('SDI Sol Microtech - 90 jours', 90),
)


def create_default_plans(apps, schema_editor):
    SDISolPlan = apps.get_model('marketplace', 'SDISolPlan')
    for name, duration_days in DEFAULT_PLANS:
        SDISolPlan.objects.get_or_create(
            name=name,
            defaults={
                'duration_days': duration_days,
                'is_active': False,
            },
        )


class Migration(migrations.Migration):
    dependencies = [
        ('marketplace', '0111_sdisolplan_sdisolmember_plan_amount_htg_and_more'),
    ]

    operations = [
        migrations.RunPython(create_default_plans, migrations.RunPython.noop),
    ]
