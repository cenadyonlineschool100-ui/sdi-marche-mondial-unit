import json
import logging
import uuid
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.contrib.auth.decorators import login_required

from .models import Order, PayPalPayment, PayPalWebhookEvent, Transaction
from .paypal_gateway import (
    PayPalAPIError,
    PayPalConfigurationError,
    paypal_api_request,
    verify_webhook_signature,
)
from .paypal_stock import (
    StockReservationUnavailable,
    begin_paypal_capture,
    cancel_paypal_capture,
    consume_paypal_stock,
    release_paypal_stock,
    reserve_stock_for_retry,
)


logger = logging.getLogger(__name__)
PAYPAL_METHODS = {'eur_paypal', 'int_paypal'}


def _paypal_is_configured():
    return settings.PAYPAL_CHECKOUT_ENABLED


def _pending_transaction(order):
    return Transaction.objects.filter(
        sender=order.buyer,
        type=f'payment_{order.payment_method}',
        amount=order.total_amount,
        status='pending',
        created_at__gte=order.created_at,
    ).order_by('-created_at', '-pk').first()


def _get_or_create_payment(order):
    payment, _ = PayPalPayment.objects.get_or_create(
        order=order,
        defaults={
            'transaction': _pending_transaction(order),
            'amount': order.total_amount,
            'currency': 'USD',
        },
    )
    return payment


def _capture_amount(capture):
    try:
        amount = Decimal(capture['amount']['value'])
    except (KeyError, TypeError, InvalidOperation) as exc:
        raise PayPalAPIError('PayPal returned an invalid capture amount.') from exc
    if not amount.is_finite() or amount <= 0:
        raise PayPalAPIError('PayPal returned an invalid capture amount.')
    return amount, capture.get('amount', {}).get('currency_code')


def _complete_payment(payment_id, capture):
    capture_id = capture.get('id')
    if not capture_id or capture.get('status') != 'COMPLETED':
        raise PayPalAPIError('PayPal did not confirm a completed capture.')

    amount, currency = _capture_amount(capture)
    with transaction.atomic():
        payment = PayPalPayment.objects.select_for_update().select_related(
            'order', 'transaction'
        ).get(pk=payment_id)
        order = Order.objects.select_for_update().get(pk=payment.order_id)

        if payment.status == 'completed':
            if payment.capture_id != capture_id:
                raise PayPalAPIError('A different capture is already recorded.')
            return payment
        if (
            currency != 'USD'
            or payment.currency != 'USD'
            or amount != payment.amount
            or payment.amount != order.total_amount
            or order.payment_method not in PAYPAL_METHODS
        ):
            raise PayPalAPIError('PayPal capture does not match the stored order.')
        try:
            consume_paypal_stock(payment, order)
        except StockReservationUnavailable as exc:
            raise PayPalAPIError('PayPal capture has no active stock reservation.') from exc

        payment.capture_id = capture_id
        payment.status = 'completed'
        payment.captured_at = timezone.now()
        payment.save(update_fields=['capture_id', 'status', 'captured_at', 'updated_at'])

        order.payment_status = 'approved'
        if order.status == 'pending':
            order.status = 'awaiting_delivery'
            order.save(update_fields=['payment_status', 'status'])
        else:
            order.save(update_fields=['payment_status'])
        if payment.transaction and payment.transaction.status != 'approved':
            payment.transaction.status = 'approved'
            payment.transaction.save(update_fields=['status'])
        if not Transaction.objects.filter(
            sender=order.buyer,
            type='escrow_hold',
            amount=order.total_amount,
            status='pending',
            created_at__gte=order.created_at,
        ).exists():
            Transaction.objects.create(
                sender=order.buyer,
                receiver=None,
                amount=order.total_amount,
                type='escrow_hold',
                status='pending',
            )
        return payment


@login_required
@require_POST
def paypal_create_order(request, order_id):
    order = get_object_or_404(Order, pk=order_id, buyer=request.user)
    if order.payment_method not in PAYPAL_METHODS:
        return JsonResponse({'error': 'Cette commande ne peut pas être payée avec PayPal.'}, status=400)
    if order.payment_status == 'approved':
        return JsonResponse({'error': 'Cette commande est déjà payée.'}, status=409)
    if not _paypal_is_configured():
        return JsonResponse({'error': 'PayPal Sandbox n’est pas encore configuré.'}, status=503)
    if order.total_amount <= 0:
        return JsonResponse({'error': 'Le montant de la commande est invalide.'}, status=400)
    if not getattr(order, 'paypal_stock_reservation', None):
        return JsonResponse({'error': 'La réservation de stock de cette commande est introuvable.'}, status=409)

    payment = _get_or_create_payment(order)
    if payment.amount != order.total_amount or payment.currency != 'USD':
        return JsonResponse({'error': 'Le montant enregistré ne correspond pas à la commande.'}, status=409)
    if payment.status == 'completed':
        return JsonResponse({'error': 'Cette commande est déjà payée.'}, status=409)
    reservation = getattr(order, 'paypal_stock_reservation', None)
    if reservation and reservation.status == 'reserved' and reservation.expires_at <= timezone.now():
        release_paypal_stock(
            order.pk,
            'expired',
            payment_status='expired',
        )
        payment.refresh_from_db()
        reservation.refresh_from_db()

    with transaction.atomic():
        payment = PayPalPayment.objects.select_for_update().get(pk=payment.pk)
        order = Order.objects.select_for_update().get(pk=order.pk)
        reservation = getattr(order, 'paypal_stock_reservation', None)
        needs_retry = payment.status in {'failed', 'cancelled', 'expired'} or (
            reservation and reservation.status == 'released'
        )
        if needs_retry:
            if not reserve_stock_for_retry(order.pk):
                return JsonResponse(
                    {'error': 'Le stock nécessaire n’est plus disponible pour cette nouvelle tentative.'},
                    status=409,
                )
            payment = PayPalPayment.objects.select_for_update().get(pk=payment.pk)
            if needs_retry:
                if payment.transaction and payment.transaction.status == 'pending':
                    payment.transaction.status = 'cancelled'
                    payment.transaction.save(update_fields=['status'])
                payment.transaction = Transaction.objects.create(
                    sender=order.buyer,
                    amount=order.total_amount,
                    type=f'payment_{order.payment_method}',
                    status='pending',
                )
                payment.paypal_order_id = None
                payment.request_id = uuid.uuid4()
                payment.status = 'created'
                payment.save(update_fields=[
                    'transaction', 'paypal_order_id', 'request_id', 'status', 'updated_at',
                ])
                order.payment_status = 'pending'
                order.save(update_fields=['payment_status'])

    if not payment.paypal_order_id:
        request_id = payment.request_id
        payload = {
            'intent': 'CAPTURE',
            'purchase_units': [{
                'reference_id': f'SDI-ORDER-{order.pk}',
                'custom_id': f'{order.pk}:{order.buyer_id}',
                'invoice_id': f'SDI-{order.pk}-{payment.request_id.hex}',
                'description': f'Commande SDI STORE #{order.pk}'[:127],
                'amount': {
                    'currency_code': 'USD',
                    'value': f'{order.total_amount:.2f}',
                },
            }],
            'application_context': {
                'brand_name': 'SDI STORE',
                'user_action': 'PAY_NOW',
                'return_url': request.build_absolute_uri(
                    reverse('order_confirm', args=[order.pk])
                ),
                'cancel_url': request.build_absolute_uri(
                    reverse('order_confirm', args=[order.pk])
                ),
            },
        }
        try:
            response = paypal_api_request(
                'POST',
                '/v2/checkout/orders',
                payload=payload,
                request_id=f'SDI-CREATE-{payment.request_id}',
            )
        except (PayPalAPIError, PayPalConfigurationError):
            logger.warning('PayPal order creation failed for local order %s.', order.pk)
            return JsonResponse({'error': 'PayPal ne peut pas créer le paiement pour le moment.'}, status=502)

        if not isinstance(response, dict):
            return JsonResponse({'error': 'PayPal a retourné une réponse de commande invalide.'}, status=502)
        paypal_order_id = response.get('id')
        if not paypal_order_id or response.get('status') != 'CREATED':
            logger.warning('PayPal returned an incomplete order for local order %s.', order.pk)
            return JsonResponse({'error': 'PayPal a retourné une réponse de commande invalide.'}, status=502)
        with transaction.atomic():
            payment = PayPalPayment.objects.select_for_update().get(pk=payment.pk)
            if payment.request_id != request_id or (
                payment.paypal_order_id and payment.paypal_order_id != paypal_order_id
            ):
                return JsonResponse({'error': 'Une autre tentative PayPal est déjà en cours.'}, status=409)
            payment.paypal_order_id = paypal_order_id
            payment.status = 'created'
            payment.save(update_fields=['paypal_order_id', 'status', 'updated_at'])

    return JsonResponse({'id': payment.paypal_order_id})


@login_required
@require_POST
def paypal_cancel_order(request, order_id):
    order = get_object_or_404(Order, pk=order_id, buyer=request.user)
    if order.payment_method not in PAYPAL_METHODS:
        return JsonResponse({'error': 'Cette commande ne peut pas être payée avec PayPal.'}, status=400)
    if not _paypal_is_configured():
        return JsonResponse({'error': 'PayPal Sandbox n’est pas encore configuré.'}, status=503)

    try:
        payload = json.loads(request.body or b'{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Requête d’annulation invalide.'}, status=400)
    paypal_order_id = payload.get('paypal_order_id') if isinstance(payload, dict) else None
    payment = get_object_or_404(PayPalPayment, order=order)
    if not paypal_order_id or paypal_order_id != payment.paypal_order_id:
        return JsonResponse({'error': 'Identifiant de paiement PayPal invalide.'}, status=400)
    if payment.status in {'failed', 'cancelled', 'expired'}:
        return JsonResponse({'status': payment.status})
    if payment.status == 'completed' or order.payment_status == 'approved':
        return JsonResponse({'error': 'Cette commande est déjà payée.'}, status=409)

    try:
        paypal_order = paypal_api_request(
            'GET', f'/v2/checkout/orders/{payment.paypal_order_id}'
        )
    except (PayPalAPIError, PayPalConfigurationError):
        logger.warning('PayPal cancellation check failed for local order %s.', order.pk)
        return JsonResponse({'error': 'PayPal ne peut pas vérifier l’annulation pour le moment.'}, status=502)
    if not isinstance(paypal_order, dict) or paypal_order.get('id') != payment.paypal_order_id:
        return JsonResponse({'error': 'PayPal a retourné une commande invalide.'}, status=502)
    if paypal_order.get('status') not in {'CREATED', 'VOIDED'}:
        return JsonResponse({'error': 'Cette tentative PayPal ne peut pas être annulée sans risque.'}, status=409)
    if not release_paypal_stock(
        order.pk,
        'user_cancelled',
        payment_status='cancelled',
    ):
        return JsonResponse({'error': 'Le stock est déjà consommé ou cette commande ne peut pas être annulée.'}, status=409)
    return JsonResponse({'status': 'CANCELLED'})


@login_required
@require_POST
def paypal_capture_order(request, order_id):
    order = get_object_or_404(Order, pk=order_id, buyer=request.user)
    if order.payment_method not in PAYPAL_METHODS:
        return JsonResponse({'error': 'Cette commande ne peut pas être payée avec PayPal.'}, status=400)

    try:
        payload = json.loads(request.body or b'{}')
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({'error': 'Requête de capture invalide.'}, status=400)
    paypal_order_id = payload.get('paypal_order_id') if isinstance(payload, dict) else None
    payment = get_object_or_404(PayPalPayment, order=order)
    if not paypal_order_id or paypal_order_id != payment.paypal_order_id:
        return JsonResponse({'error': 'Identifiant de paiement PayPal invalide.'}, status=400)
    if payment.status == 'completed':
        return JsonResponse({'status': 'COMPLETED', 'order_id': order.pk})
    if payment.status in {'failed', 'cancelled'}:
        return JsonResponse({'error': 'Cette tentative PayPal n’est plus active.'}, status=409)
    if payment.status == 'expired':
        return JsonResponse({'error': 'Cette tentative PayPal a expiré.'}, status=409)
    if not begin_paypal_capture(payment.pk):
        return JsonResponse({'error': 'La réservation de stock a expiré ou n’est plus active.'}, status=409)

    try:
        response = paypal_api_request(
            'POST',
            f'/v2/checkout/orders/{payment.paypal_order_id}/capture',
            payload={},
            request_id=f'SDI-CAPTURE-{payment.request_id}',
        )
        if not isinstance(response, dict):
            raise PayPalAPIError('PayPal returned an invalid order response.')
        if response.get('id') != payment.paypal_order_id:
            raise PayPalAPIError('PayPal returned a different order.')
        purchase_units = response.get('purchase_units') or []
        captures = (
            purchase_units[0].get('payments', {}).get('captures', [])
            if purchase_units else []
        )
        if not captures or purchase_units[0].get('reference_id') != f'SDI-ORDER-{order.pk}':
            raise PayPalAPIError('PayPal capture is not associated with this order.')
        capture = captures[0]
        _complete_payment(payment.pk, capture)
    except PayPalConfigurationError:
        cancel_paypal_capture(payment.pk)
        return JsonResponse({'error': 'La configuration PayPal est incomplète.'}, status=503)
    except PayPalAPIError:
        logger.warning('PayPal capture was not confirmed for local order %s.', order.pk)
        return JsonResponse({'error': 'PayPal n’a pas confirmé le paiement.'}, status=502)

    return JsonResponse({'status': 'COMPLETED', 'order_id': order.pk})


@csrf_exempt
@require_POST
def paypal_webhook(request):
    if not settings.PAYPAL_WEBHOOK_ID:
        return HttpResponse(status=503)
    try:
        event = json.loads(request.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return HttpResponse(status=400)
    if not isinstance(event, dict) or not event.get('id') or not event.get('event_type'):
        return HttpResponse(status=400)

    try:
        if not verify_webhook_signature(request, event):
            return HttpResponse(status=400)
    except (PayPalAPIError, PayPalConfigurationError):
        logger.warning('PayPal webhook signature verification is unavailable.')
        return HttpResponse(status=503)

    event_record, _ = PayPalWebhookEvent.objects.get_or_create(
        event_id=event['id'],
        defaults={'event_type': event['event_type']},
    )
    if event_record.processed_at:
        return HttpResponse(status=200)

    resource = event.get('resource') or {}
    related_ids = resource.get('supplementary_data', {}).get('related_ids', {})
    paypal_order_id = related_ids.get('order_id')
    if event['event_type'] in {
        'PAYMENT.CAPTURE.COMPLETED',
        'PAYMENT.CAPTURE.DENIED',
    } and (not paypal_order_id or not resource.get('id')):
        logger.warning('Verified PayPal capture webhook is missing association identifiers.')
        event_record.processed_at = timezone.now()
        event_record.save(update_fields=['processed_at'])
        return HttpResponse(status=200)
    try:
        payment = PayPalPayment.objects.select_related('order').get(
            paypal_order_id=paypal_order_id
        )
        if event['event_type'] == 'PAYMENT.CAPTURE.COMPLETED':
            capture_id = resource.get('id')
            capture = paypal_api_request(
                'GET', f'/v2/payments/captures/{capture_id}'
            )
            if not isinstance(capture, dict):
                raise PayPalAPIError('PayPal returned an invalid capture response.')
            if capture.get('id') != capture_id:
                raise PayPalAPIError('PayPal returned a different capture.')
            capture_order_id = capture.get(
                'supplementary_data', {}
            ).get('related_ids', {}).get('order_id')
            if capture_order_id != payment.paypal_order_id:
                raise PayPalAPIError('PayPal capture belongs to a different order.')
            _complete_payment(payment.pk, capture)
        elif event['event_type'] == 'PAYMENT.CAPTURE.DENIED':
            if payment.status != 'completed':
                released = release_paypal_stock(
                    payment.order_id,
                    'denied',
                    payment_status='failed',
                )
                if not released:
                    with transaction.atomic():
                        payment = PayPalPayment.objects.select_for_update().get(pk=payment.pk)
                        order = Order.objects.select_for_update().get(pk=payment.order_id)
                        if payment.status != 'completed' and order.payment_status != 'approved':
                            payment.status = 'failed'
                            payment.save(update_fields=['status', 'updated_at'])
                            order.payment_status = 'failed'
                            order.save(update_fields=['payment_status'])
    except PayPalPayment.DoesNotExist:
        logger.warning('Verified PayPal webhook has no matching local payment.')
    except (PayPalAPIError, PayPalConfigurationError):
        logger.warning('PayPal webhook processing failed for event %s.', event['id'])
        return HttpResponse(status=503)

    event_record.processed_at = timezone.now()
    event_record.save(update_fields=['processed_at'])
    return HttpResponse(status=200)
