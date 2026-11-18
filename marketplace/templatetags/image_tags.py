from django import template
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.conf import settings
from django.core.files.storage import default_storage
import os
from urllib.parse import urlparse
from urllib.parse import quote

register = template.Library()


@register.filter
def safe_image_url(image_file):
    """Return a local image URL only when the referenced file exists."""
    if not image_file:
        return ''
    name = getattr(image_file, 'name', None)
    storage = getattr(image_file, 'storage', None)
    if name and storage and not storage.exists(name):
        return ''
    return getattr(image_file, 'url', None) or str(image_file)


@register.simple_tag
def responsive_image(image_path, alt='', css_class='', sizes=None, element_id=None):
    """
    Rend un élément <picture> qui sert un WebP si disponible, sinon l'image d'origine.
    Utilise l'attribut `loading="lazy"` et des attributs `data-src` pour le lazy-loader JS.

    Args:
        image_path: ImageField ou URL string vers l'image source
        alt: texte alternatif
        css_class: classes CSS pour la balise img
        sizes: valeur sizes pour srcset (optionnel)
        element_id: identifiant HTML facultatif pour l'élément img
    """
    if not image_path:
        return ''

    image_url = getattr(image_path, 'url', None) or str(image_path)
    if not image_url:
        return ''

    parsed_url = urlparse(image_url)
    if parsed_url.scheme in ('http', 'https') and parsed_url.netloc:
        image_attrs = [f'class="{css_class} lazy-img"', f'data-src="{image_url}"', f'alt="{alt}"', 'loading="lazy"']
        if sizes:
            image_attrs.append(f'sizes="{sizes}"')
        if element_id:
            image_attrs.append(f'id="{element_id}"')
        return mark_safe(f'<img {" ".join(image_attrs)}>')

    media_url = settings.MEDIA_URL
    if image_url.startswith(media_url):
        rel = image_url[len(media_url):]
    else:
        rel = image_url.lstrip('/')

    if not default_storage.exists(rel):
        placeholder_svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="640" height="480" viewBox="0 0 640 480">'
            '<rect width="640" height="480" fill="#f1f3f5"/>'
            '<path d="M250 190h140v100H250z" fill="none" stroke="#87909a" stroke-width="12"/>'
            '<circle cx="290" cy="225" r="10" fill="#87909a"/>'
            '<path d="m260 275 40-35 25 22 22-18 33 31" fill="none" stroke="#87909a" stroke-width="10"/>'
            '</svg>'
        )
        placeholder_url = f'data:image/svg+xml,{quote(placeholder_svg)}'
        return format_html(
            '<img src="{}" class="{}" alt="Image indisponible" loading="lazy">',
            placeholder_url,
            css_class,
        )

    base, ext = os.path.splitext(rel)
    webp_rel = base + '.webp'
    webp_url = settings.MEDIA_URL + webp_rel
    webp_exists = default_storage.exists(webp_rel)

    image_attrs = [f'class="{css_class} lazy-img"', f'data-src="{settings.MEDIA_URL + rel}"', f'alt="{alt}"', 'loading="lazy"']
    if sizes:
        image_attrs.append(f'sizes="{sizes}"')
    if element_id:
        image_attrs.append(f'id="{element_id}"')
    image_attrs = ' '.join(image_attrs)

    if webp_exists:
        html = f'<picture>'
        html += f'<source data-srcset="{webp_url}" type="image/webp">'
        html += f'<img {image_attrs}>'
        html += '</picture>'
    else:
        html = f'<img {image_attrs}>'

    return mark_safe(html)
