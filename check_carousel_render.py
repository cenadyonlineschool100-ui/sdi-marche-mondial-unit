#!/usr/bin/env python
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sdi_market.settings')
django.setup()

from django.test import Client

client = Client()
response = client.get('/')
html = response.content.decode('utf-8')

# Chercher les clés
found_heading = 'Produits en vedette' in html
found_carousel = '.shop-carousel' in html or 'shop-carousel' in html
found_banner_carousel_products = 'banner_carousel_products' in html

print(f"Heading 'Produits en vedette': {found_heading}")
print(f"Carousel class or id: {found_carousel}")
print(f"Variable banner_carousel_products: {found_banner_carousel_products}")

# Si le carrousel est là, chercher le nombre de slides
if found_carousel:
    slide_count = html.count('carousel-slide')
    print(f"Number of carousel-slide divs: {slide_count}")
    print(f"\n✓ Carousel is rendered in HTML")
else:
    print(f"\n✗ Carousel NOT found in HTML")

# Afficher un aperçu
if found_heading:
    idx = html.find('Produits en vedette')
    section = html[max(0, idx-200):min(len(html), idx+500)]
    print(f"\nHTML around heading:")
    print(section)
