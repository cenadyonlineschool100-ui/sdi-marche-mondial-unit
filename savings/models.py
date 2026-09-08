from datetime import timedelta
from django.db import models
from django.conf import settings
from django.utils import timezone


class SavingsPlan(models.Model):
    CURRENCY_CHOICES = [
        ('HTG', 'HTG'),
        ('USD', 'USD'),
        ('EUR', 'EUR'),
        ('DOP', 'DOP'),
    ]

    name = models.CharField(max_length=120)
    duration_days = models.PositiveIntegerField(help_text='Durée du plan en jours')
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)
    min_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    max_amount = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    commission_percent = models.DecimalField(max_digits=5, decimal_places=2, default=0, help_text='Pourcentage de commission')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.duration_days}j - {self.currency})"


class UserSavings(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='savings')
    plan = models.ForeignKey(SavingsPlan, on_delete=models.PROTECT, related_name='subscriptions')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    start_date = models.DateTimeField(default=timezone.now)
    end_date = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    admin_locked = models.BooleanField(default=False, help_text='Si vrai, seul l\'admin peut supprimer ce plan')
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.end_date:
            self.end_date = self.start_date + timedelta(days=self.plan.duration_days)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user} - {self.plan.name} ({self.amount} {self.plan.currency})"
