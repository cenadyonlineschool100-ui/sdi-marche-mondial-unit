from django.contrib import admin
from .models import SavingsPlan, UserSavings


@admin.register(SavingsPlan)
class SavingsPlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'duration_days', 'currency', 'min_amount', 'max_amount', 'commission_percent', 'is_active')
    list_filter = ('currency', 'is_active')
    search_fields = ('name',)


@admin.register(UserSavings)
class UserSavingsAdmin(admin.ModelAdmin):
    list_display = ('user', 'plan', 'amount', 'start_date', 'end_date', 'is_active', 'admin_locked')
    list_filter = ('is_active', 'admin_locked', 'plan')
    search_fields = ('user__username', 'plan__name')
