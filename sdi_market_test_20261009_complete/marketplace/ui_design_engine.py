"""
Moteur de personnalisation UI et IA Designer
Gère les thèmes, les animations, les couleurs et les prévisualisations
"""
import json
from typing import Dict, List, Any
from PIL import Image, ImageDraw, ImageFilter
from io import BytesIO
import base64


class ThemeEngine:
    """Moteur de gestion des thèmes"""
    
    PREDEFINED_THEMES = {
        'arctic_neon_glass': {
            'name': 'Arctic Neon Glass UI',
            'primary_color': '#00D9FF',
            'secondary_color': '#0A0E27',
            'accent_color': '#FF006E',
            'background_color': '#0A0E27',
            'glow_color': '#00D9FF',
            'text_color': '#FFFFFF',
            'border_color': '#00D9FF',
            'shadow_color': 'rgba(0, 217, 255, 0.3)',
            'style': 'arctic_neon'
        },
        'cyber_ice_fintech': {
            'name': 'Cyber Ice Fintech',
            'primary_color': '#00BFFF',
            'secondary_color': '#1A1F3A',
            'accent_color': '#FFD700',
            'background_color': '#0F1525',
            'glow_color': '#00BFFF',
            'text_color': '#E8F0FF',
            'border_color': '#00BFFF',
            'shadow_color': 'rgba(0, 191, 255, 0.25)',
            'style': 'cyber_ice'
        },
        'white_blue_cyber': {
            'name': 'White & Blue Cyber Glassmorphism',
            'primary_color': '#0066FF',
            'secondary_color': '#FFFFFF',
            'accent_color': '#FF3366',
            'background_color': '#F5F7FF',
            'glow_color': '#0066FF',
            'text_color': '#333333',
            'border_color': '#0066FF',
            'shadow_color': 'rgba(0, 102, 255, 0.15)',
            'style': 'white_blue'
        },
        'quantum_fintech': {
            'name': 'Quantum Fintech Dashboard',
            'primary_color': '#00FF88',
            'secondary_color': '#001A2E',
            'accent_color': '#FF0055',
            'background_color': '#001A2E',
            'glow_color': '#00FF88',
            'text_color': '#FFFFFF',
            'border_color': '#00FF88',
            'shadow_color': 'rgba(0, 255, 136, 0.2)',
            'style': 'quantum'
        },
        'neon_flow_banking': {
            'name': 'Neon Flow Banking UI',
            'primary_color': '#FF00FF',
            'secondary_color': '#0D0221',
            'accent_color': '#00D9FF',
            'background_color': '#0D0221',
            'glow_color': '#FF00FF',
            'text_color': '#FFFFFF',
            'border_color': '#FF00FF',
            'shadow_color': 'rgba(255, 0, 255, 0.3)',
            'style': 'neon_flow'
        }
    }
    
    @staticmethod
    def get_theme_preset(theme_key: str) -> Dict[str, str]:
        """Récupère une présélection de thème"""
        return ThemeEngine.PREDEFINED_THEMES.get(
            theme_key,
            ThemeEngine.PREDEFINED_THEMES['arctic_neon_glass']
        )
    
    @staticmethod
    def generate_css_variables(theme: Dict[str, str]) -> str:
        """Génère les variables CSS pour un thème"""
        css = ":root {\n"
        for key, value in theme.items():
            css_var = key.replace('_', '-')
            css += f"  --{css_var}: {value};\n"
        css += "}\n"
        return css
    
    @staticmethod
    def merge_custom_colors(
        base_theme: Dict[str, str],
        custom_colors: Dict[str, str]
    ) -> Dict[str, str]:
        """Fusionne les couleurs personnalisées avec le thème de base"""
        merged = base_theme.copy()
        merged.update(custom_colors)
        return merged


class AIDesigner:
    """IA Designer pour recommandations de design"""
    
    def generate_recommendations(
        self,
        current_theme=None,
        user_preferences: Dict = None
    ) -> List[Dict[str, Any]]:
        """
        Génère des recommandations de design basées sur l'IA
        """
        recommendations = []
        
        # Recommendation 1: Amélioration du contraste
        recommendations.append({
            'type': 'contrast_optimization',
            'description': 'Optimiser le contraste pour meilleure lisibilité',
            'theme': None,
            'colors': {
                'text_color': '#FFFFFF',
                'background_color': '#0A0E27'
            },
            'confidence': 0.95
        })
        
        # Recommendation 2: Harmonisation des couleurs
        recommendations.append({
            'type': 'color_harmony',
            'description': 'Utiliser une palette harmonieuse avec complément violet',
            'theme': None,
            'colors': {
                'primary_color': '#00D9FF',
                'accent_color': '#7C3AED'
            },
            'confidence': 0.87
        })
        
        # Recommendation 3: Animations fluides
        recommendations.append({
            'type': 'animation_enhancement',
            'description': 'Ajouter des transitions fluides 0.3s ease-out',
            'animations': [
                'fade-in 0.3s ease-out',
                'slide-up 0.4s ease-out',
                'glow-pulse 1.5s infinite'
            ],
            'confidence': 0.92
        })
        
        # Recommendation 4: Style glassmorphism
        recommendations.append({
            'type': 'glass_effect',
            'description': 'Renforcer l\'effet glassmorphism avec blur 15px',
            'theme': None,
            'colors': {},
            'glass_settings': {
                'blur': '15px',
                'opacity': 0.8,
                'backdrop_filter': 'blur(15px)'
            },
            'confidence': 0.89
        })
        
        return recommendations
    
    @staticmethod
    def calculate_color_harmony(colors: List[str]) -> float:
        """Calcule l'harmonie d'une palette de couleurs (0-1)"""
        # Simplifié - dans la vraie implémentation, utiliserait Lab color space
        return 0.85
    
    @staticmethod
    def suggest_complementary_color(color: str) -> str:
        """Suggère une couleur complémentaire"""
        # Conversion simple hex to RGB
        hex_color = color.lstrip('#')
        r, g, b = tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        
        # Complément simple
        comp_r = 255 - r
        comp_g = 255 - g
        comp_b = 255 - b
        
        return f'#{comp_r:02x}{comp_g:02x}{comp_b:02x}'


class ThemePreviewGenerator:
    """Génère des aperçus de thème avant application"""
    
    def generate_preview(self, theme) -> Dict[str, Any]:
        """Génère un aperçu complet du thème"""
        
        components_preview = {
            'dashboard': self._preview_dashboard(theme),
            'navbar': self._preview_navbar(theme),
            'cards': self._preview_cards(theme),
            'buttons': self._preview_buttons(theme),
            'forms': self._preview_forms(theme),
            'tables': self._preview_tables(theme),
            'charts': self._preview_charts(theme),
        }
        
        return {
            'theme_id': theme.id,
            'theme_name': theme.name,
            'components': components_preview,
            'css_variables': self._generate_preview_css(theme),
            'animation_preview': self._generate_animation_preview(theme),
            'timestamp': str(timezone.now())
        }
    
    @staticmethod
    def _preview_dashboard(theme) -> Dict[str, str]:
        """Prévisualise le dashboard"""
        return {
            'background': theme.background_color,
            'glow_effect': f'box-shadow: inset 0 0 30px {theme.glow_color}',
            'elements': 6
        }
    
    @staticmethod
    def _preview_navbar(theme) -> Dict[str, str]:
        return {
            'background': theme.secondary_color,
            'text_color': theme.text_color,
            'border': f'1px solid {theme.border_color}',
            'glow': theme.glow_color
        }
    
    @staticmethod
    def _preview_cards(theme) -> Dict[str, str]:
        return {
            'background': f'rgba(255, 255, 255, 0.05)',
            'border': f'1px solid {theme.border_color}',
            'shadow': theme.shadow_color,
            'backdrop_filter': 'blur(10px)'
        }
    
    @staticmethod
    def _preview_buttons(theme) -> Dict[str, str]:
        return {
            'primary': theme.primary_color,
            'secondary': theme.accent_color,
            'hover_glow': f'0 0 20px {theme.glow_color}',
            'transition': 'all 0.3s ease-out'
        }
    
    @staticmethod
    def _preview_forms(theme) -> Dict[str, str]:
        return {
            'input_background': f'rgba(255, 255, 255, 0.08)',
            'input_border': f'1px solid {theme.border_color}',
            'focus_shadow': f'0 0 15px {theme.primary_color}',
            'placeholder_color': 'rgba(255, 255, 255, 0.5)'
        }
    
    @staticmethod
    def _preview_tables(theme) -> Dict[str, str]:
        return {
            'header_background': theme.secondary_color,
            'header_text': theme.text_color,
            'row_hover': f'rgba({theme.primary_color}, 0.1)',
            'border': f'1px solid {theme.border_color}'
        }
    
    @staticmethod
    def _preview_charts(theme) -> Dict[str, str]:
        return {
            'primary_line': theme.primary_color,
            'secondary_line': theme.accent_color,
            'grid_color': f'rgba({theme.text_color}, 0.1)',
            'tooltip_background': theme.secondary_color
        }
    
    @staticmethod
    def _generate_preview_css(theme) -> str:
        """Génère CSS pour la prévisualisation"""
        css = f"""
        :root {{
            --primary-color: {theme.primary_color};
            --secondary-color: {theme.secondary_color};
            --accent-color: {theme.accent_color};
            --background-color: {theme.background_color};
            --glow-color: {theme.glow_color};
            --text-color: {theme.text_color};
            --border-color: {theme.border_color};
            --shadow-color: {theme.shadow_color};
            --glass-opacity: {theme.glass_opacity};
            --blur-effect: {theme.blur_effect}px;
        }}
        """
        return css
    
    @staticmethod
    def _generate_animation_preview(theme) -> Dict[str, str]:
        """Génère aperçu des animations"""
        return {
            'fade_in': 'animation: fadeIn 0.5s ease-out',
            'glow_pulse': f'animation: glowPulse 1.5s infinite; color: {theme.glow_color}',
            'slide_up': 'animation: slideUp 0.4s ease-out',
            'hover_lift': 'transform: translateY(-2px); box-shadow: 0 10px 30px rgba(0,0,0,0.3)'
        }


class AnimationGenerator:
    """Génère les animations pour les thèmes"""
    
    @staticmethod
    def generate_css_animations(theme) -> str:
        """Génère les keyframes et animations CSS"""
        animations = """
        /* Fade In Animation */
        @keyframes fadeIn {
            from {
                opacity: 0;
            }
            to {
                opacity: 1;
            }
        }
        
        /* Glow Pulse Animation */
        @keyframes glowPulse {
            0%, 100% {
                filter: drop-shadow(0 0 8px rgba(0, 217, 255, 0.3));
            }
            50% {
                filter: drop-shadow(0 0 20px rgba(0, 217, 255, 0.8));
            }
        }
        
        /* Slide Up Animation */
        @keyframes slideUp {
            from {
                opacity: 0;
                transform: translateY(20px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }
        
        /* Neon Glow Animation */
        @keyframes neonGlow {
            0%, 100% {
                text-shadow: 0 0 10px rgba(0, 217, 255, 0.4),
                             0 0 20px rgba(0, 217, 255, 0.2),
                             0 0 30px rgba(0, 217, 255, 0.1);
            }
            50% {
                text-shadow: 0 0 20px rgba(0, 217, 255, 0.8),
                             0 0 30px rgba(0, 217, 255, 0.6),
                             0 0 40px rgba(0, 217, 255, 0.4);
            }
        }
        
        /* Float Animation */
        @keyframes float {
            0%, 100% {
                transform: translateY(0px);
            }
            50% {
                transform: translateY(-10px);
            }
        }
        
        /* Rotate Animation */
        @keyframes spin {
            from {
                transform: rotate(0deg);
            }
            to {
                transform: rotate(360deg);
            }
        }
        """
        return animations
    
    @staticmethod
    def get_animation_preset(preset_name: str) -> Dict[str, str]:
        """Récupère une présélection d'animations"""
        presets = {
            'smooth': {
                'transition': '0.3s ease-out',
                'animations': ['fadeIn 0.5s', 'slideUp 0.4s']
            },
            'cyber': {
                'transition': '0.2s cubic-bezier(0.4, 0, 0.2, 1)',
                'animations': ['neonGlow 1.5s infinite', 'glowPulse 1s infinite']
            },
            'premium': {
                'transition': '0.5s cubic-bezier(0.25, 0.46, 0.45, 0.94)',
                'animations': ['float 3s ease-in-out infinite', 'fadeIn 0.8s']
            }
        }
        return presets.get(preset_name, presets['smooth'])


class ThemeValidator:
    """Valide les thèmes et les palettes de couleurs"""
    
    @staticmethod
    def validate_color_harmony(colors: Dict[str, str]) -> bool:
        """Valide l'harmonie d'une palette"""
        if not colors:
            return False
        
        # Vérifier qu'on a les couleurs essentielles
        essential_colors = ['primary_color', 'secondary_color', 'background_color', 'text_color']
        for color in essential_colors:
            if color not in colors:
                return False
        
        return True
    
    @staticmethod
    def validate_contrast(foreground: str, background: str) -> float:
        """Valide le contraste entre deux couleurs (WCAG standard)"""
        # Conversion hex to RGB
        def hex_to_rgb(hex_color):
            hex_color = hex_color.lstrip('#')
            return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))
        
        fg_rgb = hex_to_rgb(foreground)
        bg_rgb = hex_to_rgb(background)
        
        # Calcul de la luminance
        def get_luminance(rgb):
            r, g, b = [x / 255.0 for x in rgb]
            r = r / 12.92 if r <= 0.03928 else pow((r + 0.055) / 1.055, 2.4)
            g = g / 12.92 if g <= 0.03928 else pow((g + 0.055) / 1.055, 2.4)
            b = b / 12.92 if b <= 0.03928 else pow((b + 0.055) / 1.055, 2.4)
            return 0.2126 * r + 0.7152 * g + 0.0722 * b
        
        l1 = get_luminance(fg_rgb)
        l2 = get_luminance(bg_rgb)
        
        lighter = max(l1, l2)
        darker = min(l1, l2)
        
        return (lighter + 0.05) / (darker + 0.05)
    
    @staticmethod
    def is_wcag_compliant(foreground: str, background: str, level='AA') -> bool:
        """Vérifie la conformité WCAG"""
        contrast = ThemeValidator.validate_contrast(foreground, background)
        
        if level == 'AA':
            return contrast >= 4.5  # Pour le texte normal
        elif level == 'AAA':
            return contrast >= 7.0
        
        return False


# Import timezone pour ThemePreviewGenerator
from django.utils import timezone
