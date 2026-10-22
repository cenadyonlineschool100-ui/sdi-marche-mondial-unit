"""
Utilitaires pour l'optimisation et la gestion des images de produits
"""
from PIL import Image
from io import BytesIO
from django.core.files.base import ContentFile
import os
import requests
from django.conf import settings
from django.core.files.storage import default_storage
from urllib.parse import quote_plus


def optimize_image(image_file, max_width=1200, max_height=1200, quality=85):
    """
    Optimise une image en :
    - Redimensionnant aux dimensions max
    - Compressant la qualité
    - Convertissant en WebP si possible
    
    Args:
        image_file: Fichier image Django
        max_width: Largeur maximale en pixels
        max_height: Hauteur maximale en pixels
        quality: Qualité JPEG/WebP (1-100)
    
    Returns:
        Fichier optimisé ou l'original si erreur
    """
    try:
        # Ouvrir l'image
        img = Image.open(image_file)
        
        # Convertir en RGB si PNG avec transparence
        if img.mode in ('RGBA', 'LA', 'P'):
            rgb_img = Image.new('RGB', img.size, (255, 255, 255))
            rgb_img.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = rgb_img
        
        # Redimensionner avec aspect ratio préservé
        img.thumbnail((max_width, max_height), Image.Resampling.LANCZOS)
        
        # Sauvegarder optimisé
        output = BytesIO()
        img.save(output, format='JPEG', quality=quality, optimize=True)
        output.seek(0)
        
        # Créer un nom de fichier
        filename = os.path.splitext(image_file.name)[0] + '_optimized.jpg'
        
        return ContentFile(output.read(), name=filename)
    
    except Exception as e:
        print(f"Erreur optimisation image: {e}")
        return image_file


def generate_product_image(product_name):
    """
    Génère automatiquement une image de produit basée sur le nom.
    Utilise une source gratuite si la clé API Unsplash n'est pas configurée.
    """
    search_query = quote_plus(product_name.strip() or 'produit')
    access_key = getattr(settings, 'UNSPLASH_ACCESS_KEY', '')

    # Si une clé Unsplash valide est fournie, tenter la recherche API
    if access_key and access_key != 'YOUR_UNSPLASH_ACCESS_KEY_HERE':
        try:
            url = f"https://api.unsplash.com/search/photos?query={search_query}&per_page=1&client_id={access_key}"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get('results'):
                    return data['results'][0]['urls']['regular']
        except Exception as e:
            print(f"Erreur génération image Unsplash API: {e}")

    # Sans clé ou si l'API échoue, utiliser une source plus stable
    fallback_query = product_name.strip().replace(' ', '+') or 'produit'
    return f"https://loremflickr.com/400/300/{fallback_query}?random=0"


def get_image_suggestions(product_name, count=3):
    """
    Retourne plusieurs suggestions d'images pour un produit.
    """
    search_query = quote_plus(product_name.strip() or 'produit')
    access_key = getattr(settings, 'UNSPLASH_ACCESS_KEY', '')

    if access_key and access_key != 'YOUR_UNSPLASH_ACCESS_KEY_HERE':
        try:
            url = f"https://api.unsplash.com/search/photos?query={search_query}&per_page={count}&client_id={access_key}"
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                data = response.json()
                return [result['urls']['regular'] for result in data.get('results', [])]
        except Exception as e:
            print(f"Erreur suggestions images Unsplash API: {e}")

    # Fallback vers LoremFlickr pour des suggestions d'images stables
    fallback_query = product_name.strip().replace(' ', ',') or 'produit'
    return [
        f"https://loremflickr.com/400/300/{fallback_query}?random={i}"
        for i in range(count)
    ]


def generate_thumbnail(image_file, size=(300, 300), quality=80):
    """
    Génère une miniature (thumbnail) d'une image
    
    Args:
        image_file: Fichier image
        size: Dimensions (width, height)
        quality: Qualité JPEG
    
    Returns:
        Fichier miniature
    """
    try:
        img = Image.open(image_file)
        
        if img.mode in ('RGBA', 'LA', 'P'):
            rgb_img = Image.new('RGB', img.size, (255, 255, 255))
            rgb_img.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = rgb_img
        
        img.thumbnail(size, Image.Resampling.LANCZOS)
        
        output = BytesIO()
        img.save(output, format='JPEG', quality=quality, optimize=True)
        output.seek(0)
        
        filename = os.path.splitext(image_file.name)[0] + '_thumb.jpg'
        return ContentFile(output.read(), name=filename)
    
    except Exception as e:
        print(f"Erreur génération thumbnail: {e}")
        return image_file


def get_image_dimensions(image_file):
    """
    Récupère les dimensions d'une image
    
    Returns:
        Tuple (width, height) ou None
    """
    try:
        img = Image.open(image_file)
        return img.size
    except:
        return None


def validate_image(image_file, max_size_mb=5):
    """
    Valide une image
    
    Args:
        image_file: Fichier image
        max_size_mb: Taille maximale en MB
    
    Returns:
        Tuple (is_valid, error_message)
    """
    # Vérifier taille
    if image_file.size > (max_size_mb * 1024 * 1024):
        return False, f"Image trop grande (max {max_size_mb}MB)"
    
    # Vérifier format
    try:
        img = Image.open(image_file)
        img.verify()
        return True, None
    except Exception as e:
        return False, f"Format image invalide: {str(e)}"


def convert_to_webp(image_path, quality=80):
    """
    Convertit une image sur disque en WebP et retourne le chemin du fichier WebP.
    Si le fichier WebP existe déjà, ne refait pas la conversion.

    Args:
        image_path: Chemin absolu vers le fichier image source
        quality: Qualité WebP (0-100)

    Returns:
        webp_path (str) ou None si échec
    """
    try:
        if not os.path.exists(image_path):
            return None

        base, ext = os.path.splitext(image_path)
        webp_path = base + '.webp'

        # Skip if already exists
        if os.path.exists(webp_path):
            return webp_path

        img = Image.open(image_path)

        # Convert RGBA to RGB with white background to avoid alpha issues
        if img.mode in ('RGBA', 'LA', 'P'):
            rgb_img = Image.new('RGB', img.size, (255, 255, 255))
            rgb_img.paste(img, mask=img.split()[-1] if img.mode == 'RGBA' else None)
            img = rgb_img

        img.save(webp_path, 'WEBP', quality=quality, method=6)
        return webp_path

    except Exception as e:
        print(f"Erreur conversion WebP pour {image_path}: {e}")
        return None


def generate_banner_variants(image_field, widths=(480, 768, 1024, 1280, 1600)):
    """Create real, non-upscaled WebP/AVIF banner variants in local storage."""
    if not image_field or not image_field.name or image_field.name.startswith(('http://', 'https://')):
        return []
    try:
        with default_storage.open(image_field.name, 'rb') as source_file:
            source = Image.open(source_file).convert('RGB')
            base, _ = os.path.splitext(image_field.name)
            generated = []
            for width in widths:
                if source.width < width:
                    continue
                resized = source.copy()
                resized.thumbnail((width, 800), Image.Resampling.LANCZOS)
                for extension, image_format, save_options in (
                    ('webp', 'WEBP', {'quality': 84, 'method': 6}),
                    ('avif', 'AVIF', {'quality': 55}),
                ):
                    name = f'{base}_{width}w.{extension}'
                    output = BytesIO()
                    resized.save(output, format=image_format, **save_options)
                    if default_storage.exists(name):
                        default_storage.delete(name)
                    default_storage.save(name, ContentFile(output.getvalue()))
                    generated.append(name)
            return generated
    except (OSError, ValueError):
        return []
