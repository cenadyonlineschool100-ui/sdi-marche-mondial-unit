# -*- coding: utf-8 -*-
from django.contrib import admin
from django.urls import path
from django.shortcuts import redirect
from django.contrib import messages
from django import forms
from django.utils import timezone
from decimal import Decimal
from .models import (
    User, Shop, Product, Wallet, Order, OrderItem, Transaction, AdminAddTransaction,
    Transfer, TransferReceipt, TransferLog, TransferNotification,
    DeliveryEmployee, DeliveryAssignment, Agent, AuditLog, ProductReview, DeliveryTracking,
    DeliveryNotification, ReturnRequest, Profile, ExchangeRate, PrivateConversation,
    PrivateMessage, SecurityIncident, SecurityEvent, IPBlocklist, SiteConfiguration,
    SiteConfigurationPermission, PortMonitoring, AIThreatAnalysis, HoneypotEvent,
    SecurityAlert, SecurityLog, SecurityMetrics, AntiBotField, AntiBotDetection,
    SecurityVulnerability, VulnerabilityFix, AISecurityAudit, ContinuousSecurityMonitoring,
    AISecurityRecommendation, Receipt, WithdrawalRequest, AdminWithdrawalPermission,
    Course, CourseAssignment, AssignmentSubmission, CourseCertificate,
    WithdrawalCommissionTier, TransferCommissionTier, WithdrawalTransaction, AdminCommissionLog,
    DepositCommissionConfig, Deposit, AgentCommission, CommissionRule, DepositLimit, AdminSetting,
    MarketplaceSettings, CommissionCategory, UserCommissionCategory, CommissionDistributionLog,
    TiKaneAccessRequest, TiKanePlan, TiKaneAccount, TiKaneDailyPayment,
    SDISolSettings, SDISolMember, SDISolPayment, ActivityMenuItem, BeautyAppointment, BeautyStudioRequest, TechnicianProfile,
    Property, PropertyImage, PropertyFavorite, RealEstateMessage, PropertyReview, RealEstateNotification,
    AdminAnnouncement, AdminAnnouncementPermission,
    
    # Real estate membership requests
    
)
from .business_logic import fetch_exchange_rates_from_api
from .models import ProductAccessRequest, ResellerProduct, MarketplaceSettings, MarketplaceSellerCommission
from .real_estate_models import RealEstateMembershipRequest


@admin.register(RealEstateMembershipRequest)
class RealEstateMembershipRequestAdmin(admin.ModelAdmin):
    list_display = ('user', 'full_name', 'phone', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('user__username', 'full_name', 'phone')

@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('user', 'action', 'timestamp')
    list_filter = ('action', 'timestamp')
    readonly_fields = ('user', 'action', 'details', 'timestamp', 'ip_address')

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = ('id', 'sender', 'receiver', 'amount', 'type', 'status', 'created_at')
    list_filter = ('type', 'status', 'created_at')
    search_fields = ('sender__username', 'receiver__username', 'type')

@admin.register(AdminAddTransaction)
class AdminAddTransactionAdmin(admin.ModelAdmin):
    list_display = ('id', 'sender_display', 'receiver', 'amount', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('receiver__username',)

    def sender_display(self, obj):
        return obj.sender.username if obj.sender else 'Admin'
    sender_display.short_description = 'Envoyé par'

@admin.register(Transfer)
class TransferAdmin(admin.ModelAdmin):
    list_display = ('transaction_id', 'sender', 'receiver', 'sender_account_type', 'currency', 'amount', 'fee', 'system_fee', 'agent_fee', 'status', 'created_at')
    list_filter = ('sender_account_type', 'currency', 'status', 'created_at')
    search_fields = ('transaction_id', 'sender__username', 'receiver__username')
    readonly_fields = ('transaction_id', 'created_at', 'updated_at')

@admin.register(TransferCommissionTier)
class TransferCommissionTierAdmin(admin.ModelAdmin):
    list_display = ('description', 'currency', 'min_amount', 'max_amount', 'total_fee', 'system_fee', 'agent_fee', 'active', 'created_at')
    list_filter = ('currency', 'active', 'created_at')
    search_fields = ('description',)
    readonly_fields = ('created_at', 'updated_at')

@admin.register(TransferReceipt)
class TransferReceiptAdmin(admin.ModelAdmin):
    list_display = ('receipt_number', 'transfer', 'user', 'role', 'created_at')
    list_filter = ('role', 'created_at')
    search_fields = ('receipt_number', 'user__username', 'transfer__transaction_id')
    readonly_fields = ('created_at',)

@admin.register(TransferLog)
class TransferLogAdmin(admin.ModelAdmin):
    list_display = ('transfer', 'action', 'actor', 'created_at')
    list_filter = ('action', 'created_at')
    search_fields = ('transfer__transaction_id', 'actor__username', 'details')
    readonly_fields = ('created_at',)

@admin.register(TransferNotification)
class TransferNotificationAdmin(admin.ModelAdmin):
    list_display = ('transfer', 'recipient', 'title', 'status', 'sent_at', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('transfer__transaction_id', 'recipient__username', 'title')
    readonly_fields = ('created_at', 'sent_at')

class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    verbose_name_plural = 'Profil'
    fk_name = 'user'
    fields = ('address', 'phone', 'photo', 'withdrawal_pin', 'withdrawal_code', 'delivery_access_granted', 'delivery_access_requested')

@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'address', 'withdrawal_pin', 'withdrawal_code', 'delivery_access_granted', 'user_roles')
    list_filter = ('delivery_access_granted', 'delivery_access_requested')
    search_fields = ('user__username', 'address', 'user__email')
    actions = ['regenerate_withdrawal_codes', 'generate_missing_codes']
    readonly_fields = ('user',)
    
    fieldsets = (
        ('Informations utilisateur', {
            'fields': ('user',)
        }),
        ('Données personnelles', {
            'fields': ('address', 'phone', 'photo', 'receipt_proof')
        }),
        ('Codes de retrait', {
            'fields': ('withdrawal_pin', 'withdrawal_code'),
            'description': 'Codes visibles pour les retraits (PIN: 8 chiffres, Code: 4 chiffres)'
        }),
        ('Accès livreur', {
            'fields': ('delivery_access_granted', 'delivery_access_requested')
        }),
    )

    def user_roles(self, obj):
        roles = []
        if obj.user.is_buyer:
            roles.append('Acheteur')
        if obj.user.is_seller:
            roles.append('Vendeur')
        if obj.user.is_delivery_agent:
            roles.append('Livreur')
        if obj.user.is_agent:
            roles.append('Agent')
        return ', '.join(roles)
    user_roles.short_description = 'Rôles utilisateur'

    def regenerate_withdrawal_codes(self, request, queryset):
        """Régénère les codes de retrait pour les profils sélectionnés"""
        if not (request.user.is_staff and (request.user.is_superuser or request.user.role in ['super_admin', 'admin_secondary'])):
            self.message_user(request, 'Vous n\'avez pas la permission pour régénérer les codes.', level=messages.ERROR)
            return
        
        count = 0
        for profile in queryset:
            profile.withdrawal_pin = profile._generate_withdrawal_pin()
            profile.withdrawal_code = profile._generate_withdrawal_code()
            profile.save()
            count += 1
        
        self.message_user(request, f'{count} codes de retrait ont été régénérés avec succès.')
    regenerate_withdrawal_codes.short_description = '🔄 Régénérer les codes de retrait'

    def generate_missing_codes(self, request, queryset):
        """Génère les codes manquants pour les profils sélectionnés"""
        if not (request.user.is_staff and (request.user.is_superuser or request.user.role in ['super_admin', 'admin_secondary'])):
            self.message_user(request, 'Vous n\'avez pas la permission pour générer les codes.', level=messages.ERROR)
            return
        
        count = 0
        for profile in queryset:
            modified = False
            if not profile.withdrawal_pin:
                profile.withdrawal_pin = profile._generate_withdrawal_pin()
                modified = True
            if not profile.withdrawal_code:
                profile.withdrawal_code = profile._generate_withdrawal_code()
                modified = True
            if modified:
                profile.save()
                count += 1
        
        self.message_user(request, f'{count} profils ont reçu leurs codes de retrait manquants.')
    generate_missing_codes.short_description = '✨ Générer les codes manquants'

    def has_change_permission(self, request, obj=None):
        """Vérifie que l'utilisateur est admin pour modifier"""
        return request.user.is_staff and (request.user.is_superuser or request.user.role in ['super_admin', 'admin_secondary'])

    def get_queryset(self, request):
        """L'admin secondaire ne peut voir que les profils des utilisateurs normaux"""
        qs = super().get_queryset(request)
        if request.user.is_staff and not request.user.is_superuser and request.user.role == 'admin_secondary':
            # L'admin secondaire ne peut voir que les profils des utilisateurs normaux (pas d'autres admins)
            from django.db.models import Q
            qs = qs.filter(
                Q(user__is_staff=False) | 
                Q(user__role__in=['buyer_seller', 'delivery_employee', 'agent'])
            )
        return qs


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'instructor', 'next_session', 'is_published', 'created_at')
    list_filter = ('is_published', 'instructor')
    search_fields = ('title', 'description', 'instructor')
    prepopulated_fields = {'slug': ('title',)}


@admin.register(CourseAssignment)
class CourseAssignmentAdmin(admin.ModelAdmin):
    list_display = ('title', 'course', 'due_date', 'status', 'created_at')
    list_filter = ('status', 'course')
    search_fields = ('title', 'course__title', 'description')


@admin.register(AssignmentSubmission)
class AssignmentSubmissionAdmin(admin.ModelAdmin):
    list_display = ('assignment', 'user', 'status', 'submitted_at', 'updated_at')
    list_filter = ('status', 'submitted_at')
    search_fields = ('assignment__title', 'user__username', 'comments')
    readonly_fields = ('submitted_at', 'updated_at')


@admin.register(CourseCertificate)
class CourseCertificateAdmin(admin.ModelAdmin):
    list_display = ('title', 'course', 'user', 'status', 'issued_date', 'created_at')
    list_filter = ('status', 'issued_date', 'course')
    search_fields = ('title', 'course__title', 'user__username')


@admin.register(PrivateConversation)
class PrivateConversationAdmin(admin.ModelAdmin):
    list_display = ('id', 'user1', 'user2', 'created_at', 'updated_at')
    search_fields = ('user1__username', 'user2__username')


@admin.register(PrivateMessage)
class PrivateMessageAdmin(admin.ModelAdmin):
    list_display = ('id', 'conversation', 'sender', 'receiver', 'created_at', 'is_read')
    list_filter = ('is_read', 'created_at')
    search_fields = ('sender__username', 'receiver__username', 'conversation__id', 'content')
    actions = ['grant_delivery_access', 'revoke_delivery_access']

    def user_roles(self, obj):
        roles = []
        if obj.user.is_buyer:
            roles.append('Acheteur')
        if obj.user.is_seller:
            roles.append('Vendeur')
        if obj.user.is_delivery_agent:
            roles.append('Livreur')
        if obj.user.is_agent:
            roles.append('Agent')
        return ', '.join(roles)
    user_roles.short_description = 'Rôles'

    def grant_delivery_access(self, request, queryset):
        for profile in queryset:
            profile.delivery_access_granted = True
            profile.delivery_access_requested = False  # Reset request
            profile.user.is_delivery_agent = True
            profile.user.save()
            profile.save()
            if not DeliveryEmployee.objects.filter(user=profile.user).exists():
                DeliveryEmployee.objects.create(
                    user=profile.user,
                    identifier=f"EMP{profile.user.id}",
                    assigned_zone=profile.user.zone or "Zone par défaut"
                )
        self.message_user(request, 'Accès livreur accordé aux profils sélectionnés.')
    grant_delivery_access.short_description = 'Accorder l’accès livreur'

    def revoke_delivery_access(self, request, queryset):
        for profile in queryset:
            profile.delivery_access_granted = False
            profile.user.is_delivery_agent = False
            profile.user.save()
            profile.save()
        self.message_user(request, 'Accès livreur révoqué pour les profils sélectionnés.')
    revoke_delivery_access.short_description = 'Révoquer l’accès livreur'

@admin.register(BeautyAppointment)
class BeautyAppointmentAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'product', 'booking_type', 'scheduled_date', 'scheduled_time', 'status', 'payment_confirmed')
    list_filter = ('booking_type', 'status', 'payment_confirmed', 'scheduled_date')
    search_fields = ('user__username', 'product__name', 'address', 'instructions')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Réservation Beauté', {
            'fields': ('user', 'product', 'booking_type', 'scheduled_date', 'scheduled_time', 'address', 'instructions', 'technician', 'status', 'payment_confirmed')
        }),
        ('Suivi', {
            'fields': ('created_at', 'updated_at',)
        }),
    )

@admin.register(BeautyStudioRequest)
class BeautyStudioRequestAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'studio_name', 'status', 'created_at', 'approved_at')
    list_filter = ('status', 'created_at', 'approved_at')
    search_fields = ('user__username', 'studio_name', 'phone', 'address', 'specialties')
    readonly_fields = ('created_at', 'updated_at', 'approved_at', 'approved_by')
    fieldsets = (
        ('Demande Studio Beauté', {
            'fields': ('user', 'studio_name', 'description', 'phone', 'address', 'specialties', 'status')
        }),
        ('Approbation', {
            'fields': ('approved_shop', 'approved_by', 'approved_at')
        }),
        ('Suivi', {
            'fields': ('created_at', 'updated_at')
        }),
    )
    
    def save_model(self, request, obj, form, change):
        # Si le statut passe à 'approved', créer/lier le shop
        if obj.status == 'approved' and obj.approved_by is None:
            obj.approve(request.user)
        super().save_model(request, obj, form, change)


@admin.register(TechnicianProfile)
class TechnicianProfileAdmin(admin.ModelAdmin):
    list_display = ('id', 'company_name', 'contact_name', 'phone', 'email', 'city_region', 'is_published', 'created_at')
    list_filter = ('is_published', 'city_region', 'created_at')
    search_fields = ('company_name', 'contact_name', 'phone', 'email', 'services', 'city_region')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Profil Technicien', {
            'fields': (
                'user', 'company_name', 'contact_name', 'phone', 'email', 'city_region', 'address',
                'description', 'services', 'references', 'website', 'whatsapp', 'facebook', 'logo',
                'photo_1', 'photo_1_desc', 'photo_2', 'photo_2_desc', 'photo_3', 'photo_3_desc',
                'photo_4', 'photo_4_desc', 'photo_5', 'photo_5_desc', 'is_published'
            )
        }),
        ('Suivi', {
            'fields': ('created_at', 'updated_at')
        }),
    )

@admin.register(ExchangeRate)
class ExchangeRateAdmin(admin.ModelAdmin):
    list_display = ('usd_to_htg', 'usd_to_peso', 'htg_to_peso', 'created_at', 'is_active')
    list_filter = ('is_active', 'created_at')
    ordering = ('-created_at',)
    readonly_fields = ('created_at',)
    change_list_template = 'admin/marketplace/exchangerate/change_list.html'
    change_form_template = 'admin/marketplace/exchangerate/change_form.html'
    actions = ['refresh_exchange_rates']

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('refresh-rates/', self.admin_site.admin_view(self.refresh_rates_view), name='marketplace_exchangerate_refresh_rates'),
        ]
        return custom_urls + urls

    def refresh_rates_view(self, request):
        rate = fetch_exchange_rates_from_api()
        if rate:
            messages.success(request, f'Taux de change mis à jour automatiquement (UTC {rate.created_at:%Y-%m-%d %H:%M}).')
        else:
            messages.error(request, 'Impossible de récupérer les taux de change depuis l’API. Le système utilisera les taux existants ou les taux fixes.')
        return redirect('admin:marketplace_exchangerate_changelist')

    def refresh_exchange_rates(self, request, queryset):
        rate = fetch_exchange_rates_from_api()
        if rate:
            messages.success(request, 'Taux de change rafraîchis avec succès.')
        else:
            messages.error(request, 'Impossible de rafraîchir les taux de change.')

    refresh_exchange_rates.short_description = '🔄 Rafraîchir les taux de change'


@admin.register(ActivityMenuItem)
class ActivityMenuItemAdmin(admin.ModelAdmin):
    list_display = ('title', 'url', 'is_active', 'order')
    list_editable = ('is_active', 'order')
    search_fields = ('title', 'description', 'url', 'icon_class')
    ordering = ('order', 'title')


@admin.register(TiKanePlan)
class TiKanePlanAdmin(admin.ModelAdmin):
    list_display = ('name', 'duration_days', 'commission_fixed', 'commission_variable', 'bonus_rate', 'active')
    list_editable = ('active',)
    search_fields = ('name',)
    ordering = ('duration_days', 'name')


@admin.register(TiKaneAccessRequest)
class TiKaneAccessRequestAdmin(admin.ModelAdmin):
    list_display = ('user', 'full_name', 'status', 'plan', 'requested_at', 'reviewed_at')
    list_filter = ('status', 'plan', 'requested_at')
    search_fields = ('user__username', 'full_name', 'email', 'phone')
    readonly_fields = ('requested_at', 'reviewed_at', 'account_number', 'tikaned_id')


@admin.register(TiKaneAccount)
class TiKaneAccountAdmin(admin.ModelAdmin):
    list_display = ('account_number', 'user', 'plan', 'status', 'balance', 'total_deposits', 'total_withdrawals')
    list_filter = ('status', 'plan')
    search_fields = ('account_number', 'user__username', 'unique_identifier')
    readonly_fields = ('account_number', 'unique_identifier', 'opened_at', 'created_at', 'updated_at')


@admin.register(TiKaneDailyPayment)
class TiKaneDailyPaymentAdmin(admin.ModelAdmin):
    list_display = ('account', 'day_number', 'status', 'paid', 'paid_at', 'deposit')
    list_filter = ('status', 'paid', 'account__plan')
    search_fields = ('account__account_number', 'account__user__username')
    ordering = ('account', 'day_number')


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ('user', 'balance', 'balance_usd', 'balance_htg', 'balance_peso', 'can_transfer', 'is_blocked')
    list_filter = ('can_transfer', 'is_blocked')
    search_fields = ('user__username',)
    readonly_fields = ('user',)
    actions = ['block_wallet', 'unblock_wallet', 'enable_transfer', 'disable_transfer']

    def block_wallet(self, request, queryset):
        queryset.update(is_blocked=True)
        self.message_user(request, 'Portefeuilles bloqués.')
    block_wallet.short_description = 'Bloquer les portefeuilles'

    def unblock_wallet(self, request, queryset):
        queryset.update(is_blocked=False)
        self.message_user(request, 'Portefeuilles débloqués.')
    unblock_wallet.short_description = 'Débloquer les portefeuilles'

    def enable_transfer(self, request, queryset):
        queryset.update(can_transfer=True)
        self.message_user(request, 'Transferts activés.')
    enable_transfer.short_description = 'Activer les transferts'

    def disable_transfer(self, request, queryset):
        queryset.update(can_transfer=False)
        self.message_user(request, 'Transferts désactivés.')
    disable_transfer.short_description = 'Désactiver les transferts'

class UserAdminForm(forms.ModelForm):
    temp_pin = forms.CharField(
        label='Code PIN (8 chiffres)',
        max_length=8,
        required=False,
        help_text='Entrez un nouveau code PIN de 8 chiffres pour l\'utilisateur. Laissez vide pour ne pas changer.',
        widget=forms.PasswordInput()
    )
    temp_otp = forms.CharField(
        label='Code sécurisé (4 chiffres)',
        max_length=4,
        required=False,
        help_text='Entrez un nouveau code sécurisé de 4 chiffres. Laissez vide pour ne pas changer.',
        widget=forms.PasswordInput()
    )

    class Meta:
        model = User
        fields = '__all__'

    def save(self, commit=True):
        user = super().save(commit=False)
        temp_pin = self.cleaned_data.get('temp_pin')
        temp_otp = self.cleaned_data.get('temp_otp')
        if temp_pin:
            if len(temp_pin) == 8 and temp_pin.isdigit():
                user.set_security_pin(temp_pin)
            else:
                raise forms.ValidationError('Le code PIN doit être exactement 8 chiffres.')
        if temp_otp:
            if len(temp_otp) == 4 and temp_otp.isdigit():
                user.set_otp_code(temp_otp)
            else:
                raise forms.ValidationError('Le code sécurisé doit être exactement 4 chiffres.')
        if commit:
            user.save()
            if temp_pin or temp_otp:
                profile, _ = Profile.objects.get_or_create(user=user)
                if temp_pin:
                    profile.withdrawal_pin = temp_pin
                if temp_otp:
                    profile.withdrawal_code = temp_otp
                profile.save()
        return user

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    form = UserAdminForm
    inlines = [ProfileInline]
    list_display = ('username', 'first_name', 'last_name', 'email', 'account_code', 'role', 'is_buyer', 'is_seller', 'is_delivery_agent', 'is_agent', 'is_staff')
    list_filter = ('role', 'is_buyer', 'is_seller', 'is_delivery_agent', 'is_agent', 'is_staff')
    search_fields = ('username', 'first_name', 'last_name', 'email', 'account_code')
    readonly_fields = ('date_joined', 'last_login')

    fieldsets = (
        ('Informations personnelles', {
            'fields': ('username', 'first_name', 'last_name', 'email', 'password')
        }),
        ('Rôles et permissions', {
            'fields': ('role', 'is_buyer', 'is_seller', 'is_delivery_agent', 'can_request_delivery', 'is_agent', 'is_staff', 'is_superuser', 'groups', 'user_permissions')
        }),
        ('Sécurité pour retraits', {
            'fields': ('temp_pin', 'temp_otp', 'failed_withdrawal_attempts', 'withdrawal_blocked_until', 'otp_expires_at'),
            'classes': ('collapse',)
        }),
        ('Informations temporelles', {
            'fields': ('date_joined', 'last_login')
        }),
    )

admin.site.register(Shop)

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'shop', 'price_ht', 'quantity', 'get_image_status', 'get_banner_status', 'created_at')
    list_filter = ('shop', 'category', 'created_at', 'banner_display_allowed', 'banner_blocked_by_admin')
    search_fields = ('name', 'description', 'shop__name')
    readonly_fields = ('created_at', 'banner_blocked_by_admin', 'banner_blocked_at')
    
    fieldsets = (
        ('Informations générales', {
            'fields': ('shop', 'category', 'name', 'description')
        }),
        ('Prix et stock', {
            'fields': ('price_ht', 'quantity')
        }),
        ('Dimensions et poids', {
            'fields': ('largeur', 'hauteur', 'longueur', 'poids')
        }),
        ('Images', {
            'fields': ('image', 'custom_image')
        }),
        ('Contrôle d\'affichage en bannière', {
            'fields': ('banner_display_allowed', 'banner_blocked_by_admin', 'banner_blocked_at', 'banner_block_reason'),
            'description': 'Contrôlez si ce produit peut apparaître dans le carrousel de la bannière. '
                          'Seuls les produits avec une image valide et non bloqués seront affichés.'
        }),
        ('Informations temporelles', {
            'fields': ('created_at',)
        }),
    )
    
    actions = ['block_from_banner', 'unblock_from_banner', 'allow_banner_display']
    
    def get_image_status(self, obj):
        """Affiche le statut de l'image du produit"""
        if obj.has_valid_image():
            return '✅ Image valide'
        return '❌ Pas d\'image'
    get_image_status.short_description = 'Image'
    
    def get_banner_status(self, obj):
        """Affiche le statut d'affichage en bannière"""
        if obj.banner_blocked_by_admin:
            return f'🚫 Bloqué par {obj.banner_blocked_by_admin.username}'
        if not obj.banner_display_allowed:
            return '⏸️ Désactivé'
        if obj.has_valid_image():
            return '✅ Éligible'
        return '⚠️ Pas d\'image'
    get_banner_status.short_description = 'Statut Bannière'
    
    def block_from_banner(self, request, queryset):
        """Action pour bloquer des produits du carrousel"""
        if not request.user.is_staff or not request.user.is_superuser:
            self.message_user(request, 'Vous n\'avez pas la permission de bloquer des produits.', level=messages.ERROR)
            return
        
        now = timezone.now()
        count = 0
        for product in queryset:
            if not product.banner_blocked_by_admin:
                product.banner_blocked_by_admin = request.user
                product.banner_blocked_at = now
                product.banner_display_allowed = False
                product.save()
                count += 1
        
        if count > 0:
            self.message_user(request, f'✅ {count} produit(s) bloqué(s) de la bannière.', level=messages.SUCCESS)
        else:
            self.message_user(request, 'Aucun produit n\'a été bloqué (certains étaient déjà bloqués).', level=messages.WARNING)
    block_from_banner.short_description = '🚫 Bloquer de la bannière'
    
    def unblock_from_banner(self, request, queryset):
        """Action pour débloquer des produits du carrousel"""
        if not request.user.is_staff or not request.user.is_superuser:
            self.message_user(request, 'Vous n\'avez pas la permission de débloquer des produits.', level=messages.ERROR)
            return
        
        count = 0
        for product in queryset:
            if product.banner_blocked_by_admin:
                product.banner_blocked_by_admin = None
                product.banner_blocked_at = None
                product.banner_block_reason = ''
                product.banner_display_allowed = True
                product.save()
                count += 1
        
        if count > 0:
            self.message_user(request, f'✅ {count} produit(s) débloqué(s) de la bannière.', level=messages.SUCCESS)
        else:
            self.message_user(request, 'Aucun produit n\'a été débloqué (certains ne sont pas bloqués).', level=messages.WARNING)
    unblock_from_banner.short_description = '✅ Débloquer de la bannière'
    
    def allow_banner_display(self, request, queryset):
        """Action pour autoriser l'affichage en bannière"""
        if not request.user.is_staff or not request.user.is_superuser:
            self.message_user(request, 'Vous n\'avez pas la permission d\'autoriser des produits.', level=messages.ERROR)
            return
        
        count = queryset.update(banner_display_allowed=True)
        if count > 0:
            self.message_user(request, f'✅ {count} produit(s) autorisé(s) pour la bannière.', level=messages.SUCCESS)
    allow_banner_display.short_description = '✅ Autoriser pour la bannière'

@admin.register(ProductReview)
class ProductReviewAdmin(admin.ModelAdmin):
    list_display = ('product', 'user', 'rating', 'is_approved', 'created_at')
    list_filter = ('is_approved', 'rating', 'created_at')
    search_fields = ('product__name', 'user__username', 'comment')

@admin.register(ProductAccessRequest)
class ProductAccessRequestAdmin(admin.ModelAdmin):
    list_display = ('id', 'seller', 'product', 'owner_shop', 'status', 'commission_type', 'commission_value', 'created_at')
    list_filter = ('status', 'created_at', 'commission_type')
    search_fields = ('seller__username', 'product__name', 'owner_shop__name')
    actions = ['approve_requests', 'reject_requests']

    def approve_requests(self, request, queryset):
        selected = request.POST.getlist(admin.ACTION_CHECKBOX_NAME)
        if not selected:
            self.message_user(request, 'Aucune demande sélectionnée.', level=messages.WARNING)
            return
        ids = ','.join(selected)
        return redirect(f'./approve-requests-form/?ids={ids}')
    approve_requests.short_description = 'Approuver les demandes sélectionnées (avec commission)'

    def reject_requests(self, request, queryset):
        count = queryset.filter(status='pending').update(status='rejected')
        self.message_user(request, f'{count} demande(s) refusée(s).')
    reject_requests.short_description = 'Refuser les demandes sélectionnées'

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path('approve-requests-form/', self.admin_site.admin_view(self.approve_requests_form), name='marketplace_productaccessrequest_approve_form'),
        ]
        return custom_urls + urls

    def approve_requests_form(self, request):
        from django.template.response import TemplateResponse
        if request.method == 'POST':
            ids = request.POST.get('ids', '')
            commission_type = request.POST.get('commission_type')
            commission_value = request.POST.get('commission_value') or None
            id_list = [int(i) for i in ids.split(',') if i]
            qs = ProductAccessRequest.objects.filter(id__in=id_list, status='pending')
            settings = MarketplaceSettings.get_solo()
            approved = 0
            skipped = 0
            for req in qs:
                active_product_copies = ResellerProduct.objects.filter(original_product=req.product, status='active').count()
                active_seller_copies = ResellerProduct.objects.filter(seller=req.seller, status='active').count()
                if active_product_copies >= settings.get_copy_limit() or active_seller_copies >= settings.get_max_active_copies_for_seller():
                    req.status = 'rejected'
                    req.save()
                    skipped += 1
                    continue

                req.status = 'approved'
                req.commission_type = commission_type
                if commission_value:
                    try:
                        req.commission_value = Decimal(commission_value)
                    except Exception:
                        req.commission_value = None
                seller_commission_type, seller_commission_value = settings.get_seller_commission(req.seller)
                if not req.commission_value:
                    req.commission_type = seller_commission_type
                    req.commission_value = seller_commission_value
                req.save()
                rp, created = ResellerProduct.objects.get_or_create(
                    seller=req.seller,
                    original_product=req.product,
                    defaults={
                        'commission_type': req.commission_type,
                        'commission_value': req.commission_value
                    }
                )
                # Si aucune copie locale n'existe, en créer une dans la boutique du revendeur
                if not rp.copied_product:
                    new_prod = req.product.create_copy_for_reseller(req.seller)
                    rp.copied_product = new_prod
                    rp.save()
                approved += 1
            message = f'{approved} demande(s) approuvée(s) avec commission.'
            if skipped:
                message += f' {skipped} demande(s) rejetée(s) car les limites de copies ont été atteintes.'
            self.message_user(request, message)
            return redirect('admin:marketplace_productaccessrequest_changelist')

        ids = request.GET.get('ids', '')
        id_list = [int(i) for i in ids.split(',') if i]
        qs = ProductAccessRequest.objects.filter(id__in=id_list)
        context = dict(
            self.admin_site.each_context(request),
            requests=qs,
            ids=ids,
        )
        return TemplateResponse(request, 'admin/marketplace/approve_requests_form.html', context)


@admin.register(ResellerProduct)
class ResellerProductAdmin(admin.ModelAdmin):
    list_display = ('id', 'seller', 'original_product', 'commission_type', 'commission_value', 'custom_price', 'status', 'created_at')
    list_filter = ('status', 'commission_type', 'created_at')
    search_fields = ('seller__username', 'original_product__name')


@admin.register(MarketplaceSellerCommission)
class MarketplaceSellerCommissionAdmin(admin.ModelAdmin):
    list_display = ('seller', 'commission_type', 'commission_value', 'is_active', 'created_at')
    list_filter = ('commission_type', 'is_active', 'created_at')
    search_fields = ('seller__username',)


@admin.register(MarketplaceSettings)
class MarketplaceSettingsAdmin(admin.ModelAdmin):
    list_display = (
        'default_commission_type', 'default_commission_value', 'validation_required',
        'allow_auto_copy', 'copy_limit_per_product', 'max_active_copies_per_seller',
        'enable_real_estate_auto_loan', 'real_estate_membership_fee_htg'
    )
    readonly_fields = ('created_at',)
    fieldsets = (
        ('Commission standard', {
            'fields': ('default_commission_type', 'default_commission_value')
        }),
        ('Marketplace', {
            'fields': ('validation_required', 'allow_auto_copy', 'copy_limit_per_product', 'max_active_copies_per_seller')
        }),
        ('Immobilier', {
            'fields': ('enable_real_estate_auto_loan', 'real_estate_membership_fee_htg')
        }),
        ('Informations système', {
            'fields': ('created_at',)
        }),
    )

    def has_add_permission(self, request):
        if MarketplaceSettings.objects.exists():
            return False
        return super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        obj.pk = 1
        super().save_model(request, obj, form, change)

    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser or request.user.has_perm('marketplace.principal_admin_power')

    def has_change_permission(self, request, obj=None):
        return self.has_view_permission(request, obj)

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('id', 'buyer', 'total_amount', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    actions = ['refund_order']

    def refund_order(self, request, queryset):
        for order in queryset:
            if order.status in ['paid', 'awaiting_delivery', 'delivered']:
                # Refund buyer
                buyer_wallet = Wallet.objects.get(user=order.buyer)
                buyer_wallet.balance += order.total_amount
                buyer_wallet.save()
                # If already paid to seller, deduct back? But in escrow, if not delivered, deduct.
                if order.status == 'delivered':
                    for item in order.items.all():
                        seller_wallet = Wallet.objects.get(user=item.product.shop.owner)
                        seller_revenue = (item.price_ht - Decimal('0.6')) * item.quantity
                        seller_wallet.balance -= seller_revenue
                        seller_wallet.save()
                order.status = 'refunded'
                order.save()
                Transaction.objects.create(
                    sender=None,
                    receiver=order.buyer,
                    amount=order.total_amount,
                    type='refund',
                    status='approved'
                )
                AuditLog.objects.create(
                    user=order.buyer,
                    action='order_refund',
                    details=f'Commande #{order.id} remboursée par admin {request.user.username}',
                )
        self.message_user(request, f'Remboursement effectué pour {queryset.count()} commande(s).')
    refund_order.short_description = 'Rembourser les commandes sélectionnées'
admin.site.register(OrderItem)
admin.site.register(DeliveryEmployee)
admin.site.register(DeliveryAssignment)
admin.site.register(DeliveryTracking)
admin.site.register(DeliveryNotification)
admin.site.register(ReturnRequest)

@admin.register(Agent)
class AgentAdmin(admin.ModelAdmin):
    list_display = ('user', 'is_active')
    list_filter = ('is_active',)
    search_fields = ('user__username', 'user__email')
    actions = ['activate_agents', 'deactivate_agents']

    def activate_agents(self, request, queryset):
        for agent in queryset:
            agent.is_active = True
            agent.save()
            agent.user.is_agent = True
            agent.user.save(update_fields=['is_agent'])
        self.message_user(request, 'Agents sélectionnés activés.')
    activate_agents.short_description = 'Activer les agents sélectionnés'

    def deactivate_agents(self, request, queryset):
        for agent in queryset:
            agent.is_active = False
            agent.save()
            agent.user.is_agent = False
            agent.user.save(update_fields=['is_agent'])
        self.message_user(request, 'Agents sélectionnés désactivés.')
    deactivate_agents.short_description = 'Désactiver les agents sélectionnés'

from .models import ChatGroup, ChatMessage

@admin.register(ChatGroup)
class ChatGroupAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_global', 'created_at')
    search_fields = ('name', 'slug')
    filter_horizontal = ('participants',)

@admin.register(SecurityIncident)
class SecurityIncidentAdmin(admin.ModelAdmin):
    list_display = ('incident_type', 'severity', 'source_ip', 'created_at', 'resolved')
    list_filter = ('incident_type', 'severity', 'resolved', 'created_at')
    search_fields = ('description', 'source_ip')

@admin.register(SecurityEvent)
class SecurityEventAdmin(admin.ModelAdmin):
    list_display = ('event_type', 'source_ip', 'status_code', 'method', 'path', 'created_at')
    list_filter = ('event_type', 'method', 'status_code', 'created_at')
    search_fields = ('source_ip', 'path', 'user_agent')
    readonly_fields = ('created_at',)

@admin.register(IPBlocklist)
class IPBlocklistAdmin(admin.ModelAdmin):
    list_display = ('ip_address', 'reason')
    list_filter = ()
    search_fields = ('ip_address', 'reason')

# ==========================================
# ADMIN POUR LE SYSTÈME CYBERSÉCURITÉ INTELLIGENT
# ==========================================

@admin.register(PortMonitoring)
class PortMonitoringAdmin(admin.ModelAdmin):
    list_display = ('port', 'is_open', 'traffic_count', 'risk_level', 'suspicious_activity', 'last_scan')
    list_filter = ('is_open', 'risk_level', 'suspicious_activity')
    search_fields = ('port',)
    readonly_fields = ('last_scan',)
    list_editable = ('is_open', 'risk_level')

@admin.register(AIThreatAnalysis)
class AIThreatAnalysisAdmin(admin.ModelAdmin):
    list_display = ('threat_score', 'threat_level', 'bot_detections', 'brute_force_attempts', 'ai_confidence', 'last_analysis')
    list_filter = ('threat_level', 'last_analysis')
    readonly_fields = ('last_analysis', 'detected_anomalies', 'suspicious_patterns')

@admin.register(HoneypotEvent)
class HoneypotEventAdmin(admin.ModelAdmin):
    list_display = ('event_type', 'source_ip', 'attempted_username', 'created_at', 'alerted')
    list_filter = ('event_type', 'alerted', 'created_at')
    search_fields = ('source_ip', 'attempted_username', 'payload')
    readonly_fields = ('created_at', 'device_info', 'geolocation')

@admin.register(SecurityAlert)
class SecurityAlertAdmin(admin.ModelAdmin):
    list_display = ('alert_type', 'priority', 'title', 'source_ip', 'resolved', 'created_at')
    list_filter = ('alert_type', 'priority', 'resolved', 'created_at')
    search_fields = ('title', 'description', 'source_ip')
    readonly_fields = ('created_at', 'resolved_at')
    list_editable = ('resolved',)

@admin.register(SecurityLog)
class SecurityLogAdmin(admin.ModelAdmin):
    list_display = ('level', 'component', 'message', 'source_ip', 'user', 'created_at')
    list_filter = ('level', 'component', 'created_at')
    search_fields = ('message', 'source_ip', 'user__username')
    readonly_fields = ('created_at', 'metadata')

@admin.register(SecurityMetrics)
class SecurityMetricsAdmin(admin.ModelAdmin):
    list_display = ('timestamp', 'active_connections', 'requests_per_minute', 'ai_threat_score', 'active_alerts')
    list_filter = ('timestamp',)
    readonly_fields = ('timestamp',)

@admin.register(AntiBotField)
class AntiBotFieldAdmin(admin.ModelAdmin):
    list_display = ('form_name', 'field_name', 'is_visible', 'blocked_submissions', 'updated_at')
    list_filter = ('form_name', 'is_visible')
    search_fields = ('form_name', 'field_name')
    list_editable = ('is_visible',)

@admin.register(AntiBotDetection)
class AntiBotDetectionAdmin(admin.ModelAdmin):
    list_display = ('field', 'source_ip', 'submitted_value', 'blocked', 'created_at')
    list_filter = ('blocked', 'created_at', 'field__form_name')
    search_fields = ('source_ip', 'submitted_value')
    readonly_fields = ('created_at', 'form_data')

@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ('group', 'sender', 'created_at', 'is_system', 'is_advertisement')
    list_filter = ('is_system', 'is_advertisement', 'created_at')
    search_fields = ('content', 'sender__username', 'group__name')

@admin.register(SiteConfiguration)
class SiteConfigurationAdmin(admin.ModelAdmin):
    list_display = ('config_type', 'alt_text', 'image', 'updated_by', 'updated_at')
    readonly_fields = ('config_type', 'updated_at', 'updated_by')
    fields = ('config_type', 'image', 'alt_text', 'width', 'height', 'updated_at', 'updated_by')

    def save_model(self, request, obj, form, change):
        if change:
            obj.updated_by = request.user
        super().save_model(request, obj, form, change)

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        # Superutilisateur ou utilisateur avec permission
        if request.user.is_superuser:
            return True
        try:
            perm = request.user.logo_permission
            return perm.can_edit_logos
        except:
            return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if not request.user.is_superuser:
            # Les non-superutilisateurs ne voient que les configs s'ils ont permission
            try:
                perm = request.user.logo_permission
                if not perm.can_edit_logos:
                    qs = qs.none()
            except:
                qs = qs.none()
        return qs


@admin.register(SiteConfigurationPermission)
class SiteConfigurationPermissionAdmin(admin.ModelAdmin):
    list_display = ('user', 'can_edit_logos', 'granted_by', 'granted_at')
    list_filter = ('can_edit_logos', 'granted_at')
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('granted_at', 'granted_by')
    
    fieldsets = (
        ('Utilisateur', {
            'fields': ('user',)
        }),
        ('Permission', {
            'fields': ('can_edit_logos',)
        }),
        ('Audit', {
            'fields': ('granted_by', 'granted_at'),
            'classes': ('collapse',)
        }),
    )

    def save_model(self, request, obj, form, change):
        if not obj.granted_by:
            obj.granted_by = request.user
        super().save_model(request, obj, form, change)
        
        # Message de confirmation
        if obj.can_edit_logos:
            messages.success(request, f"Permission accordée à {obj.user.username} pour modifier les logos")
        else:
            messages.warning(request, f"Permission retirée à {obj.user.username}")

    def has_add_permission(self, request):
        return request.user.is_superuser

    def has_change_permission(self, request, obj=None):
        return request.user.is_superuser

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser



# ========================
# Configuration des commissions de dépôt
# ========================
@admin.register(DepositCommissionConfig)
class DepositCommissionConfigAdmin(admin.ModelAdmin):
    list_display = ('currency', 'commission_type', 'commission_value', 'min_deposit', 'max_deposit', 'is_active', 'updated_at')
    list_filter = ('currency', 'commission_type', 'is_active')
    list_editable = ('commission_value', 'min_deposit', 'max_deposit', 'is_active')
    readonly_fields = ('created_at', 'updated_at', 'updated_by_display')
    
    fieldsets = (
        ('Configuration Devise', {
            'fields': ('currency',)
        }),
        ('Commission', {
            'fields': ('commission_type', 'commission_value')
        }),
        ('Limites Depot', {
            'fields': ('min_deposit', 'max_deposit')
        }),
        ('Statut', {
            'fields': ('is_active',)
        }),
        ('Audit', {
            'fields': ('created_at', 'updated_at', 'updated_by', 'updated_by_display'),
            'classes': ('collapse',)
        }),
    )
    
    def updated_by_display(self, obj):
        return obj.updated_by.username if obj.updated_by else 'N/A'
    updated_by_display.short_description = 'Modifie par'
    
    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(AgentCommission)
class AgentCommissionAdmin(admin.ModelAdmin):
    list_display = ('agent', 'deposit', 'commission_amount', 'source_account', 'credited', 'created_at')
    list_filter = ('credited', 'created_at')
    search_fields = ('agent__username', 'deposit__reference')
    readonly_fields = ('agent', 'deposit', 'commission_amount', 'source_account', 'credited', 'created_at')


@admin.register(WithdrawalCommissionTier)
class WithdrawalCommissionTierAdmin(admin.ModelAdmin):
    list_display = ('currency', 'min_amount', 'max_amount', 'total_fee', 'system_fee', 'agent_fee', 'active', 'created_at')
    list_filter = ('currency', 'active', 'created_at')
    search_fields = ('currency', 'description',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(WithdrawalTransaction)
class WithdrawalTransactionAdmin(admin.ModelAdmin):
    list_display = ('withdrawal_request', 'user', 'agent', 'amount', 'currency', 'fee_total', 'fee_system', 'fee_agent', 'status', 'created_at')
    list_filter = ('currency', 'status', 'created_at')
    search_fields = ('user__username', 'agent__username', 'withdrawal_request__id')
    readonly_fields = ('withdrawal_request', 'user', 'agent', 'amount', 'currency', 'fee_total', 'fee_system', 'fee_agent', 'status', 'created_at')


@admin.register(AdminCommissionLog)
class AdminCommissionLogAdmin(admin.ModelAdmin):
    list_display = ('admin', 'action_type', 'target_name', 'target_type', 'created_at')
    list_filter = ('action_type', 'target_type', 'created_at')
    search_fields = ('admin__username', 'target_name')
    readonly_fields = ('admin', 'action_type', 'target_name', 'target_type', 'old_value', 'new_value', 'ip_address', 'created_at')


@admin.register(CommissionCategory)
class CommissionCategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'is_active', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('name', 'slug')
    readonly_fields = ('created_at',)


@admin.register(UserCommissionCategory)
class UserCommissionCategoryAdmin(admin.ModelAdmin):
    list_display = ('user', 'category', 'assigned_at')
    list_filter = ('category', 'assigned_at')
    search_fields = ('user__username', 'category__name')
    readonly_fields = ('assigned_at',)


@admin.register(CommissionDistributionLog)
class CommissionDistributionLogAdmin(admin.ModelAdmin):
    list_display = ('admin', 'user', 'action', 'amount', 'currency', 'created_at')
    list_filter = ('action', 'currency', 'created_at')
    search_fields = ('admin__username', 'user__username', 'description')
    readonly_fields = ('admin', 'user', 'action', 'amount', 'currency', 'description', 'created_at')


@admin.register(CommissionRule)
class CommissionRuleAdmin(admin.ModelAdmin):
    list_display = ('agent', 'min_amount', 'max_amount', 'commission_amount', 'created_at')
    list_filter = ('agent', 'created_at')
    search_fields = ('agent__username',)


@admin.register(DepositLimit)
class DepositLimitAdmin(admin.ModelAdmin):
    list_display = ('min_amount', 'max_amount', 'daily_limit', 'per_agent_daily_limit', 'updated_at')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(AdminSetting)
class AdminSettingAdmin(admin.ModelAdmin):
    list_display = ('key', 'value', 'updated_at')
    search_fields = ('key', 'value')
    readonly_fields = ('updated_at',)


# ========================
# Depots MicrosDiCash
# ========================
@admin.register(Deposit)
class DepositAdmin(admin.ModelAdmin):
    list_display = ('reference', 'agent_display', 'client', 'amount', 'currency', 'commission', 'status', 'created_at')
    list_filter = ('status', 'currency', 'created_at', 'agent')
    search_fields = ('reference', 'client__username', 'agent__username', 'client__email')
    readonly_fields = ('reference', 'created_at', 'updated_at', 'confirmation_info')
    
    fieldsets = (
        ('Informations Depot', {
            'fields': ('reference', 'agent', 'client', 'status')
        }),
        ('Montants', {
            'fields': ('amount', 'currency', 'commission')
        }),
        ('Confirmation', {
            'fields': ('confirmed_by', 'confirmed_at', 'confirmation_info'),
            'classes': ('collapse',)
        }),
        ('Rejet', {
            'fields': ('rejection_reason',),
            'classes': ('collapse',)
        }),
        ('Audit', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def agent_display(self, obj):
        return obj.agent.username if obj.agent else 'Non assigne'
    agent_display.short_description = 'Agent'
    
    def confirmation_info(self, obj):
        if obj.confirmed_by:
            return "Confirme par {} a {}".format(obj.confirmed_by.username, obj.confirmed_at)
        return "Non confirme"
    confirmation_info.short_description = 'Informations de confirmation'
    
    actions = ['mark_confirmed', 'mark_rejected']
    
    def mark_confirmed(self, request, queryset):
        updated = queryset.filter(status='pending').update(
            status='confirmed',
            confirmed_by=request.user,
            confirmed_at=timezone.now()
        )
        self.message_user(request, "{} depot(s) confirme(s).".format(updated), messages.SUCCESS)
    mark_confirmed.short_description = "Confirmer les depots selectionnes"
    
    def mark_rejected(self, request, queryset):
        updated = queryset.filter(status='pending').update(
            status='rejected'
        )
        self.message_user(request, "{} depot(s) rejete(s).".format(updated), messages.SUCCESS)
    mark_rejected.short_description = "Rejeter les depots selectionnes"


# ==========================================
# MODULE IMMOBILIER - ADMIN
# ==========================================

@admin.register(Property)
class PropertyAdmin(admin.ModelAdmin):
    list_display = ('title', 'city', 'property_type', 'price', 'approval_status', 'created_at')
    list_filter = ('property_type', 'approval_status', 'city')
    search_fields = ('title', 'address', 'city')
    readonly_fields = ('created_at', 'updated_at', 'published_at', 'view_count', 'contact_count')
    fieldsets = (
        ('Informations de base', {'fields': ('title', 'description', 'property_type', 'listing_type', 'status')}),
        ('Localisation', {'fields': ('address', 'city', 'neighborhood', 'country', 'latitude', 'longitude')}),
        ('D�tails du bien', {'fields': ('price', 'currency', 'total_area', 'bedrooms', 'bathrooms', 'has_parking', 'has_garden', 'has_balcony', 'has_gate')}),
        ('Propri�taire', {'fields': ('owner', 'agent')}),
        ('Validation', {'fields': ('approval_status', 'approved_by', 'rejected_reason')}),
        ('M�tadonn�es', {'fields': ('created_at', 'updated_at', 'published_at', 'view_count', 'contact_count'), 'classes': ('collapse',)}),
    )

@admin.register(PropertyImage)
class PropertyImageAdmin(admin.ModelAdmin):
    list_display = ('property', 'image_type', 'order')
    list_filter = ('image_type',)
    search_fields = ('property__title',)

@admin.register(PropertyFavorite)
class PropertyFavoriteAdmin(admin.ModelAdmin):
    list_display = ('user', 'property', 'added_at')
    list_filter = ('added_at',)
    search_fields = ('user__username', 'property__title')
    readonly_fields = ('added_at',)

@admin.register(RealEstateMessage)
class RealEstateMessageAdmin(admin.ModelAdmin):
    list_display = ('sender', 'recipient', 'property', 'is_read', 'created_at')
    list_filter = ('is_read', 'created_at')
    search_fields = ('sender__username', 'recipient__username', 'property__title')
    readonly_fields = ('created_at', 'updated_at', 'read_at')

@admin.register(PropertyReview)
class PropertyReviewAdmin(admin.ModelAdmin):
    list_display = ('user', 'property', 'review_type', 'rating', 'is_approved')
    list_filter = ('review_type', 'is_approved', 'rating')
    search_fields = ('user__username', 'property__title')
    readonly_fields = ('created_at', 'updated_at')

@admin.register(RealEstateNotification)
class RealEstateNotificationAdmin(admin.ModelAdmin):
    list_display = ('user', 'notification_type', 'is_read', 'created_at')
    list_filter = ('notification_type', 'is_read')
    search_fields = ('user__username', 'title')
    readonly_fields = ('created_at', 'read_at')


# ==========================================
# SYSTÈME D'ANNONCES ADMINISTRATIVES
# ==========================================

@admin.register(AdminAnnouncement)
class AdminAnnouncementAdmin(admin.ModelAdmin):
    list_display = ('title', 'status', 'is_priority', 'is_active', 'scroll_speed', 'view_count', 'click_count', 'created_at')
    list_filter = ('status', 'is_priority', 'is_active', 'animation_effect', 'scroll_speed', 'created_at')
    search_fields = ('title', 'message')
    readonly_fields = ('created_at', 'updated_at', 'view_count', 'click_count', 'created_by', 'updated_by')
    
    fieldsets = (
        ('Informations de base', {
            'fields': ('title', 'message', 'icon')
        }),
        ('Status et visibilité', {
            'fields': ('status', 'is_priority', 'is_active')
        }),
        ('Planification', {
            'fields': ('start_date', 'end_date')
        }),
        ('Apparence visuelle', {
            'fields': ('background_color', 'text_color', 'accent_color')
        }),
        ('Animation et défilement', {
            'fields': ('scroll_speed', 'enable_loop', 'animation_effect')
        }),
        ('Métadonnées', {
            'fields': ('created_by', 'created_at', 'updated_by', 'updated_at'),
            'classes': ('collapse',)
        }),
        ('Statistiques', {
            'fields': ('view_count', 'click_count'),
            'classes': ('collapse',)
        }),
    )
    
    actions = ['make_active', 'make_inactive', 'set_priority', 'remove_priority']
    
    def make_active(self, request, queryset):
        updated = queryset.update(status='active', is_active=True)
        self.message_user(request, f"{updated} annonce(s) activée(s).", messages.SUCCESS)
    make_active.short_description = "Activer les annonces sélectionnées"
    
    def make_inactive(self, request, queryset):
        updated = queryset.update(status='inactive', is_active=False)
        self.message_user(request, f"{updated} annonce(s) désactivée(s).", messages.SUCCESS)
    make_inactive.short_description = "Désactiver les annonces sélectionnées"
    
    def set_priority(self, request, queryset):
        updated = queryset.update(is_priority=True)
        self.message_user(request, f"{updated} annonce(s) marquée(s) comme prioritaire(s).", messages.SUCCESS)
    set_priority.short_description = "Marquer comme prioritaire"
    
    def remove_priority(self, request, queryset):
        updated = queryset.update(is_priority=False)
        self.message_user(request, f"{updated} annonce(s) non-prioritaire(s).", messages.SUCCESS)
    remove_priority.short_description = "Retirer de la priorité"
    
    def save_model(self, request, obj, form, change):
        if not change:  # Nouvelle annonce
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(AdminAnnouncementPermission)
class AdminAnnouncementPermissionAdmin(admin.ModelAdmin):
    list_display = ('admin', 'permission_level', 'granted_by', 'granted_at')
    list_filter = ('permission_level', 'granted_at')
    search_fields = ('admin__username', 'granted_by__username')
    readonly_fields = ('granted_at',)
    
    fieldsets = (
        ('Administrateur et permissions', {
            'fields': ('admin', 'permission_level')
        }),
        ('Audit', {
            'fields': ('granted_by', 'granted_at'),
            'classes': ('collapse',)
        }),
    )

