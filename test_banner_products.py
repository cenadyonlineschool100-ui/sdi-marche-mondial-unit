#!/usr/bin/env python
"""Test script to check banner-eligible products."""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sdi_market.settings')
django.setup()

from marketplace.models import Product
from django.db.models import Q, Avg, Count

# Vérifier les produits avec images valides
products_with_images = Product.objects.filter(
    Q(custom_image__isnull=False) | Q(image__isnull=False)
).count()

# Vérifier les produits éligibles
eligible = Product.objects.filter(
    quantity__gt=0,
    banner_display_allowed=True,
    banner_blocked_by_admin__isnull=True
).exclude(
    Q(custom_image__isnull=True) & Q(image__isnull=True)
).count()

print(f'Produits avec images: {products_with_images}')
print(f'Produits éligibles pour bannière: {eligible}')

# Afficher les 3 premiers produits éligibles
eligible_prods = Product.objects.filter(
    quantity__gt=0,
    banner_display_allowed=True,
    banner_blocked_by_admin__isnull=True
).exclude(
    Q(custom_image__isnull=True) & Q(image__isnull=True)
).select_related('shop').annotate(
    average_rating=Avg('reviews__rating', filter=Q(reviews__is_approved=True)),
    reviews_count=Count('reviews', filter=Q(reviews__is_approved=True))
)[:3]

print("\nPremiers produits éligibles:")
for p in eligible_prods:
    print(f"- {p.name} (shop: {p.shop.name}, image: {bool(p.custom_image or p.image)}, stock: {p.quantity})")
