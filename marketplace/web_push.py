import json
import logging
from urllib.parse import urlsplit

from django.conf import settings
from django.utils import timezone

from .models import PersistentNotification, PushSubscription


logger = logging.getLogger(__name__)


def _safe_target_url(target_url):
    if not target_url or not target_url.startswith('/') or target_url.startswith('//') or '\\' in target_url:
        return '/notifications/'
    parsed = urlsplit(target_url)
    if parsed.scheme or parsed.netloc:
        return '/notifications/'
    return target_url


def _send_payload_to_user(user_id, payload):
    private_key = getattr(settings, 'WEB_PUSH_VAPID_PRIVATE_KEY', '')
    public_key = getattr(settings, 'WEB_PUSH_VAPID_PUBLIC_KEY', '')
    if not private_key or not public_key:
        return

    try:
        from pywebpush import WebPushException, webpush

        subscriptions = PushSubscription.objects.filter(user_id=user_id, is_active=True)

        for subscription in subscriptions:
            try:
                webpush(
                    subscription_info={
                        'endpoint': subscription.endpoint,
                        'keys': {'p256dh': subscription.p256dh, 'auth': subscription.auth},
                    },
                    data=payload,
                    vapid_private_key=private_key,
                    vapid_claims={'sub': settings.WEB_PUSH_VAPID_CLAIMS_EMAIL},
                    ttl=60,
                )
                PushSubscription.objects.filter(pk=subscription.pk).update(last_used_at=timezone.now())
            except WebPushException as exc:
                status_code = getattr(getattr(exc, 'response', None), 'status_code', None)
                if status_code in (404, 410):
                    PushSubscription.objects.filter(pk=subscription.pk).update(is_active=False)
                else:
                    logger.warning('Web Push delivery failed for subscription %s: %s', subscription.pk, exc)
            except Exception:
                logger.exception('Web Push delivery failed for subscription %s', subscription.pk)
    except Exception:
        logger.exception('Unable to dispatch Web Push')


def send_notification_push(notification_id):
    """Deliver an existing SDI notification to registered devices without affecting its creation."""
    try:
        notification = PersistentNotification.objects.get(pk=notification_id, is_read=False)
    except PersistentNotification.DoesNotExist:
        return

    _send_payload_to_user(notification.recipient_id, json.dumps({
        'id': notification.pk,
        'title': 'SDI MICROTECH GLOBAL MARKET UNIT',
        'body': 'Vous avez une nouvelle notification sur SDI.',
        'url': _safe_target_url(notification.target_url),
    }))


def send_notification_dismissal(user_id, notification_id=None):
    """Close a previously delivered browser notification after it is read in SDI."""
    _send_payload_to_user(user_id, json.dumps({'action': 'dismiss', 'id': notification_id}))