# Generated migration to initialize Tikane savings plans

from django.db import migrations
from decimal import Decimal


def create_initial_plans(apps, schema_editor):
    """Create initial Tikane savings plans"""
    TiKanePlan = apps.get_model('marketplace', 'TiKanePlan')
    
    plans_data = [
        {
            'name': 'Plan 30 Jours',
            'duration_days': 30,
            'commission_fixed': Decimal('0.00'),
            'commission_variable': Decimal('1.00'),
            'bonus_rate': Decimal('2.50'),
            'description': 'Plan d\'épargne court terme de 30 jours avec bonus de rendement de 2.5%',
            'active': True,
        },
        {
            'name': 'Plan 3 Mois',
            'duration_days': 90,
            'commission_fixed': Decimal('0.00'),
            'commission_variable': Decimal('1.00'),
            'bonus_rate': Decimal('5.00'),
            'description': 'Plan d\'épargne de 3 mois avec bonus de rendement de 5%',
            'active': True,
        },
        {
            'name': 'Plan 6 Mois',
            'duration_days': 180,
            'commission_fixed': Decimal('0.00'),
            'commission_variable': Decimal('1.00'),
            'bonus_rate': Decimal('8.00'),
            'description': 'Plan d\'épargne de 6 mois avec bonus de rendement de 8%',
            'active': True,
        },
        {
            'name': 'Plan 1 An',
            'duration_days': 365,
            'commission_fixed': Decimal('0.00'),
            'commission_variable': Decimal('1.00'),
            'bonus_rate': Decimal('12.00'),
            'description': 'Plan d\'épargne d\'1 an avec bonus de rendement de 12%',
            'active': True,
        },
        {
            'name': 'Plan 2 Ans',
            'duration_days': 730,
            'commission_fixed': Decimal('0.00'),
            'commission_variable': Decimal('1.00'),
            'bonus_rate': Decimal('18.00'),
            'description': 'Plan d\'épargne de 2 ans avec bonus de rendement maximum de 18%',
            'active': True,
        },
    ]
    
    for plan_data in plans_data:
        TiKanePlan.objects.get_or_create(
            name=plan_data['name'],
            defaults=plan_data
        )


def delete_initial_plans(apps, schema_editor):
    """Delete initial plans on reverse migration"""
    TiKanePlan = apps.get_model('marketplace', 'TiKanePlan')
    plan_names = [
        'Plan 30 Jours',
        'Plan 3 Mois',
        'Plan 6 Mois',
        'Plan 1 An',
        'Plan 2 Ans',
    ]
    TiKanePlan.objects.filter(name__in=plan_names).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('marketplace', '0078_tikaneplan_tikaneaccessrequest_tikaneaccount'),
    ]

    operations = [
        migrations.RunPython(create_initial_plans, delete_initial_plans),
    ]
