from django.core.management.base import BaseCommand
from django.utils import timezone

from marketplace.models import PayPalStockReservation
from marketplace.paypal_stock import release_paypal_stock


class Command(BaseCommand):
    help = 'Release expired stock reservations for unpaid PayPal orders.'

    def handle(self, *args, **options):
        expired_order_ids = list(
            PayPalStockReservation.objects.filter(
                status='reserved',
                expires_at__lte=timezone.now(),
                order__payment_method__in=('eur_paypal', 'int_paypal'),
            )
            .order_by('expires_at', 'pk')
            .values_list('order_id', flat=True)
        )
        released_count = sum(
            release_paypal_stock(
                order_id,
                'expired',
                payment_status='expired',
            )
            for order_id in expired_order_ids
        )
        self.stdout.write(
            self.style.SUCCESS(f'Released {released_count} expired PayPal stock reservation(s).')
        )
