#!/usr/bin/env python
import os
import sys
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sdi_market.settings')
sys.path.insert(0, r'c:\wamp64\www\SDI STORE 1\sdi_market')
django.setup()

# Import what we need
from marketplace.views import get_banner_eligible_products
from marketplace.models import Product

# Test
print("Testing get_banner_eligible_products()...")
try:
    products = get_banner_eligible_products(limit=8)
    print(f"Result type: {type(products)}")
    print(f"Number of products: {len(products)}")
    for p in products[:3]:
        print(f"  - {p.name}")
except Exception as e:
    print(f"ERROR: {e}")
    import traceback
    traceback.print_exc()

# Also check total products in DB
print("\nTotal products in database:")
total = Product.objects.count()
print(f"  {total} products")

# Check how many should be eligible
eligible = Product.objects.filter(
    quantity__gt=0,
    banner_display_allowed=True,
    banner_blocked_by_admin__isnull=True
).count()
print(f"  {eligible} should be eligible (stock > 0, not blocked)")
