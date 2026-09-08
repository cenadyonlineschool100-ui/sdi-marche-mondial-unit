#!/usr/bin/env python
"""Test script to verify carousel HTML rendering."""
import os
import django
from django.test import Client

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'sdi_market.settings')
django.setup()

client = Client()
response = client.get('/')

# Vérifier si le carrousel est dans la réponse
html = response.content.decode('utf-8')

has_carousel_heading = 'Produits en vedette' in html
has_carousel_container = 'shop-carousel' in html
has_carousel_track = 'carousel-track' in html
has_carousel_slide = 'carousel-slide' in html
has_carousel_button = 'banner-carousel-prev' in html

print(f"✓ Carrousel dans HTML:")
print(f"  - 'Produits en vedette' heading: {has_carousel_heading}")
print(f"  - '.shop-carousel' class: {has_carousel_container}")
print(f"  - '#banner-carousel-track' id: {has_carousel_track}")
print(f"  - '.carousel-slide' class: {has_carousel_slide}")
print(f"  - button ids: {has_carousel_button}")

# Afficher un aperçu de la section du carrousel si elle existe
if has_carousel_heading:
    # Chercher la section du carrousel
    idx = html.find('Produits en vedette')
    if idx > 0:
        section = html[max(0, idx-200):min(len(html), idx+800)]
        print(f"\nAperçu de la section (from -200 to +800):")
        print(section[:500] + "...")
else:
    print("\n⚠ Le carrousel ne semble pas être présent dans le HTML!")
    # Afficher les premières 2000 caractères du body pour déboguer
    body_start = html.find('<body')
    if body_start > 0:
        print("\nPremiers 2000 chars du body:")
        print(html[body_start:body_start+2000])
