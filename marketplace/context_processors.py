"""
Marketplace context processors with graceful fallbacks for deployment
"""


def navigation_context(request):
    """Add navigation configuration to context"""
    return {
        'marketplace_inactivity_timeout_seconds': 600,
    }


def currency_context(request):
    """Add currency information to context"""
    return {
        'current_currency': 'USD',
        'current_currency_symbol': '$',
        'currency_choices': [
            ('USD', 'USD'),
            ('EUR', 'EUR'),
            ('HTG', 'HTG'),
            ('DOP', 'DOP'),
        ],
        'price_conversion_note': 'Prix indicatif – paiement final selon la méthode choisie',
    }


def site_config_context(request):
    """Add site configuration to context"""
    return {'site_configs': {}}


def activity_menu_context(request):
    """Add activity menu items to context"""
    return {'activity_menu_items': []}


def private_chat_context(request):
    """Add private chat information to context"""
    return {'unread_message_count': 0}


def announcement_context(request):
    """Add admin announcements to context"""
    return {'admin_announcements': []}


def site_banner_context(request):
    """Expose the latest active site banner and its eligible products."""
    try:
        from django.db import models
        from .models import Product, SiteBanner, SystemSettings

        settings_obj = SystemSettings.objects.filter(pk=1).first()
        if settings_obj and not settings_obj.banner_enabled:
            return {
                'site_banner': None,
                'site_banner_access_granted': False,
                'banner_carousel_products': [],
            }
        is_principal = request.user.is_authenticated and (request.user.is_superuser or request.user.role == 'super_admin')
        is_admin = request.user.is_authenticated and request.user.is_staff
        if settings_obj and is_admin and not is_principal and not settings_obj.banner_visible_to_admins:
            return {
                'site_banner': None,
                'site_banner_access_granted': False,
                'banner_carousel_products': [],
            }
        if settings_obj and is_principal and not settings_obj.principal_banner_visible:
            return {
                'site_banner': None,
                'site_banner_access_granted': False,
                'banner_carousel_products': [],
            }

        banners = SiteBanner.get_active_banners().prefetch_related('images', 'shops')
        shop_id = getattr(getattr(request, 'resolver_match', None), 'kwargs', {}).get('shop_id')
        if shop_id:
            banners = banners.filter(
                models.Q(scope='all') |
                models.Q(scope='selected', shops__id=shop_id)
            ).distinct()

        banner = next(
            (
                item for item in banners
                if item.can_access(request.user)
                or (item.access_mode == 'paid' and request.user.is_authenticated)
            ),
            None,
        )

        products = Product.objects.filter(
            quantity__gt=0,
            banner_display_allowed=True,
            banner_blocked_by_admin__isnull=True,
        ).select_related('shop', 'category', 'priority_group').order_by('-created_at')
        eligible_products = [product for product in products if product.has_valid_image() and (not product.priority_group or product.priority_group.is_scheduled_active())]
        eligible_products.sort(
            key=lambda product: (
                product.priority_group.priority if product.priority_group else 100,
                -(product.priority_group.weight if product.priority_group else 1),
                product.banner_priority,
                -(product.banner_weight or 1),
                -product.created_at.timestamp(),
            )
        )
        eligible_products = _interleave_banner_products(eligible_products)
        banner_rotation_schedule = _build_banner_rotation_schedule(eligible_products)

        return {
            'site_banner': banner,
            'site_banner_access_granted': banner.can_access(request.user) if banner else False,
            'banner_carousel_products': eligible_products,
            'banner_rotation_schedule': banner_rotation_schedule,
            'banner_expand_enabled': settings_obj.banner_expand_enabled if settings_obj else False,
            'banner_normal_height': settings_obj.banner_normal_height if settings_obj else 150,
            'banner_expanded_height': settings_obj.banner_expanded_height if settings_obj else 220,
        }
    except Exception:
        return {
            'site_banner': None,
            'site_banner_access_granted': False,
            'banner_carousel_products': [],
            'banner_rotation_schedule': [],
        }


def _interleave_banner_products(products):
    """Order products by group weight while emitting each product once."""
    groups = {}
    for product in products:
        key = product.priority_group_id or 0
        groups.setdefault(key, []).append(product)

    credits = {key: 0 for key in groups}
    ordered = []
    last_group = None
    while any(groups.values()):
        available_keys = [key for key, items in groups.items() if items]
        total_weight = sum(
            groups[key][0].priority_group.weight if groups[key][0].priority_group else 1
            for key in available_keys
        )
        for key in available_keys:
            credits[key] += groups[key][0].priority_group.weight if groups[key][0].priority_group else 1
        candidates = [key for key in available_keys if len(available_keys) == 1 or key != last_group]
        selected_key = max(
            candidates or available_keys,
            key=lambda key: (
                credits[key],
                -(groups[key][0].priority_group.priority if groups[key][0].priority_group else 100),
            ),
        )
        selected = groups[selected_key]
        product = selected.pop(0)
        ordered.append(product)
        credits[selected_key] -= total_weight
        last_group = product.priority_group_id or 0
    return ordered


def _build_banner_rotation_schedule(products, length=None):
    """Build a deterministic weighted schedule while preserving group turns."""
    if not products:
        return []
    scores = [
        max(1, product.banner_weight or 1) * (
            product.priority_group.weight if product.priority_group else 1
        )
        for product in products
    ]
    schedule_length = length or min(120, max(12, sum(scores)))
    credits = [0] * len(products)
    schedule = []
    last_product = None
    last_group = None
    total_score = sum(scores)
    has_multiple_groups = len({product.priority_group_id or 0 for product in products}) > 1
    for _ in range(schedule_length):
        for index, score in enumerate(scores):
            credits[index] += score
        group_candidates = [
            index for index, product in enumerate(products)
            if not has_multiple_groups or (product.priority_group_id or 0) != last_group
        ]
        candidates = group_candidates or list(range(len(products)))
        selected = max(candidates, key=lambda index: (credits[index], -index))
        credits[selected] -= total_score
        schedule.append(selected)
        last_product = selected
        last_group = products[selected].priority_group_id or 0
    return schedule


def system_settings_context(request):
    """Provide a safe fallback for the system settings singleton.

    This avoids crashes when the database has not been migrated yet or the
    singleton record is not present.
    """
    return {'system_settings': None}
