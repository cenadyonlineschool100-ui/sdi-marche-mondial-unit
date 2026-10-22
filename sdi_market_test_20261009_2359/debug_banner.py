#!/usr/bin/env python
"""Debug script to check banner products in home view."""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sdi_market.settings')
django.setup()

from django.test import RequestFactory
from marketplace.views import home, get_banner_eligible_products

# Test 1: Call the function directly
print("=" * 60)
print("TEST 1: get_banner_eligible_products()")
print("=" * 60)
try:
    products = get_banner_eligible_products(limit=8)
    print(f"✓ Function returned {len(products)} products")
    for i, p in enumerate(products[:3]):
        print(f"  {i+1}. {p.name} (image: {bool(p.custom_image or p.image)}, stock: {p.quantity})")
except Exception as e:
    print(f"✗ Error: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

# Test 2: Call the view
print("\n" + "=" * 60)
print("TEST 2: home() view")
print("=" * 60)
try:
    factory = RequestFactory()
    request = factory.get('/')
    response = home(request)
    
    # Check context
    context = response.context_data if hasattr(response, 'context_data') else {}
    banner_products = context.get('banner_carousel_products', [])
    
    print(f"✓ View executed successfully")
    print(f"  - banner_carousel_products in context: {banner_products is not None}")
    print(f"  - Number of products: {len(banner_products) if banner_products else 0}")
    if banner_products:
        for i, p in enumerate(banner_products[:3]):
            print(f"    {i+1}. {p.name}")
except Exception as e:
    print(f"✗ Error: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()
