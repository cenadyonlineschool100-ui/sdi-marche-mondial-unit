from django.core.management.base import BaseCommand
from django.conf import settings
from pathlib import Path
from marketplace.image_utils import convert_to_webp
import os

class Command(BaseCommand):
    help = 'Batch convertit les images JPEG/PNG du dossier MEDIA_ROOT en WebP (s'il n\'existe pas encore)'

    def add_arguments(self, parser):
        parser.add_argument('--path', type=str, help='Chemin relatif sous MEDIA_ROOT à convertir (ex: products/)', default='')
        parser.add_argument('--quality', type=int, help='Qualité WebP (0-100)', default=80)

    def handle(self, *args, **options):
        media_root = Path(settings.MEDIA_ROOT)
        rel_path = options.get('path') or ''
        quality = options.get('quality') or 80

        start_dir = media_root / rel_path
        if not start_dir.exists():
            self.stdout.write(self.style.ERROR(f"Le dossier {start_dir} n'existe pas."))
            return

        exts = ('.jpg', '.jpeg', '.png')
        converted = 0
        skipped = 0
        failed = 0

        for root, dirs, files in os.walk(start_dir):
            for fname in files:
                if fname.lower().endswith(exts):
                    src = os.path.join(root, fname)
                    try:
                        webp = convert_to_webp(src, quality=quality)
                        if webp:
                            converted += 1
                            self.stdout.write(self.style.SUCCESS(f"Converted: {src} -> {webp}"))
                        else:
                            skipped += 1
                    except Exception as e:
                        failed += 1
                        self.stdout.write(self.style.ERROR(f"Failed {src}: {e}"))

        self.stdout.write(self.style.NOTICE(f"Done. Converted: {converted}, Skipped: {skipped}, Failed: {failed}"))
