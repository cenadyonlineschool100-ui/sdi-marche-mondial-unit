from datetime import timedelta
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.urls import reverse
from .models import SavingsPlan, UserSavings
from django.utils import timezone
from django.conf import settings


def list_plans(request):
    plans = SavingsPlan.objects.filter(is_active=True).order_by('duration_days')
    active_savings = None
    if request.user.is_authenticated:
        active_savings = UserSavings.objects.filter(user=request.user, is_active=True).first()
    return render(request, 'marketplace/tikane_plans.html', {
        'plans': plans,
        'active_savings': active_savings,
    })


@login_required
def choose_plan(request, plan_id):
    plan = get_object_or_404(SavingsPlan, pk=plan_id, is_active=True)
    # check if user already has an active savings
    existing = UserSavings.objects.filter(user=request.user, is_active=True)
    if existing.exists():
        # only admin can remove
        return render(request, 'marketplace/plan_already_selected.html', {'existing': existing.first()})

    # For simplicity, assume amount equals min_amount if not provided
    amount = plan.min_amount
    sub = UserSavings.objects.create(
        user=request.user,
        plan=plan,
        amount=amount,
        start_date=timezone.now(),
        end_date=timezone.now() + timedelta(days=plan.duration_days),
        admin_locked=True,
    )
    return redirect(reverse('savings:list_plans'))


def is_principal_admin(user):
    return user.is_superuser or getattr(user, 'has_perm', lambda perm: False)('marketplace.principal_admin_power')


@user_passes_test(is_principal_admin)
def admin_remove_subscription(request, subscription_id):
    sub = get_object_or_404(UserSavings, pk=subscription_id)
    sub.is_active = False
    sub.admin_locked = False
    sub.save()
    return redirect('/admin/')
