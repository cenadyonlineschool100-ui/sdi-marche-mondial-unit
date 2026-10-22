"""
API REST pour le système de personnalisation UI Design Système
"""
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db.models import Q
import json
from .models import (
    UIDesignTheme, UserThemePreference, ThemeHistory, 
    AIDesignRecommendation, ThemeCustomColor
)
from .ui_design_engine import (
    ThemeEngine, AIDesigner, ThemePreviewGenerator, 
    AnimationGenerator, ThemeValidator
)

# ============================================================
# 1. THEMES MANAGEMENT
# ============================================================

@login_required
@require_http_methods(["GET"])
def get_all_themes(request):
    """Récupère tous les thèmes disponibles"""
    try:
        themes = UIDesignTheme.objects.filter(is_active=True)
        data = []
        
        for theme in themes:
            data.append({
                'id': theme.id,
                'name': theme.name,
                'slug': theme.slug,
                'description': theme.description,
                'preview_image': theme.preview_image.url if theme.preview_image else None,
                'primary_color': theme.primary_color,
                'secondary_color': theme.secondary_color,
                'accent_color': theme.accent_color,
                'background_color': theme.background_color,
                'is_featured': theme.is_featured,
                'popularity': theme.popularity,
                'style_type': theme.style_type,  # 'arctic_neon', 'cyber_ice', etc.
            })
        
        return JsonResponse({
            'status': 'success',
            'count': len(data),
            'themes': data
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)


@login_required
@require_http_methods(["GET"])
def get_theme_details(request, theme_id):
    """Récupère les détails complets d'un thème"""
    try:
        theme = UIDesignTheme.objects.get(id=theme_id, is_active=True)
        
        colors = ThemeCustomColor.objects.filter(theme=theme)
        colors_data = {
            c.color_key: c.color_value 
            for c in colors
        }
        
        return JsonResponse({
            'status': 'success',
            'theme': {
                'id': theme.id,
                'name': theme.name,
                'description': theme.description,
                'style_type': theme.style_type,
                'primary_color': theme.primary_color,
                'secondary_color': theme.secondary_color,
                'accent_color': theme.accent_color,
                'background_color': theme.background_color,
                'glow_color': theme.glow_color,
                'text_color': theme.text_color,
                'border_color': theme.border_color,
                'shadow_color': theme.shadow_color,
                'glass_opacity': theme.glass_opacity,
                'blur_effect': theme.blur_effect,
                'animation_preset': theme.animation_preset,
                'custom_colors': colors_data,
                'css_variables': theme.css_variables if hasattr(theme, 'css_variables') else {},
            }
        })
    except UIDesignTheme.DoesNotExist:
        return JsonResponse({
            'status': 'error',
            'message': 'Thème non trouvé'
        }, status=404)


@login_required
@require_http_methods(["POST"])
def preview_theme(request, theme_id):
    """Génère une prévisualisation du thème avant application"""
    try:
        theme = UIDesignTheme.objects.get(id=theme_id, is_active=True)
        generator = ThemePreviewGenerator()
        
        preview_data = generator.generate_preview(theme)
        
        return JsonResponse({
            'status': 'success',
            'preview': preview_data,
            'theme_name': theme.name,
            'estimated_time': '0.5s'
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)


@login_required
@require_http_methods(["POST"])
def apply_theme(request, theme_id):
    """Applique un thème au compte utilisateur"""
    try:
        theme = UIDesignTheme.objects.get(id=theme_id, is_active=True)
        user = request.user
        
        # Sauvegarder la préférence précédente dans l'historique
        old_pref = UserThemePreference.objects.filter(user=user, is_current=True).first()
        if old_pref:
            old_pref.is_current = False
            old_pref.save()
            
            history = ThemeHistory.objects.create(
                user=user,
                theme=old_pref.theme,
                action='replaced',
                duration_days=(timezone.now() - old_pref.applied_at).days
            )
        
        # Créer/mettre à jour la préférence courante
        pref, created = UserThemePreference.objects.get_or_create(
            user=user,
            theme=theme,
            defaults={'is_current': True, 'applied_at': timezone.now()}
        )
        
        if not created:
            pref.is_current = True
            pref.applied_at = timezone.now()
            pref.save()
        
        # Incrémenter la popularité du thème
        theme.popularity += 1
        theme.save()
        
        return JsonResponse({
            'status': 'success',
            'message': f'Thème "{theme.name}" appliqué avec succès',
            'theme': {
                'id': theme.id,
                'name': theme.name,
                'primary_color': theme.primary_color,
            }
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)


@login_required
@require_http_methods(["GET"])
def get_current_theme(request):
    """Récupère le thème actuel de l'utilisateur"""
    try:
        pref = UserThemePreference.objects.filter(
            user=request.user, 
            is_current=True
        ).first()
        
        if pref:
            theme = pref.theme
            return JsonResponse({
                'status': 'success',
                'theme': {
                    'id': theme.id,
                    'name': theme.name,
                    'slug': theme.slug,
                    'primary_color': theme.primary_color,
                    'secondary_color': theme.secondary_color,
                    'accent_color': theme.accent_color,
                    'background_color': theme.background_color,
                }
            })
        else:
            return JsonResponse({
                'status': 'success',
                'theme': None,
                'message': 'Aucun thème appliqué, utilisation du thème par défaut'
            })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)


@login_required
@require_http_methods(["POST"])
def restore_previous_theme(request):
    """Restaure le thème précédent"""
    try:
        user = request.user
        
        # Trouver la préférence courante
        current_pref = UserThemePreference.objects.filter(
            user=user, 
            is_current=True
        ).first()
        
        # Trouver la préférence précédente
        previous_pref = UserThemePreference.objects.filter(
            user=user,
            is_current=False
        ).order_by('-applied_at').first()
        
        if previous_pref:
            if current_pref:
                current_pref.is_current = False
                current_pref.save()
            
            previous_pref.is_current = True
            previous_pref.applied_at = timezone.now()
            previous_pref.save()
            
            return JsonResponse({
                'status': 'success',
                'message': f'Thème "{previous_pref.theme.name}" restauré',
                'theme': {'id': previous_pref.theme.id, 'name': previous_pref.theme.name}
            })
        else:
            return JsonResponse({
                'status': 'error',
                'message': 'Aucun thème précédent à restaurer'
            }, status=404)
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)


# ============================================================
# 2. AI DESIGNER
# ============================================================

@login_required
@require_http_methods(["POST"])
def get_ai_recommendations(request):
    """Obtient des recommandations de design de l'IA"""
    try:
        ai_designer = AIDesigner()
        user = request.user
        
        # Analyser le profil utilisateur
        current_pref = UserThemePreference.objects.filter(
            user=user,
            is_current=True
        ).first()
        
        current_theme = current_pref.theme if current_pref else None
        
        # Générer des recommandations
        recommendations = ai_designer.generate_recommendations(
            current_theme=current_theme,
            user_preferences={}
        )
        
        # Sauvegarder les recommandations
        for rec in recommendations:
            AIDesignRecommendation.objects.create(
                user=user,
                theme=rec['theme'] if isinstance(rec['theme'], UIDesignTheme) else None,
                recommendation_type=rec['type'],
                description=rec['description'],
                colors=rec.get('colors', {}),
                animations=rec.get('animations', []),
                confidence_score=rec.get('confidence', 0.8)
            )
        
        return JsonResponse({
            'status': 'success',
            'recommendations': recommendations,
            'count': len(recommendations)
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)


# ============================================================
# 3. CUSTOM COLORS
# ============================================================

@login_required
@require_http_methods(["POST"])
@csrf_exempt
def set_custom_colors(request, theme_id):
    """Permet de personnaliser les couleurs d'un thème"""
    try:
        theme = UIDesignTheme.objects.get(id=theme_id, is_active=True)
        data = json.loads(request.body)
        
        colors_data = data.get('colors', {})
        
        for color_key, color_value in colors_data.items():
            ThemeCustomColor.objects.update_or_create(
                theme=theme,
                color_key=color_key,
                defaults={'color_value': color_value}
            )
        
        # Mettre en cache le thème
        validator = ThemeValidator()
        is_valid = validator.validate_color_harmony(colors_data)
        
        return JsonResponse({
            'status': 'success',
            'message': 'Couleurs personnalisées avec succès',
            'is_valid': is_valid,
            'colors': colors_data
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)


# ============================================================
# 4. THEME HISTORY
# ============================================================

@login_required
@require_http_methods(["GET"])
def get_theme_history(request):
    """Récupère l'historique des thèmes de l'utilisateur"""
    try:
        history = ThemeHistory.objects.filter(user=request.user).order_by('-created_at')[:20]
        
        data = []
        for h in history:
            data.append({
                'id': h.id,
                'theme_name': h.theme.name,
                'theme_id': h.theme.id,
                'action': h.action,
                'duration_days': h.duration_days,
                'created_at': h.created_at.isoformat(),
            })
        
        return JsonResponse({
            'status': 'success',
            'history': data,
            'count': len(data)
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)


# ============================================================
# 5. THEME FAVORITES
# ============================================================

@login_required
@require_http_methods(["POST"])
def toggle_theme_favorite(request, theme_id):
    """Marque/démarque un thème comme favori"""
    try:
        theme = UIDesignTheme.objects.get(id=theme_id, is_active=True)
        pref, created = UserThemePreference.objects.get_or_create(
            user=request.user,
            theme=theme,
            defaults={'is_favorite': True}
        )
        
        if not created:
            pref.is_favorite = not pref.is_favorite
            pref.save()
        
        return JsonResponse({
            'status': 'success',
            'message': f'Favori {"ajouté" if pref.is_favorite else "supprimé"}',
            'is_favorite': pref.is_favorite
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)


@login_required
@require_http_methods(["GET"])
def get_favorite_themes(request):
    """Récupère les thèmes favoris de l'utilisateur"""
    try:
        favorites = UserThemePreference.objects.filter(
            user=request.user,
            is_favorite=True
        ).select_related('theme')
        
        data = []
        for pref in favorites:
            theme = pref.theme
            data.append({
                'id': theme.id,
                'name': theme.name,
                'primary_color': theme.primary_color,
                'preview_image': theme.preview_image.url if theme.preview_image else None,
            })
        
        return JsonResponse({
            'status': 'success',
            'favorites': data,
            'count': len(data)
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)


# ============================================================
# 6. DASHBOARD STATISTICS
# ============================================================

@login_required
@require_http_methods(["GET"])
def get_design_dashboard_stats(request):
    """Récupère les statistiques du dashboard de design"""
    try:
        user = request.user
        
        # Thèmes visités
        visited_count = UserThemePreference.objects.filter(user=user).count()
        
        # Thème actuel
        current_pref = UserThemePreference.objects.filter(
            user=user,
            is_current=True
        ).first()
        
        # Historique
        history_count = ThemeHistory.objects.filter(user=user).count()
        
        # Favorites
        favorites_count = UserThemePreference.objects.filter(
            user=user,
            is_favorite=True
        ).count()
        
        # Recommendations non lues
        recommendations = AIDesignRecommendation.objects.filter(
            user=user,
            is_viewed=False
        ).count()
        
        return JsonResponse({
            'status': 'success',
            'stats': {
                'current_theme': current_pref.theme.name if current_pref else 'Défaut',
                'themes_visited': visited_count,
                'theme_changes': history_count,
                'favorites': favorites_count,
                'new_recommendations': recommendations,
                'ai_aesthetic_score': 0,  # À calculer
            }
        })
    except Exception as e:
        return JsonResponse({
            'status': 'error',
            'message': str(e)
        }, status=500)
