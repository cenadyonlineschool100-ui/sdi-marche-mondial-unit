from decimal import Decimal
from io import BytesIO
import os
import re
from PIL import Image

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile, SimpleUploadedFile
from .models import BeautyAppointment, BeautyStudioRequest, BeautyStudioService, Product, ProductReview, SystemSettings, ProductImage, ChatMessage, PrivateMessage, Profile, Order, AdminAnnouncement, TiKaneAccessRequest, TiKanePlan, TechnicianProfile, SiteBanner, SiteBannerImage, Shop, PriorityGroup

User = get_user_model()


def normalize_phone_number(value):
    """Normalize phone numbers to a consistent international format."""
    if value is None:
        return ''

    digits = re.sub(r'\D', '', str(value).strip())
    if not digits:
        return ''

    if digits.startswith('509'):
        return '+' + digits
    if digits.startswith('0') and len(digits) == 9:
        return '+509' + digits[1:]
    if digits.startswith('9') and len(digits) in (8, 9):
        return '+509' + digits
    if len(digits) == 8:
        return '+509' + digits
    return '+' + digits if digits.isdigit() else ''


class MultipleFileInput(forms.ClearableFileInput):
    """Widget personnalisé pour les uploads multiples"""
    allow_multiple_selected = True
    
    def render(self, name, value, attrs=None, renderer=None):
        attrs = attrs or {}
        attrs['multiple'] = 'multiple'
        if 'class' not in attrs:
            attrs['class'] = 'form-control'
        if 'accept' not in attrs:
            attrs['accept'] = 'image/*'
        attrs['style'] = 'padding: 10px; border: 2px solid #d9d9e3; border-radius: 12px; cursor: pointer;'
        return super().render(name, value, attrs, renderer)
    
    def value_from_datadict(self, data, files, name):
        """Retourne une liste de fichiers au lieu d'un seul"""
        if hasattr(files, 'getlist'):
            return files.getlist(name)
        return files.get(name)

class ShopCoverPhotoForm(forms.Form):
    images = forms.FileField(
        widget=MultipleFileInput(),
        required=False,
        label='Photos de couverture',
        help_text='Téléversez plusieurs images pour la couverture du studio.',
        error_messages={
            'invalid_image': 'Téléversez des fichiers image valides (JPG, PNG, GIF, WebP).',
        }
    )
    
    def clean_images(self):
        files = self.files.getlist('images') if self.files else []
        if not files:
            return files
        
        MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
        for file in files:
            if file.size > MAX_FILE_SIZE:
                raise forms.ValidationError(f'Le fichier {file.name} dépasse la limite de 5 MB.')
            if not file.content_type.startswith('image/'):
                raise forms.ValidationError(f'{file.name} n\'est pas un fichier image valide.')
        
        return files


TECHNICIAN_SERVICE_CHOICES = [
    ('Réseaux informatiques', 'Réseaux informatiques'),
    ('Installation de caméras', 'Installation de caméras'),
    ('Électricité', 'Électricité'),
    ('Informatique', 'Informatique'),
    ('Développement web', 'Développement web'),
    ('Climatisation', 'Climatisation'),
    ('Maintenance technique', 'Maintenance technique'),
    ('Autres services', 'Autres services'),
]


class TechnicianProfileForm(forms.ModelForm):
    services = forms.MultipleChoiceField(
        choices=TECHNICIAN_SERVICE_CHOICES,
        widget=forms.CheckboxSelectMultiple(attrs={'class': 'form-check-input'}),
        required=False,
        label='Services proposés',
        help_text='Sélectionnez les services que vous proposez.'
    )

    class Meta:
        model = TechnicianProfile
        fields = [
            'company_name', 'contact_name', 'phone', 'email', 'city_region', 'address', 'description',
            'services', 'references', 'website', 'whatsapp', 'facebook', 'logo',
            'photo_1', 'photo_1_desc', 'photo_2', 'photo_2_desc', 'photo_3', 'photo_3_desc',
            'photo_4', 'photo_4_desc', 'photo_5', 'photo_5_desc'
        ]
        widgets = {
            'company_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nom de l\'entreprise'}),
            'contact_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nom du responsable'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Téléphone'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Adresse e-mail'}),
            'city_region': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ville / Région'}),
            'address': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Adresse (optionnelle)'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 4, 'placeholder': 'Décrivez vos compétences, votre expérience et vos services...'}),
            'references': forms.Textarea(attrs={'class': 'form-control', 'rows': 3, 'placeholder': 'Référence 1\nRéférence 2\nRéférence 3'}),
            'website': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'Site web (optionnel)'}),
            'whatsapp': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'WhatsApp'}),
            'facebook': forms.URLInput(attrs={'class': 'form-control', 'placeholder': 'Facebook (optionnel)'}),
            'logo': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'photo_1': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'photo_1_desc': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Description photo 1'}),
            'photo_2': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'photo_2_desc': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Description photo 2'}),
            'photo_3': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'photo_3_desc': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Description photo 3'}),
            'photo_4': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'photo_4_desc': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Description photo 4'}),
            'photo_5': forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'photo_5_desc': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Description photo 5'}),
        }
        labels = {
            'company_name': 'Nom de l\'entreprise',
            'contact_name': 'Nom du responsable',
            'phone': 'Téléphone',
            'email': 'E-mail',
            'city_region': 'Ville / Région',
            'address': 'Adresse',
            'description': 'Description de votre activité',
            'references': 'Références professionnelles',
            'website': 'Site web',
            'whatsapp': 'WhatsApp',
            'facebook': 'Facebook',
            'logo': 'Logo ou photo de l\'entreprise',
            'photo_1': 'Photo 1',
            'photo_2': 'Photo 2',
            'photo_3': 'Photo 3',
            'photo_4': 'Photo 4',
            'photo_5': 'Photo 5',
        }

    def clean_services(self):
        services = self.cleaned_data.get('services', [])
        return ', '.join(services)

    def save(self, commit=True):
        instance = super().save(commit=False)
        if commit:
            instance.save()
            self.save_m2m()
        return instance

class SignUpForm(UserCreationForm):
    first_name = forms.CharField(max_length=30, required=True, widget=forms.TextInput(attrs={'placeholder': 'Prénom'}))
    last_name = forms.CharField(max_length=30, required=True, widget=forms.TextInput(attrs={'placeholder': 'Nom'}))
    email = forms.EmailField(max_length=254, required=True, widget=forms.EmailInput(attrs={'placeholder': 'Email'}))
    address = forms.CharField(max_length=255, required=True, widget=forms.TextInput(attrs={'placeholder': 'Adresse complète'}))
    phone = forms.CharField(max_length=20, required=True, widget=forms.TextInput(attrs={'placeholder': 'Numéro de téléphone'}))
    photo = forms.ImageField(required=False, widget=forms.FileInput(attrs={'accept': 'image/*'}))
    identity_document = forms.ImageField(
        required=False,
        widget=forms.FileInput(attrs={'accept': 'image/*'}),
        help_text='Photo de passeport, carte d\'identité ou carte SDI'
    )
    receipt_proof = forms.ImageField(
        required=False,
        widget=forms.FileInput(attrs={'accept': 'image/*'}),
        help_text='Reçu SDI MicroSDICash (au moins une des deux pièces justificatives est requise)'
    )

    class Meta:
        model = User
        fields = ('username', 'first_name', 'last_name', 'email', 'password1', 'password2', 'address', 'phone', 'photo', 'identity_document', 'receipt_proof')

    def clean(self):
        cleaned = super().clean()
        email = cleaned.get('email')
        phone = cleaned.get('phone')

        # Exiger une adresse Gmail
        if email and not email.lower().endswith('@gmail.com'):
            raise ValidationError('Veuillez utiliser une adresse Gmail (ex: utilisateur@gmail.com).')

        # Empêcher l'inscription si même combinaison email + téléphone existe
        if email and phone:
            User = get_user_model()
            normalized_phone = normalize_phone_number(phone)
            if User.objects.filter(email__iexact=email, profile__phone=normalized_phone).exists():
                raise ValidationError('Un compte existe déjà avec cette adresse Gmail et ce numéro de téléphone.')

        identity_document = cleaned.get('identity_document')
        receipt_proof = cleaned.get('receipt_proof')
        if not identity_document and not receipt_proof:
            raise ValidationError('Veuillez télécharger une pièce d\'identité ou un reçu SDI MicroSDICash.')

        return cleaned

class SiteBannerForm(forms.ModelForm):
    class Meta:
        model = SiteBanner
        fields = [
            'product', 'title', 'subtitle', 'button_text', 'image',
            'is_active', 'display_order', 'start_date', 'end_date', 'display_mode', 'autoplay_seconds', 'autoplay_enabled', 'scope', 'shops', 'access_mode', 'access_price'
        ]
        widgets = {
            'product': forms.Select(attrs={'class': 'form-control'}),
            'title': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Offre du moment'}),
            'subtitle': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Sous-titre'}),
            'button_text': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Voir le produit'}),
            'image': forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'display_order': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
            'start_date': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'end_date': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'display_mode': forms.Select(attrs={'class': 'form-control'}),
            'autoplay_seconds': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'max': '300'}),
            'autoplay_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'scope': forms.Select(attrs={'class': 'form-control'}),
            'shops': forms.SelectMultiple(attrs={'class': 'form-control'}),
            'access_mode': forms.Select(attrs={'class': 'form-control'}),
            'access_price': forms.NumberInput(attrs={'class': 'form-control', 'min': '0', 'step': '0.01'}),
        }
        labels = {
            'product': 'Produit réel',
            'title': 'Titre',
            'subtitle': 'Sous-titre',
            'button_text': 'Texte du bouton',
            'image': 'Image de bannière',
            'is_active': 'Activer la bannière',
            'display_order': 'Ordre d’affichage',
            'start_date': 'Date de début',
            'end_date': 'Date de fin',
            'display_mode': 'Mode d’affichage',
            'autoplay_seconds': 'Autoplay en secondes (0 = désactivé)',
            'autoplay_enabled': 'Défilement automatique actif',
            'scope': 'Portée de la bannière',
            'shops': 'Boutiques autorisées',
            'access_mode': 'Mode d’accès à la bannière',
            'access_price': 'Prix MicroCash (USD)',
        }

    def __init__(self, *args, **kwargs):
        is_principal = kwargs.pop('is_principal', False)
        super().__init__(*args, **kwargs)
        if not is_principal:
            self.fields.pop('access_mode', None)
            self.fields.pop('access_price', None)
        self.fields['product'].queryset = Product.objects.order_by('name')
        self.fields['shops'].queryset = Shop.objects.order_by('name')

    def clean_image(self):
        image = self.cleaned_data.get('image')
        if not image or not isinstance(image, UploadedFile):
            return image
        try:
            with Image.open(image) as source:
                optimized = source.convert('RGB')
                optimized.thumbnail((1600, 800), Image.Resampling.LANCZOS)
                output = BytesIO()
                optimized.save(output, format='WEBP', quality=84, method=6)
            output.seek(0)
            image = SimpleUploadedFile(
                f'{os.path.splitext(image.name)[0]}.webp',
                output.getvalue(),
                content_type='image/webp',
            )
        except (OSError, ValueError):
            raise ValidationError('Téléversez une image valide.')
        return image


class SiteBannerImageForm(forms.ModelForm):
    class Meta:
        model = SiteBannerImage
        fields = ['image', 'display_order']
        widgets = {
            'image': forms.ClearableFileInput(attrs={'class': 'form-control', 'accept': 'image/*'}),
            'display_order': forms.NumberInput(attrs={'class': 'form-control', 'min': '0'}),
        }


class ProductForm(forms.ModelForm):
    images = forms.FileField(
        widget=MultipleFileInput(),
        required=False,
        help_text='Sélectionnez une ou plusieurs images (max 5MB chacune)'
    )

    # Champ pour l'image personnalisée (upload manuel)
    custom_image = forms.ImageField(
        required=False,
        widget=forms.FileInput(attrs={
            'accept': 'image/*',
            'class': 'form-control',
            'id': 'id_custom_image'
        }),
        help_text='Remplace l\'image auto-générée par votre propre image'
    )
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and getattr(self.instance, 'pk', None):
            self.fields['price_input_currency'].initial = (
                self.instance.price_original_currency or self.instance.price_input_currency or 'USD'
            )
            self.fields['price_in_currency'].initial = self.instance.price_original
        else:
            self.fields['price_input_currency'].initial = 'USD'

    # Champs pour la devise et le prix
    price_input_currency = forms.ChoiceField(
        choices=[
            ('USD', 'USD ($)'),
            ('HTG', 'Gourdes (HTG)'),
            ('DOP', 'Peso Dominicain (DOP)'),
            ('EUR', 'Euro (€)'),
        ],
        required=True,
        label='Devise du prix',
        widget=forms.Select(attrs={
            'class': 'form-control',
            'id': 'id_price_input_currency'
        }),
        help_text='Choisissez la devise pour le prix du produit.'
    )
    
    price_in_currency = forms.DecimalField(
        max_digits=15,
        decimal_places=2,
        required=True,
        label='Montant du prix',
        widget=forms.NumberInput(attrs={
            'step': '0.01',
            'placeholder': 'Prix dans la devise choisie',
            'class': 'form-control',
            'id': 'id_price_in_currency'
        }),
        help_text='Entrez le montant du produit dans la devise choisie. Le système convertira automatiquement en USD.'
    )

    class Meta:
        model = Product
        fields = ['name', 'description', 'price_input_currency', 'quantity', 'category', 'largeur', 'hauteur', 'longueur', 'poids', 'image', 'custom_image']
        widgets = {
            'name': forms.TextInput(attrs={
                'placeholder': 'Nom du produit',
                'class': 'form-control',
                'id': 'id_name'
            }),
            'description': forms.Textarea(attrs={
                'placeholder': 'Description du produit',
                'rows': 4,
                'class': 'form-control'
            }),
            'quantity': forms.NumberInput(attrs={
                'min': '0',
                'placeholder': 'Quantité',
                'class': 'form-control'
            }),
            'category': forms.Select(attrs={
                'class': 'form-control'
            }),
            'image': forms.URLInput(attrs={
                'placeholder': 'URL de l\'image auto-générée',
                'class': 'form-control',
                'id': 'id_image',
                'readonly': True
            })
        }

class ProductReviewForm(forms.ModelForm):
    class Meta:
        model = ProductReview
        fields = ['rating', 'comment']
        widgets = {
            'rating': forms.Select(attrs={'class': 'form-control'}),
            'comment': forms.Textarea(attrs={
                'placeholder': 'Votre avis ici...',
                'rows': 4,
                'class': 'form-control'
            }),
        }
        labels = {
            'rating': 'Note',
            'comment': 'Commentaire',
        }

class ProductImageForm(forms.ModelForm):
    class Meta:
        model = ProductImage
        fields = ['image', 'alt_text', 'is_primary']
        widgets = {
            'image': forms.FileInput(attrs={
                'accept': 'image/*',
                'class': 'form-control'
            }),
            'alt_text': forms.TextInput(attrs={
                'placeholder': 'Description de l\'image (pour accessibilité)',
                'class': 'form-control'
            }),
            'is_primary': forms.CheckboxInput(attrs={
                'class': 'form-check-input'
            })
        }

class AssignmentSubmissionForm(forms.Form):
    assignment_title = forms.CharField(
        max_length=200,
        label='Titre du devoir',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Titre du devoir'
        })
    )
    comments = forms.CharField(
        required=False,
        label='Commentaires',
        widget=forms.Textarea(attrs={
            'class': 'form-control',
            'placeholder': 'Commentaires ou informations complémentaires',
            'rows': 4
        })
    )
    submission_file = forms.FileField(
        label='Fichier de soumission',
        widget=forms.FileInput(attrs={
            'accept': '.pdf,.doc,.docx,.txt,.zip,.rar',
            'class': 'form-control'
        })
    )

    def clean_submission_file(self):
        file = self.cleaned_data.get('submission_file')
        if file:
            MAX_FILE_SIZE = 10 * 1024 * 1024
            if file.size > MAX_FILE_SIZE:
                raise forms.ValidationError('Le fichier dépasse la taille maximale de 10 MB.')
        return file

class ProfileForm(forms.ModelForm):
    first_name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': 'Prénom',
            'class': 'form-control'
        }),
        label='Prénom'
    )
    last_name = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={
            'placeholder': 'Nom',
            'class': 'form-control'
        }),
        label='Nom'
    )
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={
            'placeholder': 'Adresse email',
            'class': 'form-control'
        }),
        label='Email'
    )

    class Meta:
        model = Profile
        fields = ['first_name', 'last_name', 'email', 'address', 'phone', 'photo']
        widgets = {
            'address': forms.TextInput(attrs={
                'placeholder': 'Adresse complète',
                'class': 'form-control'
            }),
            'phone': forms.TextInput(attrs={
                'placeholder': 'Numéro de téléphone',
                'class': 'form-control'
            }),
            'photo': forms.FileInput(attrs={
                'accept': 'image/*',
                'class': 'form-control'
            })
        }
        labels = {
            'address': 'Adresse',
            'phone': 'Téléphone',
            'photo': 'Photo de profil',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and hasattr(self.instance, 'user'):
            self.fields['first_name'].initial = self.instance.user.first_name
            self.fields['last_name'].initial = self.instance.user.last_name
            self.fields['email'].initial = self.instance.user.email

    def clean_phone(self):
        phone = self.cleaned_data.get('phone')
        if phone:
            return normalize_phone_number(phone)
        return phone

    def save(self, commit=True):
        profile = super().save(commit=False)
        user = profile.user
        user.first_name = self.cleaned_data.get('first_name', user.first_name)
        user.last_name = self.cleaned_data.get('last_name', user.last_name)
        email = self.cleaned_data.get('email')
        if email:
            user.email = email
        if commit:
            user.save()
            profile.save()
        return profile

class TiKaneAccessRequestForm(forms.ModelForm):
    identity_document = forms.ImageField(
        required=True,
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*', 'capture': 'environment'}),
        label='Carte d’identité'
    )
    passport_document = forms.ImageField(
        required=True,
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*', 'capture': 'environment'}),
        label='Passeport'
    )
    driver_license_document = forms.ImageField(
        required=True,
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*', 'capture': 'environment'}),
        label='Permis de conduire'
    )
    selfie = forms.ImageField(
        required=True,
        widget=forms.FileInput(attrs={'class': 'form-control', 'accept': 'image/*', 'capture': 'user'}),
        label='Selfie en direct via caméra'
    )

    class Meta:
        model = TiKaneAccessRequest
        fields = [
            'full_name', 'email', 'phone', 'plan', 'identity_document',
            'passport_document', 'driver_license_document', 'selfie', 'acceptance_clause',
        ]
        widgets = {
            'full_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nom complet'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email'}),
            'phone': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Téléphone'}),
            'plan': forms.Select(attrs={'class': 'form-control'}),
        }
        labels = {
            'acceptance_clause': 'J’accepte la clause de responsabilité SDI Marché Mondial',
        }

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get('acceptance_clause'):
            raise forms.ValidationError('Vous devez accepter la clause de responsabilité pour soumettre la demande.')
        if not cleaned.get('identity_document'):
            raise forms.ValidationError('Veuillez téléverser votre carte d’identité.')
        if not cleaned.get('passport_document'):
            raise forms.ValidationError('Veuillez téléverser votre passeport.')
        if not cleaned.get('driver_license_document'):
            raise forms.ValidationError('Veuillez téléverser votre permis de conduire.')
        if not cleaned.get('selfie'):
            raise forms.ValidationError('Veuillez téléverser un selfie en direct.')
        return cleaned

class TiKanePlanForm(forms.ModelForm):
    class Meta:
        model = TiKanePlan
        fields = ['name', 'duration_days', 'commission_fixed', 'commission_variable', 'bonus_rate', 'description', 'active']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nom du plan'}),
            'duration_days': forms.Select(attrs={'class': 'form-control'}),
            'commission_fixed': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'commission_variable': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'bonus_rate': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }
        labels = {
            'commission_fixed': 'Commission fixe',
            'commission_variable': 'Commission variable (%)',
            'bonus_rate': 'Bonus de rendement (%)',
            'active': 'Plan actif',
        }

class TransferForm(forms.Form):
    recipient_account_code = forms.CharField(
        required=True,
        label='Numéro du compte destinataire',
        widget=forms.TextInput(attrs={
            'placeholder': 'ACC178E50D7',
            'class': 'form-control'
        })
    )
    source_account = forms.ChoiceField(
        required=True,
        label='Compte source',
        choices=[
            ('principal', 'Solde Principal'),
            ('micro_device', 'MicroSDI Multi-appareils'),
        ],
        widget=forms.Select(attrs={
            'class': 'form-control'
        })
    )
    currency = forms.ChoiceField(
        required=True,
        label='Devise',
        choices=[
            ('USD', 'USD'),
            ('HTG', 'HTG'),
            ('EUR', 'EUR'),
            ('DOP', 'DOP'),
        ],
        widget=forms.Select(attrs={
            'class': 'form-control'
        })
    )
    amount = forms.DecimalField(
        required=True,
        min_value=Decimal('0.01'),
        max_digits=15,
        decimal_places=2,
        label='Montant du transfert',
        widget=forms.NumberInput(attrs={
            'placeholder': 'Montant',
            'class': 'form-control',
            'step': '0.01'
        })
    )

    def clean_recipient_account_code(self):
        account_code = self.cleaned_data.get('recipient_account_code', '').strip().upper()
        if not account_code:
            raise ValidationError('Veuillez entrer un numéro de compte destinataire.')
        if not User.objects.filter(account_code__iexact=account_code).exists():
            raise ValidationError('Compte introuvable.')
        return account_code

    def clean_amount(self):
        amount = self.cleaned_data.get('amount')
        if amount and amount <= 0:
            raise ValidationError('Le montant doit être supérieur à zéro.')
        return amount


class ChatMessageForm(forms.ModelForm):
    class Meta:
        model = ChatMessage
        fields = ['content', 'image', 'product']
        widgets = {
            'content': forms.Textarea(attrs={
                'placeholder': 'Écrivez un message, partagez un produit, ou envoyez une image...',
                'rows': 3,
                'class': 'form-control'
            }),
            'product': forms.Select(attrs={
                'class': 'form-control'
            }),
            'image': forms.FileInput(attrs={
                'accept': 'image/*',
                'class': 'form-control'
            }),
        }
        labels = {
            'content': 'Message',
            'image': 'Image (optionnelle)',
            'product': 'Produit à partager (optionnel)'
        }

    def clean(self):
        cleaned_data = super().clean()
        content = cleaned_data.get('content', '').strip()
        image = cleaned_data.get('image')
        product = cleaned_data.get('product')
        if not content and not image and not product:
            raise forms.ValidationError('Veuillez écrire un message, ajouter une image ou sélectionner un produit.')
        return cleaned_data


class PrivateMessageForm(forms.ModelForm):
    class Meta:
        model = PrivateMessage
        fields = ['content', 'image', 'product']
        widgets = {
            'content': forms.Textarea(attrs={
                'placeholder': 'Écrivez un message privé...',
                'rows': 3,
                'class': 'form-control'
            }),
            'product': forms.Select(attrs={
                'class': 'form-control'
            }),
            'image': forms.FileInput(attrs={
                'accept': 'image/*',
                'class': 'form-control'
            }),
        }
        labels = {
            'content': 'Message',
            'image': 'Image (optionnelle)',
            'product': 'Produit à partager (optionnel)'
        }

    def clean(self):
        cleaned_data = super().clean()
        content = cleaned_data.get('content', '').strip()
        image = cleaned_data.get('image')
        product = cleaned_data.get('product')
        if not content and not image and not product:
            raise forms.ValidationError('Veuillez écrire un message privé ou ajouter une image ou sélectionner un produit.')
        return cleaned_data


class BeautyBookingForm(forms.ModelForm):
    class Meta:
        model = BeautyAppointment
        fields = ['product', 'booking_type', 'scheduled_date', 'scheduled_time', 'address', 'instructions']
        widgets = {
            'product': forms.HiddenInput(),
            'booking_type': forms.Select(attrs={
                'class': 'form-control'
            }),
            'scheduled_date': forms.DateInput(attrs={
                'type': 'date',
                'class': 'form-control'
            }),
            'scheduled_time': forms.TimeInput(attrs={
                'type': 'time',
                'class': 'form-control'
            }),
            'address': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': 'Adresse du domicile ou précisez si vous venez au studio',
                'class': 'form-control'
            }),
            'instructions': forms.Textarea(attrs={
                'rows': 3,
                'placeholder': 'Informations supplémentaires pour le technicien (allergies, style, etc.)',
                'class': 'form-control'
            }),
        }
        labels = {
            'product': 'Service sélectionné',
            'booking_type': 'Type de service',
            'scheduled_date': 'Date du rendez-vous',
            'scheduled_time': 'Heure du rendez-vous',
            'address': 'Adresse',
            'instructions': 'Instructions',
        }

    def clean(self):
        cleaned_data = super().clean()
        booking_type = cleaned_data.get('booking_type')
        address = cleaned_data.get('address', '').strip()
        if booking_type == 'home' and not address:
            self.add_error('address', 'Veuillez indiquer l’adresse de service à domicile.')
        return cleaned_data

class BeautyStudioServiceForm(forms.ModelForm):
    class Meta:
        model = BeautyStudioService
        fields = ['service_type', 'title', 'price_ht', 'image', 'description']
        widgets = {
            'service_type': forms.Select(attrs={
                'class': 'form-control'
            }),
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nom du service (ex: Manucure classique)'
            }),
            'price_ht': forms.NumberInput(attrs={
                'class': 'form-control',
                'step': '0.01',
                'placeholder': 'Prix en USD'
            }),
            'image': forms.FileInput(attrs={
                'class': 'form-control'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Description courte du service'
            }),
        }
        labels = {
            'service_type': 'Type de service',
            'title': 'Nom du service',
            'price_ht': 'Prix du service (USD)',
            'image': 'Photo du service',
            'description': 'Description',
        }


class BeautyStudioRequestForm(forms.ModelForm):
    class Meta:
        model = BeautyStudioRequest
        fields = ['studio_name', 'description', 'phone', 'address', 'specialties']
        widgets = {
            'studio_name': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nom de votre studio de beauté'
            }),
            'description': forms.Textarea(attrs={
                'rows': 4,
                'class': 'form-control',
                'placeholder': 'Décrivez vos services et votre expérience...'
            }),
            'phone': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Numéro de téléphone',
                'type': 'tel'
            }),
            'address': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Adresse de votre studio'
            }),
            'specialties': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: coiffure, maquillage, massages, manucure'
            }),
        }
        labels = {
            'studio_name': 'Nom du studio',
            'description': 'Description des services',
            'phone': 'Téléphone de contact',
            'address': 'Adresse du studio',
            'specialties': 'Vos spécialités',
        }

class SystemSettingsForm(forms.ModelForm):
    class Meta:
        model = SystemSettings
        fields = [
            'banner_visible_to_admins',
            'principal_banner_visible',
            'enable_role_management',
            'enable_financial_audit',
            'enable_alerts',
            'enable_cybersecurity',
            'enable_rollback',
            'enable_dispute_management',
            'microsdicash_account_name',
            'microsdicash_account_number',
            'microsdicash_account_phone',
            'microsdicash_payment_instructions',
        ]
        widgets = {
            'banner_visible_to_admins': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'principal_banner_visible': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'enable_role_management': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'enable_financial_audit': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'enable_alerts': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'enable_cybersecurity': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'enable_rollback': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'enable_dispute_management': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'microsdicash_account_name': forms.TextInput(attrs={'class': 'form-control'}),
            'microsdicash_account_number': forms.TextInput(attrs={'class': 'form-control'}),
            'microsdicash_account_phone': forms.TextInput(attrs={'class': 'form-control'}),
            'microsdicash_payment_instructions': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }


class BannerExpandSettingsForm(forms.ModelForm):
    class Meta:
        model = SystemSettings
        fields = ['banner_expand_enabled', 'banner_normal_height', 'banner_expanded_height']
        widgets = {
            'banner_expand_enabled': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'banner_normal_height': forms.NumberInput(attrs={'class': 'form-control', 'min': 100, 'max': 500}),
            'banner_expanded_height': forms.NumberInput(attrs={'class': 'form-control', 'min': 120, 'max': 700}),
        }

    def clean(self):
        cleaned_data = super().clean()
        normal_height = cleaned_data.get('banner_normal_height')
        expanded_height = cleaned_data.get('banner_expanded_height')
        if normal_height and expanded_height and expanded_height <= normal_height:
            self.add_error('banner_expanded_height', 'La hauteur agrandie doit être supérieure à la hauteur normale.')
        return cleaned_data


class PriorityGroupForm(forms.ModelForm):
    class Meta:
        model = PriorityGroup
        fields = ['name', 'priority', 'weight', 'is_active', 'start_date', 'end_date']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'priority': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'weight': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'max': '100'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'start_date': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
            'end_date': forms.DateTimeInput(attrs={'class': 'form-control', 'type': 'datetime-local'}),
        }


class BannerProductPriorityForm(forms.ModelForm):
    class Meta:
        model = Product
        fields = ['priority_group', 'banner_priority', 'banner_weight', 'banner_display_allowed']
        widgets = {
            'priority_group': forms.Select(attrs={'class': 'form-control'}),
            'banner_priority': forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'banner_weight': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'max': '100'}),
            'banner_display_allowed': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


class OrderForm(forms.ModelForm):
    """Formulaire pour saisir les informations de livraison lors de la commande"""
    delivery_address = forms.CharField(
        label="Adresse de livraison complète",
        widget=forms.Textarea(attrs={
            'rows': 3,
            'placeholder': 'Entrez votre adresse complète avec numéro, rue, ville, code postal...',
            'class': 'form-control'
        }),
        help_text="Adresse où vous souhaitez recevoir votre commande"
    )

    buyer_address_details = forms.CharField(
        label="Instructions de livraison (optionnel)",
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 2,
            'placeholder': 'Ex: Sonner à l\'interphone, laisser devant la porte, contacter au numéro...',
            'class': 'form-control'
        }),
        help_text="Instructions spéciales pour le livreur"
    )

    # Champs cachés pour les coordonnées GPS
    buyer_lat = forms.DecimalField(
        required=False,
        widget=forms.HiddenInput(),
        max_digits=9,
        decimal_places=6
    )

    buyer_lng = forms.DecimalField(
        required=False,
        widget=forms.HiddenInput(),
        max_digits=9,
        decimal_places=6
    )

    class Meta:
        model = Order
        fields = ['delivery_address', 'buyer_address_details', 'buyer_lat', 'buyer_lng']

    def clean(self):
        cleaned_data = super().clean()
        delivery_address = cleaned_data.get('delivery_address')
        buyer_lat = cleaned_data.get('buyer_lat')
        buyer_lng = cleaned_data.get('buyer_lng')

        # GPS is optional for now
        # if delivery_address and not (buyer_lat and buyer_lng):
        #     raise forms.ValidationError('Veuillez sélectionner votre position sur la carte.')

        return cleaned_data


class DeliveryLocationForm(forms.Form):
    """Formulaire pour que le livreur saisisse sa position actuelle"""
    driver_lat = forms.DecimalField(
        required=False,
        widget=forms.HiddenInput(),
        max_digits=9,
        decimal_places=6
    )

    driver_lng = forms.DecimalField(
        required=False,
        widget=forms.HiddenInput(),
        max_digits=9,
        decimal_places=6
    )

    driver_address_details = forms.CharField(
        label="Adresse actuelle détaillée",
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 2,
            'placeholder': 'Décrivez votre position actuelle (ex: Près du café central, parking du supermarché...)',
            'class': 'form-control'
        }),
        help_text="Aide pour localiser votre position"
    )

    def clean(self):
        cleaned_data = super().clean()
        driver_lat = cleaned_data.get('driver_lat')
        driver_lng = cleaned_data.get('driver_lng')

        if not (driver_lat and driver_lng):
            raise forms.ValidationError('Veuillez sélectionner votre position actuelle sur la carte.')

        return cleaned_data


class OrderForm(forms.ModelForm):
    """Formulaire pour saisir les informations de livraison lors de la commande"""
    delivery_address = forms.CharField(
        label="Adresse de livraison complète",
        widget=forms.Textarea(attrs={
            'rows': 3,
            'placeholder': 'Entrez votre adresse complète avec numéro, rue, ville, code postal...',
            'class': 'form-control'
        }),
        help_text="Adresse où vous souhaitez recevoir votre commande"
    )

    buyer_address_details = forms.CharField(
        label="Instructions de livraison (optionnel)",
        required=False,
        widget=forms.Textarea(attrs={
            'rows': 2,
            'placeholder': 'Ex: Sonner à l\'interphone, laisser devant la porte, contacter au numéro...',
            'class': 'form-control'
        }),
        help_text="Instructions spéciales pour le livreur"
    )

    # Champs cachés pour les coordonnées GPS
    buyer_lat = forms.DecimalField(
        required=False,
        widget=forms.HiddenInput(),
        max_digits=9,
        decimal_places=6
    )

    buyer_lng = forms.DecimalField(
        required=False,
        widget=forms.HiddenInput(),
        max_digits=9,
        decimal_places=6
    )

    payment_method = forms.ChoiceField(
        label="Moyen de paiement",
        choices=Order.payment_method_choices,
        initial="htg_wallet",
        widget=forms.RadioSelect(attrs={'class': 'form-check-input'}),
        help_text="Choisissez votre mode de paiement."
    )
    map_failed = forms.BooleanField(
        required=False,
        widget=forms.HiddenInput(),
        initial=False
    )

    class Meta:
        model = Order
        fields = ['delivery_address', 'buyer_address_details', 'buyer_lat', 'buyer_lng', 'payment_method']

    def clean(self):
        cleaned_data = super().clean()
        delivery_address = cleaned_data.get('delivery_address')
        buyer_lat = cleaned_data.get('buyer_lat')
        buyer_lng = cleaned_data.get('buyer_lng')
        map_failed = cleaned_data.get('map_failed')

        if delivery_address and not (buyer_lat and buyer_lng) and not map_failed:
            raise forms.ValidationError('Veuillez sélectionner votre position sur la carte.')

        return cleaned_data


# ==========================================
# FORMULAIRE POUR LES ANNONCES ADMINISTRATIVES
# ==========================================

class AdminAnnouncementForm(forms.ModelForm):
    """Formulaire pour créer et modifier les annonces administratives"""
    
    class Meta:
        model = AdminAnnouncement
        fields = [
            'title', 'message', 'icon',
            'status', 'is_priority', 'is_active',
            'start_date', 'end_date',
            'background_color', 'text_color', 'accent_color',
            'scroll_speed', 'enable_loop', 'animation_effect',
        ]
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: Nouvelle promotion disponible',
                'maxlength': '200'
            }),
            'message': forms.Textarea(attrs={
                'class': 'form-control',
                'placeholder': 'Entrez le message de l\'annonce...',
                'rows': 4
            }),
            'icon': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': '📢',
                'maxlength': '20'
            }),
            'status': forms.Select(attrs={
                'class': 'form-control',
            }),
            'is_priority': forms.CheckboxInput(attrs={
                'class': 'form-check-input',
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'form-check-input',
            }),
            'start_date': forms.DateTimeInput(attrs={
                'class': 'form-control',
                'type': 'datetime-local',
            }),
            'end_date': forms.DateTimeInput(attrs={
                'class': 'form-control',
                'type': 'datetime-local',
            }),
            'background_color': forms.TextInput(attrs={
                'class': 'form-control',
                'type': 'color',
            }),
            'text_color': forms.TextInput(attrs={
                'class': 'form-control',
                'type': 'color',
            }),
            'accent_color': forms.TextInput(attrs={
                'class': 'form-control',
                'type': 'color',
            }),
            'scroll_speed': forms.Select(attrs={
                'class': 'form-control',
            }),
            'enable_loop': forms.CheckboxInput(attrs={
                'class': 'form-check-input',
            }),
            'animation_effect': forms.Select(attrs={
                'class': 'form-control',
            }),
        }
        labels = {
            'title': 'Titre de l\'annonce',
            'message': 'Message administratif',
            'icon': 'Emoji/Icône',
            'status': 'Statut',
            'is_priority': 'Annonce prioritaire',
            'is_active': 'Activée',
            'start_date': 'Date de début',
            'end_date': 'Date de fin',
            'background_color': 'Couleur de fond',
            'text_color': 'Couleur du texte',
            'accent_color': 'Couleur d\'accent',
            'scroll_speed': 'Vitesse de défilement',
            'enable_loop': 'Défilement en boucle',
            'animation_effect': 'Effet d\'animation',
        }

