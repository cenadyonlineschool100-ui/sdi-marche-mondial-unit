from decimal import Decimal

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.text import slugify

from marketplace.models import Category, Product, Shop


class Command(BaseCommand):
    help = 'Ajoute des produits locaux de test pour valider la grille produits.'

    def add_arguments(self, parser):
        parser.add_argument('--count', type=int, default=20)
        parser.add_argument('--prefix', default='Produit test responsive')
        parser.add_argument('--remove', action='store_true')

    @transaction.atomic
    def handle(self, *args, **options):
        prefix = options['prefix'].strip()
        count = options['count']

        if not prefix:
            raise CommandError('Le préfixe ne peut pas être vide.')

        if options['remove']:
            deleted, _ = Product.objects.filter(name__startswith=prefix).delete()
            self.stdout.write(self.style.SUCCESS(f'{deleted} produit(s) de test supprimé(s).'))
            return

        if count < 1 or count > 100:
            raise CommandError('Le nombre doit être compris entre 1 et 100.')

        shop = Shop.objects.select_related('owner').order_by('id').first()
        if not shop:
            raise CommandError('Aucune boutique existante: création annulée.')

        category = Category.objects.filter(is_active=True).order_by('id').first()
        existing_names = set(Product.objects.filter(name__startswith=prefix).values_list('name', flat=True))
        created = []

        for index in range(1, count + 1):
            name = f'{prefix} {index:02d}'
            if name in existing_names:
                continue

            created.append(Product(
                shop=shop,
                category=category,
                name=name,
                description='Produit local de test pour la validation de la grille responsive.',
                price_ht=Decimal(index),
                price_original=Decimal(index),
                price_original_currency='USD',
                price_input_currency='USD',
                quantity=10,
                image=f'https://placehold.co/600x400/png?text={slugify(name)}',
            ))

        Product.objects.bulk_create(created)
        self.stdout.write(self.style.SUCCESS(
            f'{len(created)} produit(s) de test créé(s) dans « {shop.name} ».'
        ))
        self.stdout.write('Pour les retirer: python manage.py seed_product_test_data --remove')
