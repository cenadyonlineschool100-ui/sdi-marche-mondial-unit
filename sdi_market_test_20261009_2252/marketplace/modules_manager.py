"""
Module Manager - Gestion centralisée des modules de Marché Mondial
Architecture modulaire avec lazy loading, cache et pagination
"""

from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Prefetch, F, Count, Sum
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework import status
from datetime import datetime, timedelta
import json

from .models import Product, Shop, Order, Wallet, Profile, Transaction
from .real_estate_models import Property


class ModuleConfig:
    """Configuration pour chaque module"""
    
    MODULES = {
        'boutique': {
            'name': 'Boutique',
            'description': 'E-commerce et vente de produits',
            'icon': 'shopping-bag',
            'model': Product,
            'default_cache_ttl': 3600,  # 1 heure
            'pagination': 20,
        },
        'microsdicash': {
            'name': 'MicroSDICash',
            'description': 'Paiements numériques et portefeuille',
            'icon': 'wallet',
            'model': Wallet,
            'default_cache_ttl': 300,  # 5 minutes
            'pagination': 50,
        },
        'tikane': {
            'name': 'Ti Kanè Digital',
            'description': 'Épargne numérique collaborative',
            'icon': 'piggy-bank',
            'model': None,  # Custom logic
            'default_cache_ttl': 1800,  # 30 minutes
            'pagination': 25,
        },
        'real_estate': {
            'name': 'Maisons à louer',
            'description': 'Immobilier et locations',
            'icon': 'home',
            'model': Property,
            'default_cache_ttl': 7200,  # 2 heures
            'pagination': 15,
        },
        'studio_beaute': {
            'name': 'Studio Beauté',
            'description': 'Services de beauté et bien-être',
            'icon': 'sparkles',
            'model': Product,  # Utilise Product avec catégorie spécifique
            'default_cache_ttl': 1800,
            'pagination': 12,
        },
        'formations': {
            'name': 'Formations',
            'description': 'Cours et formations en ligne',
            'icon': 'book-open',
            'model': Product,  # Utilise Product avec catégorie spécifique
            'default_cache_ttl': 7200,
            'pagination': 20,
        },
        'services_techniciens': {
            'name': 'Services Techniciens',
            'description': 'Services techniques et réparations',
            'icon': 'wrench',
            'model': Shop,  # Basé sur les shops avec catégorie
            'default_cache_ttl': 3600,
            'pagination': 25,
        },
    }


class ModuleCache:
    """Gestion du cache pour les modules"""
    
    CACHE_REGISTRY_KEY = 'module_cache_registry'
    
    @staticmethod
    def get_cache_key(module_name, user_id=None, page=1):
        """Génère une clé de cache unique"""
        if user_id:
            return f"module:{module_name}:user:{user_id}:page:{page}"
        return f"module:{module_name}:page:{page}"
    
    @staticmethod
    def get_stats_cache_key(module_name):
        """Clé pour les statistiques du module"""
        return f"stats:{module_name}"
    
    @staticmethod
    def _get_registry():
        registry = cache.get(ModuleCache.CACHE_REGISTRY_KEY)
        return registry if isinstance(registry, list) else []
    
    @staticmethod
    def _save_registry(registry):
        cache.set(ModuleCache.CACHE_REGISTRY_KEY, registry, None)
    
    @staticmethod
    def invalidate_module(module_name):
        """Invalide le cache d'un module"""
        registry = ModuleCache._get_registry()
        keys_to_delete = [key for key in registry if key.startswith(f"module:{module_name}:")]
        if keys_to_delete:
            cache.delete_many(keys_to_delete)
            registry = [key for key in registry if key not in keys_to_delete]
            ModuleCache._save_registry(registry)
        cache.delete(ModuleCache.get_stats_cache_key(module_name))
    
    @staticmethod
    def set_with_ttl(key, value, ttl=3600):
        """Stocke une valeur avec TTL"""
        cache.set(key, value, ttl)
        registry = ModuleCache._get_registry()
        if key not in registry:
            registry.append(key)
            ModuleCache._save_registry(registry)
    
    @staticmethod
    def get_or_none(key):
        """Récupère une valeur ou None"""
        return cache.get(key)


class PreCalculatedStats:
    """Statistiques pré-calculées et mises en cache"""
    
    @staticmethod
    def calculate_boutique_stats(user_id=None):
        """Calcule les stats du module Boutique"""
        cache_key = ModuleCache.get_stats_cache_key('boutique')
        stats = cache.get(cache_key)
        
        if stats is None:
            queryset = Product.objects.all()
            if user_id:
                queryset = queryset.filter(shop__owner_id=user_id)
            
            stats = {
                'total_products': queryset.count(),
                'total_revenue': queryset.aggregate(
                    total=Sum('price'))['total'] or 0,
                'average_price': queryset.aggregate(
                    avg=Sum('price') / Count('id'))['avg'] or 0,
                'top_categories': list(
                    queryset.values('category').annotate(
                        count=Count('id')).order_by('-count')[:5]
                ),
                'updated_at': datetime.now().isoformat(),
            }
            
            ModuleCache.set_with_ttl(cache_key, stats, 1800)  # 30 mins
        
        return stats
    
    @staticmethod
    def calculate_microsdicash_stats(user_id=None):
        """Calcule les stats du module MicroSDICash"""
        cache_key = ModuleCache.get_stats_cache_key('microsdicash')
        stats = cache.get(cache_key)
        
        if stats is None:
            queryset = Wallet.objects.all()
            if user_id:
                queryset = queryset.filter(user_id=user_id)
            
            stats = {
                'total_wallets': queryset.count(),
                'total_balance': float(queryset.aggregate(
                    total=Sum('balance'))['total'] or 0),
                'average_balance': float(queryset.aggregate(
                    avg=Sum('balance') / Count('id'))['avg'] or 0),
                'currencies': list(queryset.values('currency').annotate(
                    count=Count('id'), total=Sum('balance'))),
                'updated_at': datetime.now().isoformat(),
            }
            
            ModuleCache.set_with_ttl(cache_key, stats, 300)  # 5 mins
        
        return stats
    
    @staticmethod
    def calculate_all_stats():
        """Pré-calcule toutes les statistiques"""
        all_stats = {}
        for module_name in ModuleConfig.MODULES.keys():
            method_name = f'calculate_{module_name}_stats'
            if hasattr(PreCalculatedStats, method_name):
                all_stats[module_name] = getattr(
                    PreCalculatedStats, method_name)()
        
        return all_stats


class ModuleLoader:
    """Charge les données des modules à la demande"""
    
    @staticmethod
    def load_module(module_name, user, page=1, filters=None):
        """
        Charge un module de manière lazy avec pagination et cache
        
        Args:
            module_name: Nom du module
            user: Utilisateur actuel
            page: Numéro de page
            filters: Filtres additionnels
        
        Returns:
            Dict avec données du module
        """
        
        if module_name not in ModuleConfig.MODULES:
            raise ValueError(f"Module {module_name} non trouvé")
        
        config = ModuleConfig.MODULES[module_name]
        cache_key = ModuleCache.get_cache_key(
            module_name, user.id if user else None, page)
        
        # Vérifier le cache
        cached_data = ModuleCache.get_or_none(cache_key)
        if cached_data:
            cached_data['cached'] = True
            return cached_data
        
        # Charger les données
        if module_name == 'boutique':
            data = ModuleLoader._load_boutique(user, page, filters)
        elif module_name == 'microsdicash':
            data = ModuleLoader._load_microsdicash(user, page, filters)
        elif module_name == 'tikane':
            data = ModuleLoader._load_tikane(user, page, filters)
        elif module_name == 'real_estate':
            data = ModuleLoader._load_real_estate(user, page, filters)
        elif module_name == 'studio_beaute':
            data = ModuleLoader._load_studio_beaute(user, page, filters)
        elif module_name == 'formations':
            data = ModuleLoader._load_formations(user, page, filters)
        elif module_name == 'services_techniciens':
            data = ModuleLoader._load_services_techniciens(user, page, filters)
        else:
            raise ValueError(f"Module {module_name} non implémenté")
        
        # Mettre en cache
        ModuleCache.set_with_ttl(cache_key, data, config['default_cache_ttl'])
        data['cached'] = False
        
        return data
    
    @staticmethod
    def _load_boutique(user, page, filters):
        """Charge les données de la Boutique"""
        queryset = Product.objects.select_related('shop', 'shop__owner')\
            .prefetch_related('images')
        
        if filters and filters.get('search'):
            queryset = queryset.filter(name__icontains=filters['search'])
        
        if filters and filters.get('category'):
            queryset = queryset.filter(category=filters['category'])
        
        paginator = Paginator(queryset, 20)
        page_obj = paginator.get_page(page)
        
        return {
            'module': 'boutique',
            'config': ModuleConfig.MODULES['boutique'],
            'items': [
                {
                    'id': p.id,
                    'name': p.name,
                    'price': float(p.price),
                    'image': str(p.images.first().image.url) if p.images.exists() else None,
                    'shop': p.shop.name,
                    'rating': p.rating if hasattr(p, 'rating') else 0,
                } for p in page_obj
            ],
            'pagination': {
                'current_page': page,
                'total_pages': paginator.num_pages,
                'total_items': paginator.count,
                'has_next': page_obj.has_next(),
                'has_previous': page_obj.has_previous(),
            },
            'stats': PreCalculatedStats.calculate_boutique_stats(),
        }
    
    @staticmethod
    def _load_microsdicash(user, page, filters):
        """Charge les données de MicroSDICash"""
        queryset = Wallet.objects.filter(user=user)
        
        paginator = Paginator(queryset, 50)
        page_obj = paginator.get_page(page)
        
        return {
            'module': 'microsdicash',
            'config': ModuleConfig.MODULES['microsdicash'],
            'items': [
                {
                    'id': w.id,
                    'user': w.user.username,
                    'balance': float(w.balance),
                    'currency': w.currency,
                    'last_transaction': w.last_transaction.isoformat() if w.last_transaction else None,
                } for w in page_obj
            ],
            'pagination': {
                'current_page': page,
                'total_pages': paginator.num_pages,
                'total_items': paginator.count,
                'has_next': page_obj.has_next(),
                'has_previous': page_obj.has_previous(),
            },
            'stats': PreCalculatedStats.calculate_microsdicash_stats(user.id),
        }
    
    @staticmethod
    def _load_tikane(user, page, filters):
        """Charge les données de Ti Kanè Digital"""
        return {
            'module': 'tikane',
            'config': ModuleConfig.MODULES['tikane'],
            'items': [],
            'pagination': {
                'current_page': page,
                'total_pages': 1,
                'total_items': 0,
                'has_next': False,
                'has_previous': False,
            },
            'stats': {},
        }
    
    @staticmethod
    def _load_real_estate(user, page, filters):
        """Charge les données de Maisons à louer"""
        queryset = Property.objects.select_related('owner')\
            .prefetch_related('images')
        
        if filters and filters.get('type'):
            queryset = queryset.filter(property_type=filters['type'])
        
        if filters and filters.get('price_range'):
            min_p, max_p = filters['price_range']
            queryset = queryset.filter(price__range=[min_p, max_p])
        
        paginator = Paginator(queryset, 15)
        page_obj = paginator.get_page(page)
        
        return {
            'module': 'real_estate',
            'config': ModuleConfig.MODULES['real_estate'],
            'items': [
                {
                    'id': p.id,
                    'title': p.title,
                    'price': float(p.price),
                    'location': p.location,
                    'image': str(p.images.first().image.url) if p.images.exists() else None,
                    'bedrooms': p.bedrooms if hasattr(p, 'bedrooms') else None,
                } for p in page_obj
            ],
            'pagination': {
                'current_page': page,
                'total_pages': paginator.num_pages,
                'total_items': paginator.count,
                'has_next': page_obj.has_next(),
                'has_previous': page_obj.has_previous(),
            },
            'stats': {},
        }
    
    @staticmethod
    def _load_studio_beaute(user, page, filters):
        """Charge les données de Studio Beauté"""
        queryset = Product.objects.filter(
            category='beaute').select_related('shop').prefetch_related('images')
        
        paginator = Paginator(queryset, 12)
        page_obj = paginator.get_page(page)
        
        return {
            'module': 'studio_beaute',
            'config': ModuleConfig.MODULES['studio_beaute'],
            'items': [
                {
                    'id': p.id,
                    'name': p.name,
                    'price': float(p.price),
                    'image': str(p.images.first().image.url) if p.images.exists() else None,
                } for p in page_obj
            ],
            'pagination': {
                'current_page': page,
                'total_pages': paginator.num_pages,
                'total_items': paginator.count,
                'has_next': page_obj.has_next(),
                'has_previous': page_obj.has_previous(),
            },
            'stats': {},
        }
    
    @staticmethod
    def _load_formations(user, page, filters):
        """Charge les données de Formations"""
        queryset = Product.objects.filter(
            category='formation').select_related('shop').prefetch_related('images')
        
        paginator = Paginator(queryset, 20)
        page_obj = paginator.get_page(page)
        
        return {
            'module': 'formations',
            'config': ModuleConfig.MODULES['formations'],
            'items': [
                {
                    'id': p.id,
                    'name': p.name,
                    'price': float(p.price),
                    'image': str(p.images.first().image.url) if p.images.exists() else None,
                    'instructor': p.shop.name,
                } for p in page_obj
            ],
            'pagination': {
                'current_page': page,
                'total_pages': paginator.num_pages,
                'total_items': paginator.count,
                'has_next': page_obj.has_next(),
                'has_previous': page_obj.has_previous(),
            },
            'stats': {},
        }
    
    @staticmethod
    def _load_services_techniciens(user, page, filters):
        """Charge les données de Services Techniciens"""
        queryset = Shop.objects.filter(
            category='services_techniques').prefetch_related('products')
        
        paginator = Paginator(queryset, 25)
        page_obj = paginator.get_page(page)
        
        return {
            'module': 'services_techniciens',
            'config': ModuleConfig.MODULES['services_techniciens'],
            'items': [
                {
                    'id': s.id,
                    'name': s.name,
                    'description': s.description,
                    'services_count': s.products.count(),
                } for s in page_obj
            ],
            'pagination': {
                'current_page': page,
                'total_pages': paginator.num_pages,
                'total_items': paginator.count,
                'has_next': page_obj.has_next(),
                'has_previous': page_obj.has_previous(),
            },
            'stats': {},
        }


# API Views pour le lazy loading asynchrone

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_module_list(request):
    """Retourne la liste des modules disponibles"""
    modules = []
    for key, config in ModuleConfig.MODULES.items():
        modules.append({
            'id': key,
            'name': config['name'],
            'description': config['description'],
            'icon': config['icon'],
        })
    
    return Response({
        'modules': modules,
        'total': len(modules),
    })


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def load_module_data(request, module_name):
    """Charge les données d'un module spécifique (lazy loading)"""
    try:
        page = request.GET.get('page', 1)
        filters = {
            'search': request.GET.get('search'),
            'category': request.GET.get('category'),
            'type': request.GET.get('type'),
            'price_range': None,
        }
        
        if request.GET.get('price_min') and request.GET.get('price_max'):
            filters['price_range'] = (
                float(request.GET.get('price_min')),
                float(request.GET.get('price_max')),
            )
        
        # Nettoyer les filtres vides
        filters = {k: v for k, v in filters.items() if v is not None}
        
        data = ModuleLoader.load_module(
            module_name, request.user, page, filters)
        
        return Response(data, status=status.HTTP_200_OK)
    
    except ValueError as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_400_BAD_REQUEST
        )
    except Exception as e:
        return Response(
            {'error': 'Erreur lors du chargement du module'},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def get_module_stats(request, module_name=None):
    """Retourne les statistiques pré-calculées"""
    try:
        if module_name:
            if module_name == 'boutique':
                stats = PreCalculatedStats.calculate_boutique_stats()
            elif module_name == 'microsdicash':
                stats = PreCalculatedStats.calculate_microsdicash_stats(
                    request.user.id)
            else:
                return Response(
                    {'error': 'Module non trouvé'},
                    status=status.HTTP_404_NOT_FOUND
                )
            return Response({'stats': stats}, status=status.HTTP_200_OK)
        else:
            all_stats = PreCalculatedStats.calculate_all_stats()
            return Response(
                {'stats': all_stats}, status=status.HTTP_200_OK)
    
    except Exception as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


@api_view(['POST'])
@permission_classes([IsAuthenticated])
def invalidate_module_cache(request, module_name):
    """Invalide le cache d'un module (admin only)"""
    if not request.user.is_staff:
        return Response(
            {'error': 'Permissions insuffisantes'},
            status=status.HTTP_403_FORBIDDEN
        )
    
    try:
        ModuleCache.invalidate_module(module_name)
        return Response(
            {'message': f'Cache du module {module_name} invalidé'},
            status=status.HTTP_200_OK
        )
    except Exception as e:
        return Response(
            {'error': str(e)},
            status=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
