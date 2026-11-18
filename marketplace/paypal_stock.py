from datetime import timedelta

from django.conf import settings
from django.db import OperationalError, connection, transaction
from django.db.models import F
from django.utils import timezone

from .models import (
    Order,
    PayPalPayment,
    PayPalStockEvent,
    PayPalStockReservation,
    PayPalStockReservationItem,
    Product,
    Transaction,
)


class StockReservationUnavailable(Exception):
    pass


class InsufficientStock(Exception):
    pass


class StockContention(InsufficientStock):
    pass


def decrement_available_stock(product_id, quantity):
    try:
        updated = Product.objects.filter(
            pk=product_id,
            quantity__gte=quantity,
        ).update(quantity=F('quantity') - quantity)
    except OperationalError as exc:
        message = str(exc).lower()
        if connection.vendor == 'sqlite' and (
            'database is locked' in message or 'table is locked' in message
        ):
            raise StockContention from exc
        raise
    if updated != 1:
        raise InsufficientStock


def _reservation_expiry():
    ttl_hours = settings.PAYPAL_STOCK_RESERVATION_TTL_HOURS
    if ttl_hours <= 0:
        raise ValueError('PAYPAL_STOCK_RESERVATION_TTL_HOURS must be positive.')
    return timezone.now() + timedelta(hours=ttl_hours)


def create_paypal_stock_reservation(order, order_items):
    reservation = PayPalStockReservation.objects.create(
        order=order,
        expires_at=_reservation_expiry(),
    )
    for product, quantity in sorted(order_items, key=lambda item: item[0].pk):
        PayPalStockReservationItem.objects.create(
            reservation=reservation,
            product=product,
            product_id_snapshot=product.pk,
            product_name=product.name,
            quantity=quantity,
        )
        PayPalStockEvent.objects.create(
            order=order,
            product=product,
            product_name=product.name,
            quantity=quantity,
            event_type='reserved',
            reason='paypal_order_created',
        )
    return reservation


def release_paypal_stock(order_id, reason, *, payment_status=None):
    with transaction.atomic():
        payment = PayPalPayment.objects.select_for_update().filter(
            order_id=order_id,
        ).first()
        order = Order.objects.select_for_update().get(pk=order_id)
        reservation = PayPalStockReservation.objects.select_for_update().filter(
            order=order,
        ).first()
        if (
            reservation is None
            or reservation.status not in (
                {'reserved', 'capturing'} if reason == 'denied' else {'reserved'}
            )
            or order.payment_status == 'approved'
            or order.status != 'pending'
            or (payment and payment.status == 'completed')
        ):
            return False

        items = list(reservation.items.order_by('product_id_snapshot'))
        if any(item.product_id is None for item in items):
            return False
        for item in items:
            product = Product.objects.select_for_update().get(pk=item.product_id)
            Product.objects.filter(pk=product.pk).update(
                quantity=F('quantity') + item.quantity,
            )
            PayPalStockEvent.objects.create(
                order=order,
                product=product,
                product_name=item.product_name,
                quantity=item.quantity,
                event_type='expired' if reason == 'expired' else 'released',
                reason=reason,
            )
            item.product = None
            item.save(update_fields=['product'])

        reservation.status = 'released'
        reservation.released_at = timezone.now()
        reservation.save(update_fields=['status', 'released_at', 'updated_at'])

        if payment_status and payment and payment.status != 'completed':
            payment.status = payment_status
            payment.save(update_fields=['status', 'updated_at'])
        if payment_status in {'expired', 'failed'}:
            order.payment_status = 'failed'
            order.save(update_fields=['payment_status'])
        if payment and payment.transaction and payment.transaction.status == 'pending':
            payment.transaction.status = 'rejected' if reason == 'denied' else 'cancelled'
            payment.transaction.save(update_fields=['status'])
        elif payment is None and reason == 'expired':
            pending_transaction = Transaction.objects.filter(
                sender=order.buyer,
                type=f'payment_{order.payment_method}',
                status='pending',
                created_at__gte=order.created_at,
            ).order_by('-created_at', '-pk').first()
            if pending_transaction:
                pending_transaction.status = 'cancelled'
                pending_transaction.save(update_fields=['status'])
        return True


def reserve_stock_for_retry(order_id):
    try:
        with transaction.atomic():
            order = Order.objects.select_for_update().get(pk=order_id)
            reservation = PayPalStockReservation.objects.select_for_update().filter(
                order=order,
            ).first()
            if (
                reservation is None
                or reservation.status == 'consumed'
                or order.payment_status == 'approved'
                or order.status != 'pending'
            ):
                return False
            if reservation.status == 'reserved':
                return True
            if reservation.status == 'capturing':
                return False

            items = list(reservation.items.order_by('product_id_snapshot'))
            products = {
                product.pk: product
                for product in Product.objects.select_for_update().filter(
                    pk__in=[item.product_id_snapshot for item in items],
                ).order_by('pk')
            }
            if any(
                item.product_id_snapshot not in products
                or products[item.product_id_snapshot].quantity < item.quantity
                for item in items
            ):
                return False

            for item in items:
                product = products[item.product_id_snapshot]
                decrement_available_stock(product.pk, item.quantity)
                item.product = product
                item.save(update_fields=['product'])
                PayPalStockEvent.objects.create(
                    order=order,
                    product=product,
                    product_name=item.product_name,
                    quantity=item.quantity,
                    event_type='re_reserved',
                    reason='paypal_retry',
                )

            reservation.status = 'reserved'
            reservation.expires_at = _reservation_expiry()
            reservation.released_at = None
            reservation.save(update_fields=['status', 'expires_at', 'released_at', 'updated_at'])
            return True
    except InsufficientStock:
        return False


def begin_paypal_capture(payment_id):
    with transaction.atomic():
        payment = PayPalPayment.objects.select_for_update().get(pk=payment_id)
        order = Order.objects.select_for_update().get(pk=payment.order_id)
        reservation = PayPalStockReservation.objects.select_for_update().filter(
            order=order,
        ).first()
        if payment.status == 'completed' and order.payment_status == 'approved':
            return False
        if (
            reservation is None
            or reservation.status != 'reserved'
            or reservation.expires_at <= timezone.now()
            or order.payment_status == 'approved'
            or order.status != 'pending'
        ):
            return False
        reservation.status = 'capturing'
        reservation.save(update_fields=['status', 'updated_at'])
        return True


def cancel_paypal_capture(payment_id):
    with transaction.atomic():
        payment = PayPalPayment.objects.select_for_update().get(pk=payment_id)
        reservation = PayPalStockReservation.objects.select_for_update().filter(
            order_id=payment.order_id,
        ).first()
        if reservation and reservation.status == 'capturing':
            reservation.status = 'reserved'
            reservation.save(update_fields=['status', 'updated_at'])


def consume_paypal_stock(payment, order):
    reservation = PayPalStockReservation.objects.select_for_update().filter(
        order=order,
    ).first()
    if reservation is None:
        raise StockReservationUnavailable('PayPal order has no stock reservation.')
    if reservation.status == 'consumed':
        return
    if reservation.status == 'reserved' and reservation.expires_at <= timezone.now():
        raise StockReservationUnavailable('PayPal stock reservation has expired.')
    if reservation.status not in {'reserved', 'capturing'}:
        raise StockReservationUnavailable('PayPal stock reservation is no longer active.')

    items = list(reservation.items.order_by('product_id_snapshot'))
    if any(item.product_id is None for item in items):
        raise StockReservationUnavailable('Reserved product no longer exists.')
    for item in items:
        PayPalStockEvent.objects.create(
            order=order,
            product_id=item.product_id,
            product_name=item.product_name,
            quantity=item.quantity,
            event_type='consumed',
            reason='paypal_capture_completed',
        )
        item.product = None
        item.save(update_fields=['product'])
    reservation.status = 'consumed'
    reservation.save(update_fields=['status', 'updated_at'])
