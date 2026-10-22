# ==========================================
# MODULE IMMOBILIER - MAISON À LOUER SDI
# ==========================================

from django.db import models
from django.utils import timezone
from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator

User = get_user_model()


# ==========================================
# MODÈLE PROPRIÉTÉ
# ==========================================
class Property(models.Model):
    """Modèle pour les propriétés immobilières"""
    
    PROPERTY_TYPE_CHOICES = (
        ('maison', 'Maison'),
        ('appartement', 'Appartement'),
        ('terrain', 'Terrain'),
        ('local_commercial', 'Local commercial'),
    )
    
    STATUS_CHOICES = (
        ('disponible', 'Disponible'),
        ('loue', 'Loué'),
        ('vente_en_cours', 'Vente en cours'),
        ('indisponible', 'Indisponible'),
    )
    
    LISTING_TYPE_CHOICES = (
        ('vente', 'À vendre'),
        ('location', 'À louer'),
    )
    
    APPROVAL_STATUS_CHOICES = (
        ('en_attente', 'En attente'),
        ('approuvee', 'Approuvée'),
        ('rejetee', 'Rejetée'),
    )
    
    # Informations de base
    title = models.CharField(max_length=200, verbose_name='Titre de l\'annonce')
    description = models.TextField(verbose_name='Description détaillée')
    property_type = models.CharField(max_length=20, choices=PROPERTY_TYPE_CHOICES, verbose_name='Type de bien')
    listing_type = models.CharField(max_length=20, choices=LISTING_TYPE_CHOICES, verbose_name='Statut')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='disponible', verbose_name='État')
    
    # Localisation
    address = models.CharField(max_length=255, verbose_name='Adresse complète')
    city = models.CharField(max_length=100, verbose_name='Ville')
    neighborhood = models.CharField(max_length=100, blank=True, verbose_name='Quartier')
    country = models.CharField(max_length=100, default='Haiti', verbose_name='Pays')
    latitude = models.FloatField(null=True, blank=True, verbose_name='Latitude')
    longitude = models.FloatField(null=True, blank=True, verbose_name='Longitude')
    
    # Détails du bien
    price = models.DecimalField(max_digits=15, decimal_places=2, validators=[MinValueValidator(0)], verbose_name='Prix')
    currency = models.CharField(max_length=3, default='HTG', verbose_name='Devise')
    total_area = models.FloatField(validators=[MinValueValidator(0)], verbose_name='Surface totale (m²)')
    bedrooms = models.IntegerField(default=0, validators=[MinValueValidator(0)], verbose_name='Nombre de chambres')
    bathrooms = models.IntegerField(default=0, validators=[MinValueValidator(0)], verbose_name='Nombre de salles de bain')
    has_parking = models.BooleanField(default=False, verbose_name='Dispose d\'un parking')
    has_garden = models.BooleanField(default=False, verbose_name='Dispose d\'un jardin')
    has_balcony = models.BooleanField(default=False, verbose_name='Dispose d\'un balcon')
    has_gate = models.BooleanField(default=False, verbose_name='Dispose d\'une clôture/barrière')
    
    # Propriétaire / Agent
    owner = models.ForeignKey(User, on_delete=models.CASCADE, related_name='real_estate_properties', verbose_name='Propriétaire')
    agent = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='managed_properties', verbose_name='Agent immobilier')
    
    # Validation
    approval_status = models.CharField(max_length=20, choices=APPROVAL_STATUS_CHOICES, default='en_attente', verbose_name='Statut d\'approbation')
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_properties', verbose_name='Approuvé par')
    rejected_reason = models.TextField(blank=True, verbose_name='Raison du rejet')
    
    # Métadonnées
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Créé le')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Modifié le')
    published_at = models.DateTimeField(null=True, blank=True, verbose_name='Publié le')
    view_count = models.IntegerField(default=0, verbose_name='Nombre de vues')
    contact_count = models.IntegerField(default=0, verbose_name='Nombre de contacts')
    
    class Meta:
        verbose_name = 'Propriété immobilière'
        verbose_name_plural = 'Propriétés immobilières'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['city', 'property_type']),
            models.Index(fields=['approval_status', 'listing_type']),
            models.Index(fields=['-created_at']),
        ]
    
    def __str__(self):
        return f"{self.title} - {self.city}"
    
    def approve(self, admin_user):
        """Approuve la propriété"""
        self.approval_status = 'approuvee'
        self.approved_by = admin_user
        self.published_at = timezone.now()
        self.status = 'disponible'
        self.save()
    
    def reject(self, admin_user, reason=''):
        """Rejette la propriété"""
        self.approval_status = 'rejetee'
        self.approved_by = admin_user
        self.rejected_reason = reason
        self.save()


# ==========================================
# MODÈLE IMAGE DE PROPRIÉTÉ
# ==========================================
class PropertyImage(models.Model):
    """Modèle pour les images des propriétés"""
    
    IMAGE_TYPE_CHOICES = (
        ('facade', 'Façade'),
        ('avant', 'Surface avant'),
        ('entree', 'Porte principale'),
        ('fenetres', 'Fenêtres'),
        ('salon', 'Salon'),
        ('cuisine', 'Cuisine'),
        ('chambre', 'Chambre'),
        ('salle_bain', 'Salle de bain'),
        ('toilettes', 'Toilettes'),
        ('parking', 'Parking'),
        ('balcon', 'Balcon'),
        ('jardin', 'Jardin'),
        ('cloture', 'Clôture / Barrière'),
        ('autre', 'Autre'),
    )
    
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='images', verbose_name='Propriété')
    image = models.ImageField(upload_to='real_estate/%Y/%m/', verbose_name='Image')
    image_type = models.CharField(max_length=20, choices=IMAGE_TYPE_CHOICES, verbose_name='Type d\'image')
    caption = models.CharField(max_length=255, blank=True, verbose_name='Légende')
    order = models.IntegerField(default=0, verbose_name='Ordre d\'affichage')
    uploaded_at = models.DateTimeField(auto_now_add=True, verbose_name='Téléchargé le')
    
    class Meta:
        verbose_name = 'Image de propriété'
        verbose_name_plural = 'Images de propriété'
        ordering = ['order', 'uploaded_at']
    
    def __str__(self):
        return f"Image - {self.property.title}"


# ==========================================
# MODÈLE FAVORIS
# ==========================================
class PropertyFavorite(models.Model):
    """Modèle pour les propriétés mises en favoris"""
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='favorite_properties', verbose_name='Utilisateur')
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='favorited_by', verbose_name='Propriété')
    added_at = models.DateTimeField(auto_now_add=True, verbose_name='Ajouté le')
    
    class Meta:
        verbose_name = 'Favoris immobilier'
        verbose_name_plural = 'Favoris immobilier'
        unique_together = ['user', 'property']
        ordering = ['-added_at']
    
    def __str__(self):
        return f"{self.user.username} - {self.property.title}"


# ==========================================
# MODÈLE MESSAGE
# ==========================================
class RealEstateMessage(models.Model):
    """Modèle pour la messagerie entre utilisateurs et propriétaires"""
    
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='messages', verbose_name='Propriété')
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='sent_real_estate_messages', verbose_name='Expéditeur')
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='received_real_estate_messages', verbose_name='Destinataire')
    message = models.TextField(verbose_name='Message')
    
    # Métadonnées
    is_read = models.BooleanField(default=False, verbose_name='Lu')
    read_at = models.DateTimeField(null=True, blank=True, verbose_name='Lu le')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Créé le')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Modifié le')
    
    # Gestion admin
    admin_replied = models.BooleanField(default=False, verbose_name='Admin a répondu')
    admin_reply_blocked = models.BooleanField(default=False, verbose_name='Réponse admin bloquée')
    admin_reply_reason = models.TextField(blank=True, verbose_name='Raison du blocage')
    
    class Meta:
        verbose_name = 'Message immobilier'
        verbose_name_plural = 'Messages immobilier'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Message de {self.sender.username} - {self.property.title}"
    
    def mark_as_read(self):
        """Marque le message comme lu"""
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save()


# ==========================================
# MODÈLE SIGNALEMENT / AVIS
# ==========================================
class PropertyReview(models.Model):
    """Modèle pour les avis et signalements"""
    
    REVIEW_TYPE_CHOICES = (
        ('avis', 'Avis positif'),
        ('probleme', 'Problème'),
        ('arnaque', 'Signalement arnaque'),
        ('donnees_incorrectes', 'Données incorrectes'),
        ('autre', 'Autre'),
    )
    
    property = models.ForeignKey(Property, on_delete=models.CASCADE, related_name='reviews', verbose_name='Propriété')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='property_reviews', verbose_name='Utilisateur')
    review_type = models.CharField(max_length=20, choices=REVIEW_TYPE_CHOICES, verbose_name='Type d\'avis')
    title = models.CharField(max_length=200, verbose_name='Titre')
    description = models.TextField(verbose_name='Description')
    rating = models.IntegerField(default=5, validators=[MinValueValidator(1)], verbose_name='Note (1-5)', help_text='1 à 5 étoiles')
    
    # Modération
    is_verified = models.BooleanField(default=False, verbose_name='Vérifié')
    is_approved = models.BooleanField(default=False, verbose_name='Approuvé')
    moderated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='moderated_reviews', verbose_name='Modéré par')
    
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Créé le')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='Modifié le')
    
    class Meta:
        verbose_name = 'Avis immobilier'
        verbose_name_plural = 'Avis immobilier'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.review_type} - {self.property.title}"


# ==========================================
# MODÈLE NOTIFICATION
# ==========================================
class RealEstateNotification(models.Model):
    """Modèle pour les notifications du module immobilier"""
    
    NOTIFICATION_TYPE_CHOICES = (
        ('nouveau_message', 'Nouveau message'),
        ('propriete_approuvee', 'Propriété approuvée'),
        ('propriete_rejetee', 'Propriété rejetée'),
        ('favori_ajoute', 'Favori ajouté'),
        ('propriete_contactee', 'Propriété contactée'),
        ('avis_recu', 'Avis reçu'),
    )
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='real_estate_notifications', verbose_name='Utilisateur')
    notification_type = models.CharField(max_length=30, choices=NOTIFICATION_TYPE_CHOICES, verbose_name='Type de notification')
    property = models.ForeignKey(Property, on_delete=models.CASCADE, null=True, blank=True, verbose_name='Propriété')
    title = models.CharField(max_length=200, verbose_name='Titre')
    message = models.TextField(verbose_name='Message')
    
    is_read = models.BooleanField(default=False, verbose_name='Lu')
    read_at = models.DateTimeField(null=True, blank=True, verbose_name='Lu le')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Créé le')
    
    class Meta:
        verbose_name = 'Notification immobilier'
        verbose_name_plural = 'Notifications immobilier'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.notification_type} - {self.user.username}"
    
    def mark_as_read(self):
        """Marque la notification comme lue"""
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save()


# ==========================================
# MODÈLE DEMANDE D'ADHÉSION IMMOBILIÈRE
# ==========================================
class RealEstateMembershipRequest(models.Model):
    """Demande d'adhésion pour devenir membre immobilier (peut lister des biens)."""

    STATUS_CHOICES = (
        ('pending', 'En attente'),
        ('approved', 'Approuvée'),
        ('rejected', 'Rejetée'),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='real_estate_membership_requests', verbose_name='Utilisateur')
    full_name = models.CharField(max_length=200, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    sample_property_title = models.CharField(max_length=200, blank=True)
    message = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    admin_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Demande d'adhésion immobilier"
        verbose_name_plural = "Demandes d'adhésion immobilier"
        ordering = ['-created_at']

    def __str__(self):
        return f"MembershipRequest {self.user.username} - {self.get_status_display()}"
