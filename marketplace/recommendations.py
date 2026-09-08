"""
Service de recommandations IA basé sur:
- Similarité de produits (TF-IDF + cosine similarity)
- Historique d'achat utilisateur
- Filtrage collaboratif simplifié
"""

import warnings
from decimal import Decimal

from .models import Product, Order, OrderItem

# Importation lazy des dépendances ML
_sklearn_available = False
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    from sklearn.preprocessing import StandardScaler
    import numpy as np
    _sklearn_available = True
except ImportError:
    warnings.warn(
        "Scikit-learn n'est pas installée. Le système de recommandations IA sera désactivé. "
        "Installez les dépendances avec: pip install -r requirements.txt",
        RuntimeWarning
    )
    np = None
    TfidfVectorizer = None
    cosine_similarity = None


class RecommendationEngine:
    """Moteur de recommandations IA"""
    
    def __init__(self):
        self.products = list(Product.objects.filter(quantity__gt=0).select_related('shop'))
        self.tfidf_vectorizer = None
        
        if _sklearn_available and TfidfVectorizer:
            self.tfidf_vectorizer = TfidfVectorizer(
                lowercase=True,
                stop_words=None,
                max_features=100,
                ngram_range=(1, 2)
            )
    
    def get_similar_products(self, product_id, limit=5):
        """
        Retourne des produits similaires basés sur:
        - Similarité lexicale du nom/descriptions
        - Prix proche
        - Même vendeur ou catégorie
        """
        if not _sklearn_available:
            # Fallback: similarité basique par prix
            return self._get_similar_by_price(product_id, limit)
        
        try:
            product = Product.objects.get(id=product_id)
        except Product.DoesNotExist:
            return []
        
        if not self.products or not self.tfidf_vectorizer:
            return []
        
        # Créer les features textuelles pour tous les produits
        product_texts = [p.name.lower() for p in self.products]
        
        try:
            tfidf_matrix = self.tfidf_vectorizer.fit_transform(product_texts)
            
            # Trouver l'index du produit actuel
            current_idx = next(
                (i for i, p in enumerate(self.products) if p.id == product_id),
                None
            )
            
            if current_idx is None:
                return []
            
            # Calculer la similarité textuelle
            similarities = cosine_similarity(
                tfidf_matrix[current_idx],
                tfidf_matrix
            )[0]
            
            # Créer un score combiné avec le prix
            scores = []
            current_price = float(product.price_ht)
            
            for idx, product_id_iter in enumerate([p.id for p in self.products]):
                if idx == current_idx:
                    continue
                
                sim_score = similarities[idx]
                
                # Pénalité pour les prix très différents (±50%)
                if idx < len(self.products):
                    other_price = float(self.products[idx].price_ht)
                    price_diff = abs(current_price - other_price) / max(current_price, other_price)
                    price_penalty = np.exp(-price_diff)
                    sim_score = sim_score * 0.7 + price_penalty * 0.3
                
                scores.append({
                    'product': self.products[idx],
                    'score': float(sim_score)
                })
            
            # Trier par score et retourner les top N
            scores.sort(key=lambda x: x['score'], reverse=True)
            return [item['product'] for item in scores[:limit]]
        
        except Exception as e:
            print(f"Erreur dans get_similar_products: {e}")
            return self._get_similar_by_price(product_id, limit)
    
    def _get_similar_by_price(self, product_id, limit=5):
        """Fallback simple: produits avec prix similaire"""
        try:
            product = Product.objects.get(id=product_id)
            similar = Product.objects.filter(
                quantity__gt=0,
                price_ht__gte=product.price_ht * Decimal('0.7'),
                price_ht__lte=product.price_ht * Decimal('1.3')
            ).exclude(id=product_id)[:limit]
            return list(similar)
        except:
            return []
    
    def get_personalized_recommendations(self, user, limit=5):
        """
        Retourne des recommandations personnalisées basées sur:
        - Historique d'achat de l'utilisateur
        - Produits similaires à ceux achetés
        - Tendances populaires
        """
        if not self.products:
            return []
        
        # 1. Récupérer l'historique d'achat
        user_purchases = OrderItem.objects.filter(
            order__buyer=user
        ).select_related('product').values_list('product_id', flat=True)
        
        if not user_purchases:
            # Pas d'historique: retourner les produits les plus vendus
            return self._get_trending_products(limit)
        
        # 2. Pour chaque achat, trouver des produits similaires
        similar_products_map = {}
        for product_id in user_purchases:
            similar = self.get_similar_products(product_id, limit=3)
            for prod in similar:
                if prod.id not in user_purchases and prod.id not in similar_products_map:
                    similar_products_map[prod.id] = {
                        'product': prod,
                        'score': 0
                    }
                    similar_products_map[prod.id]['score'] += 1
        
        # 3. Trier par score de recommandation
        recommendations = sorted(
            similar_products_map.values(),
            key=lambda x: x['score'],
            reverse=True
        )
        
        return [item['product'] for item in recommendations[:limit]]
    
    def _get_trending_products(self, limit=5):
        """Retourne les produits les plus vendus (tendances)"""
        from django.db.models import Count
        
        trending = OrderItem.objects.values('product_id').annotate(
            count=Count('id')
        ).order_by('-count')[:limit]
        
        trending_ids = [item['product_id'] for item in trending]
        return Product.objects.filter(id__in=trending_ids, quantity__gt=0)
    
    def get_recommendations_for_bundle(self, product_ids, limit=5):
        """
        Retourne des produits qui iraient bien ensemble (bundle/combo)
        Utile pour les promotions cross-sell
        """
        if not product_ids:
            return []
        
        all_similar = set()
        for pid in product_ids:
            similar = self.get_similar_products(pid, limit=3)
            all_similar.update([p.id for p in similar])
        
        # Exclure les produits du bundle
        all_similar = all_similar - set(product_ids)
        
        if not all_similar:
            return []
        
        return Product.objects.filter(id__in=all_similar, quantity__gt=0)[:limit]


# Instance globale du moteur
_recommendation_engine = None


def get_recommendation_engine():
    """Retourne l'instance du moteur de recommandations"""
    global _recommendation_engine
    if _recommendation_engine is None:
        _recommendation_engine = RecommendationEngine()
    return _recommendation_engine


def refresh_recommendation_engine():
    """Rafraîchit le moteur (à appeler après chaque nouveau produit)"""
    global _recommendation_engine
    _recommendation_engine = RecommendationEngine()


# Fonctions utilitaires
def get_similar_products(product_id, limit=5):
    """Wrapper pour obtenir des produits similaires"""
    engine = get_recommendation_engine()
    return engine.get_similar_products(product_id, limit)


def get_personalized_recommendations(user, limit=5):
    """Wrapper pour obtenir des recommandations personnalisées"""
    if not user.is_authenticated:
        engine = get_recommendation_engine()
        return engine._get_trending_products(limit)
    
    engine = get_recommendation_engine()
    return engine.get_personalized_recommendations(user, limit)


def get_trending_products(limit=5):
    """Wrapper pour obtenir les produits tendances"""
    engine = get_recommendation_engine()
    return engine._get_trending_products(limit)
