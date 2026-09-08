import uuid
import secrets
import os
from decimal import Decimal
import datetime
from datetime import datetime, timedelta
from django.db import models
from django.utils import timezone
# Ensure timezone.utc is available (some Django versions may not expose it)
try:
    _ = timezone.utc
except Exception:
    import importlib
    timezone.utc = importlib.import_module('datetime').timezone.utc
from django.utils.text import slugify
from django.contrib.auth.models import AbstractUser
from django.contrib.auth.hashers import make_password, check_password
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db.models import JSONField
from django.core.files.storage import default_storage

# -------------------------------
# Utilisateur (acheteur + vendeur + employé livraison)
# -------------------------------
class User(AbstractUser):
    ROLE_CHOICES = (
        ('super_admin', 'Super Admin'),
        ('ai_admin', 'Administrateur IA'),
        ('admin_secondary', 'Admin secondaire'),
        ('support_employee', 'Soutien / employé'),
        ('buyer_seller', 'Acheteur / Vendeur'),
        ('delivery_employee', 'Employé livraison'),
        ('agent', 'Agent'),
    )
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='buyer_seller')
    is_buyer = models.BooleanField(default=True)
    is_seller = models.BooleanField(default=True)
    is_delivery_employee = models.BooleanField(default=False)
    is_delivery_agent = models.BooleanField(default=False)
    can_request_delivery = models.BooleanField(default=True)
    is_agent = models.BooleanField(default=False)  # pour les agents de recharge
    zone = models.CharField(max_length=100, blank=True, null=True)  # zone géographique
    account_code = models.CharField(max_length=20, blank=True, help_text="Code de compte unique")
    # Codes de sécurité
    security_pin = models.CharField(max_length=128, blank=True, null=True, help_text="Code PIN hashé utilisateur")
    otp_code = models.CharField(max_length=128, blank=True, null=True, help_text="Code OTP hashé temporaire")
    display_security_pin = models.CharField(max_length=20, blank=True, null=True, help_text="PIN pour affichage (non-hashé)")
    display_otp_code = models.CharField(max_length=20, blank=True, null=True, help_text="Code OTP pour affichage (non-hashé)")
    failed_withdrawal_attempts = models.IntegerField(default=0, help_text="Tentatives de retrait échouées")
    withdrawal_blocked_until = models.DateTimeField(blank=True, null=True, help_text="Bloqué jusqu'à cette date")
    otp_expires_at = models.DateTimeField(blank=True, null=True, help_text="Expiration du code OTP")

    def set_security_pin(self, pin):
        """Hash et sauvegarde le PIN"""
        self.security_pin = make_password(pin)
        self.display_security_pin = pin  # Sauvegarder aussi la version non-hashée pour affichage
        self.save()

    def check_security_pin(self, pin):
        """Vérifie le PIN"""
        return check_password(pin, self.security_pin) if self.security_pin else False

    def set_otp_code(self, code):
        """Hash et sauvegarde le code OTP"""
        self.otp_code = make_password(code)
        self.display_otp_code = code  # Sauvegarder aussi la version non-hashée pour affichage
        self.save()

    def check_otp_code(self, code):
        """Vérifie le code OTP"""
        return check_password(code, self.otp_code) if self.otp_code else False

    def reset_failed_attempts(self):
        """Remet à zéro les tentatives échouées"""
        self.failed_withdrawal_attempts = 0
        self.withdrawal_blocked_until = None
        self.save()

    def increment_failed_attempts(self):
        """Incrémente les tentatives échouées et bloque si nécessaire"""
        self.failed_withdrawal_attempts += 1
        if self.failed_withdrawal_attempts >= 3:
            from django.utils import timezone
            self.withdrawal_blocked_until = timezone.now() + timezone.timedelta(hours=1)  # Bloque 1 heure
        self.save()

    def is_withdrawal_blocked(self):
        """Vérifie si le retrait est bloqué"""
        if self.withdrawal_blocked_until:
            from django.utils import timezone
            if timezone.now() < self.withdrawal_blocked_until:
                return True
            else:
                self.reset_failed_attempts()  # Débloque automatiquement
        return False

    def save(self, *args, **kwargs):
        if not self.account_code:
            # Générer un code unique basé sur l'UUID
            unique_suffix = str(uuid.uuid4())[:8].upper()
            self.account_code = f"ACC{unique_suffix}"
        super().save(*args, **kwargs)

class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    address = models.CharField(max_length=255, blank=True, default='')
    phone = models.CharField(max_length=20, blank=True, default='')
    preferred_currency = models.CharField(
        max_length=3, 
        choices=[('USD','USD'),('HTG','HTG'),('DOP','DOP'),('EUR','EUR')],
        default='USD'
    )
    photo = models.ImageField(upload_to='profile_photos/', blank=True, null=True)
    receipt_proof = models.ImageField(upload_to='receipt_uploads/', blank=True, null=True, verbose_name='Reçu MonCash')
    identity_document = models.ImageField(upload_to='identity_documents/', blank=True, null=True, verbose_name="Carte d'identité / Carte SDI")
    recharge_selfie = models.ImageField(upload_to='recharge_selfies/', blank=True, null=True, verbose_name='Selfie de recharge')
    recharge_message = models.TextField(blank=True, null=True, verbose_name='Message de recharge')
    delivery_access_granted = models.BooleanField(default=False)
    delivery_access_requested = models.BooleanField(default=False)
    withdrawal_pin = models.CharField(max_length=8, blank=True, null=True, help_text='Code PIN visible pour retrait')
    withdrawal_code = models.CharField(max_length=4, blank=True, null=True, help_text='Code final visible pour retrait')
    global_withdrawal_access_granted = models.BooleanField(default=False, help_text='Accès aux retraits globaux pour les admins secondaires')
    theme_name = models.CharField(
        max_length=50,
        choices=[
            ('arctic-neon-glass', 'Arctic Neon Glass UI'),
            ('cyber-ice-fintech', 'Cyber Ice Fintech'),
            ('white-blue-cyber', 'White & Blue Cyber Glassmorphism'),
            ('blue-mirror', 'Blue Mirror UI'),
            ('quantum-fintech', 'Quantum Fintech Dashboard'),
            ('neon-flow-banking', 'Neon Flow Banking UI'),
            ('glassmorphism', 'Glassmorphism UI'),
            ('minimal-clean', 'Minimal Clean UI'),
            ('interactive-3d', '3D Interactive UI'),
            ('holographic-ui', 'Holographic UI'),
            ('cyberpunk-ui', 'Cyberpunk UI'),
            ('dark-futuristic', 'Dark Futuristic UI'),
            ('ai-dashboard', 'AI Dashboard UI'),
            ('saas-modern', 'SaaS Modern UI'),
            ('custom', 'Custom Theme'),
        ],
        default='blue-mirror',
        help_text='Selected UI theme'
    )
    theme_settings = JSONField(default=dict, blank=True, help_text='Custom theme color settings')
    is_real_estate_member = models.BooleanField(default=False, verbose_name='Membre Immobilier')

    def _generate_withdrawal_pin(self):
        return ''.join(secrets.choice('0123456789') for _ in range(8))

    def _generate_withdrawal_code(self):
        return ''.join(secrets.choice('0123456789') for _ in range(4))

    def save(self, *args, **kwargs):
        is_new = self.pk is None
        if is_new:
            if not self.withdrawal_pin:
                self.withdrawal_pin = self._generate_withdrawal_pin()
            if not self.withdrawal_code:
                self.withdrawal_code = self._generate_withdrawal_code()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Profil de {self.user.username}"

    class Meta:
        verbose_name = 'Profil utilisateur'
        verbose_name_plural = 'Profils utilisateurs'


class TechnicianProfile(models.Model):
    SERVICE_CHOICES = [
        ('Réseaux informatiques', 'Réseaux informatiques'),
        ('Installation de caméras', 'Installation de caméras'),
        ('Électricité', 'Électricité'),
        ('Informatique', 'Informatique'),
        ('Développement web', 'Développement web'),
        ('Climatisation', 'Climatisation'),
        ('Maintenance technique', 'Maintenance technique'),
        ('Autres services', 'Autres services'),
    ]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='technician_profile')
    company_name = models.CharField(max_length=150)
    contact_name = models.CharField(max_length=120, help_text='Nom du responsable')
    phone = models.CharField(max_length=30)
    email = models.EmailField()
    city_region = models.CharField(max_length=120, blank=True, default='')
    address = models.CharField(max_length=255, blank=True, default='')
    description = models.TextField(blank=True, default='')
    services = models.CharField(max_length=500, blank=True, default='', help_text='Services proposés séparés par des virgules')
    references = models.TextField(blank=True, default='', help_text='Références professionnelles (une par ligne)')
    website = models.URLField(blank=True, default='')
    whatsapp = models.CharField(max_length=80, blank=True, default='')
    facebook = models.URLField(blank=True, default='')
    logo = models.ImageField(upload_to='technician_logos/', blank=True, null=True)
    photo_1 = models.ImageField(upload_to='technician_photos/', blank=True, null=True)
    photo_1_desc = models.CharField(max_length=200, blank=True, default='')
    photo_2 = models.ImageField(upload_to='technician_photos/', blank=True, null=True)
    photo_2_desc = models.CharField(max_length=200, blank=True, default='')
    photo_3 = models.ImageField(upload_to='technician_photos/', blank=True, null=True)
    photo_3_desc = models.CharField(max_length=200, blank=True, default='')
    photo_4 = models.ImageField(upload_to='technician_photos/', blank=True, null=True)
    photo_4_desc = models.CharField(max_length=200, blank=True, default='')
    photo_5 = models.ImageField(upload_to='technician_photos/', blank=True, null=True)
    photo_5_desc = models.CharField(max_length=200, blank=True, default='')
    is_published = models.BooleanField(default=True)
    slug = models.SlugField(max_length=180, unique=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Profil Technicien'
        verbose_name_plural = 'Profils Techniciens'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.company_name} ({self.user.username})"

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(f"{self.company_name}-{self.user.username}")[:160]
            slug = base_slug
            counter = 1
            while TechnicianProfile.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def get_services_list(self):
        return [service.strip() for service in self.services.split(',') if service.strip()]

    def get_reference_list(self):
        return [ref.strip() for ref in self.references.splitlines() if ref.strip()]

    def get_photo_pairs(self):
        pairs = []
        for index in range(1, 6):
            photo = getattr(self, f'photo_{index}', None)
            desc = getattr(self, f'photo_{index}_desc', '')
            if photo:
                pairs.append((photo, desc))
        return pairs


class TiKanePlan(models.Model):
    DURATION_CHOICES = [
        (30, '30 jours'),
        (60, '60 jours'),
        (90, '90 jours'),
        (180, '6 mois'),
        (365, '12 mois'),
        (730, '24 mois'),
    ]

    name = models.CharField(max_length=120, unique=True)
    duration_days = models.PositiveIntegerField(choices=DURATION_CHOICES)
    commission_fixed = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    commission_variable = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    bonus_rate = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    description = models.TextField(blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} - {self.get_duration_days_display()}"

    def calculate_withdrawal_commission(self, amount):
        """Retourne la commission de retrait pour ce plan ou None si aucune commission définie."""
        from decimal import Decimal

        amount = Decimal(str(amount))
        if self.commission_fixed == 0 and self.commission_variable == 0:
            return None

        total = Decimal(str(self.commission_fixed))
        if self.commission_variable:
            total += (amount * Decimal(str(self.commission_variable)) / Decimal('100')).quantize(Decimal('0.01'))
        return total.quantize(Decimal('0.01'))

    class Meta:
        verbose_name = 'Plan Ti Kanè'
        verbose_name_plural = 'Plans Ti Kanè'
        ordering = ['duration_days', 'name']

class TiKaneAccessRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'En attente d\'approbation'),
        ('approved', 'Approuvé'),
        ('refused', 'Refusé'),
        ('suspended', 'Suspendu'),
    ]

    user = models.ForeignKey('User', on_delete=models.CASCADE, related_name='tikane_requests')
    full_name = models.CharField(max_length=255)
    email = models.EmailField(max_length=254)
    phone = models.CharField(max_length=20)
    identity_document = models.ImageField(upload_to='tikane/identity_documents/', blank=True, null=True)
    passport_document = models.ImageField(upload_to='tikane/passports/', blank=True, null=True)
    driver_license_document = models.ImageField(upload_to='tikane/driver_licenses/', blank=True, null=True)
    selfie = models.ImageField(upload_to='tikane/selfies/', blank=True, null=True)
    plan = models.ForeignKey('TiKanePlan', on_delete=models.SET_NULL, blank=True, null=True, related_name='access_requests')
    acceptance_clause = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    account_number = models.CharField(max_length=30, blank=True, null=True, unique=True)
    tikaned_id = models.CharField(max_length=40, blank=True, null=True, unique=True)
    requested_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(blank=True, null=True)
    reviewed_by = models.ForeignKey('User', on_delete=models.SET_NULL, blank=True, null=True, related_name='tikane_reviews')
    admin_notes = models.TextField(blank=True)

    def save(self, *args, **kwargs):
        if self.status == 'approved' and not self.account_number:
            self.account_number = self.account_number or f"TK-{timezone.now().year}-{str(self.pk or int(datetime.datetime.now().timestamp()))[-6:]}"
        if self.status == 'approved' and not self.tikaned_id:
            self.tikaned_id = self.tikaned_id or f"TKID{secrets.token_hex(4).upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Demande Ti Kanè {self.user.username} - {self.get_status_display()}"

    class Meta:
        verbose_name = 'Demande Ti Kanè'
        verbose_name_plural = 'Demandes Ti Kanè'
        ordering = ['-requested_at']

class TiKaneAccount(models.Model):
    STATUS_CHOICES = [
        ('active', 'Actif'),
        ('pending', 'En attente'),
        ('closed', 'Fermé'),
        ('suspended', 'Suspendu'),
    ]

    user = models.OneToOneField('User', on_delete=models.CASCADE, related_name='tikane_account')
    request = models.OneToOneField('TiKaneAccessRequest', on_delete=models.SET_NULL, null=True, blank=True, related_name='tikane_account')
    account_number = models.CharField(max_length=30, unique=True)
    opened_at = models.DateTimeField(auto_now_add=True)
    maturity_date = models.DateTimeField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    unique_identifier = models.CharField(max_length=50, unique=True)
    plan = models.ForeignKey('TiKanePlan', on_delete=models.SET_NULL, null=True, blank=True, related_name='accounts')
    balance = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    total_deposits = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    total_withdrawals = models.DecimalField(max_digits=20, decimal_places=2, default=0)
    is_sdi_managed = models.BooleanField(default=True)
    manager_name = models.CharField(max_length=255, blank=True)
    manager_phone = models.CharField(max_length=50, blank=True)
    manager_email = models.EmailField(max_length=254, blank=True)
    manager_logo = models.ImageField(upload_to='tikane/manager_logos/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.account_number:
            self.account_number = f"TK-{timezone.now().year}-{str(uuid.uuid4())[:8].upper()}"
        if not self.unique_identifier:
            self.unique_identifier = f"TKID-{uuid.uuid4().hex[:10].upper()}"
        if self.plan and not self.maturity_date:
            start_at = self.opened_at or timezone.now()
            self.maturity_date = start_at + timedelta(days=self.plan.duration_days)
        super().save(*args, **kwargs)
        if self.plan and self.status == 'active':
            self.initialize_daily_payment_rows()

    def get_plan_withdrawal_commission(self, amount):
        """Retourne la commission de retrait Ti Kanè pour ce compte basé sur le plan."""
        if not self.plan:
            return None
        return self.plan.calculate_withdrawal_commission(amount)

    def initialize_daily_payment_rows(self):
        if not self.plan:
            return
        existing_days = set(self.daily_payments.values_list('day_number', flat=True))
        for day in range(1, self.plan.duration_days + 1):
            if day not in existing_days:
                TiKaneDailyPayment.objects.create(
                    account=self,
                    day_number=day,
                    status='unpaid',
                    paid=False
                )

    @property
    def is_mature(self):
        return bool(self.maturity_date and timezone.now() >= self.maturity_date)

    @property
    def can_withdraw(self):
        return self.status == 'active' and self.is_mature

    def get_next_unpaid_day(self):
        if not self.plan:
            return None
        paid_days = set(self.daily_payments.filter(paid=True).values_list('day_number', flat=True))
        for day in range(1, self.plan.duration_days + 1):
            if day not in paid_days:
                return day
        return None

    def mark_next_unpaid_day_paid(self, deposit=None):
        next_day = self.get_next_unpaid_day()
        if next_day is None:
            return None
        payment_record, created = TiKaneDailyPayment.objects.get_or_create(
            account=self,
            day_number=next_day,
            defaults={
                'status': 'paid',
                'paid': True,
                'paid_at': timezone.now(),
                'deposit': deposit,
            }
        )
        if not created:
            payment_record.status = 'paid'
            payment_record.paid = True
            payment_record.paid_at = payment_record.paid_at or timezone.now()
            payment_record.deposit = deposit or payment_record.deposit
            payment_record.save(update_fields=['status', 'paid', 'paid_at', 'deposit'])

        # Générer automatiquement un reçu numérique pour ce jour payé
        try:
            if deposit and hasattr(deposit, 'client'):
                receipt_number = f"TKP-{uuid.uuid4().hex[:8].upper()}-{self.user.id}-{next_day}"
                content = (
                    f"Ti Kanè - Reçu Paiement Journalier\n"
                    f"Client: {self.user.username}\n"
                    f"Plan: {self.plan.name if self.plan else 'N/A'}\n"
                    f"Jour: {next_day}/{self.plan.duration_days if self.plan else '?'}\n"
                    f"Montant payé: {deposit.amount:.2f} {deposit.currency}\n"
                    f"Date: {timezone.now().strftime('%d/%m/%Y %H:%M')}\n"
                    f"Référence dépôt: {deposit.reference}\n"
                    f"Note: Montant réservé pour Ti Kanè Digital. Retrait indisponible avant la date prévue.\n"
                )
                DepositReceipt.objects.create(
                    receipt_number=receipt_number,
                    client=self.user,
                    agent=deposit.agent if hasattr(deposit, 'agent') else None,
                    deposit=deposit,
                    content=content
                )
        except Exception:
            # Ne pas interrompre le flux principal si la génération du reçu échoue
            pass

        return payment_record

    def get_daily_payment_statuses(self):
        if not self.plan:
            return []
        payments = {p.day_number: p for p in self.daily_payments.all()}
        rows = []
        for day in range(1, self.plan.duration_days + 1):
            record = payments.get(day)
            rows.append({
                'day': day,
                'paid': bool(record and record.paid),
                'paid_at': record.paid_at if record else None,
                'deposit': record.deposit if record else None,
            })
        return rows

    @property
    def days_until_maturity(self):
        if not self.maturity_date:
            return None
        delta = self.maturity_date - timezone.now()
        return max(delta.days, 0)

    def __str__(self):
        return f"{self.account_number} - {self.user.username}"

    class Meta:
        verbose_name = 'Compte Ti Kanè'
        verbose_name_plural = 'Comptes Ti Kanè'
        ordering = ['-opened_at']

class TiKaneDailyPayment(models.Model):
    STATUS_CHOICES = [
        ('paid', 'Payer'),
        ('unpaid', 'Non payer'),
    ]

    account = models.ForeignKey('TiKaneAccount', on_delete=models.CASCADE, related_name='daily_payments')
    day_number = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='paid')
    paid = models.BooleanField(default=False)
    paid_at = models.DateTimeField(blank=True, null=True)
    deposit = models.ForeignKey('Deposit', on_delete=models.SET_NULL, null=True, blank=True, related_name='tikane_daily_payments')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Paiement journalier Ti Kanè'
        verbose_name_plural = 'Paiements journaliers Ti Kanè'
        unique_together = ('account', 'day_number')
        ordering = ['account', 'day_number']

    def save(self, *args, **kwargs):
        self.paid = self.status == 'paid'
        if self.paid and not self.paid_at:
            self.paid_at = timezone.now()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Jour {self.day_number} - {self.account.user.username} - {'Payer' if self.paid else 'Non payer'}"

class ExchangeRate(models.Model):
    usd_to_htg = models.DecimalField(max_digits=15, decimal_places=6, default=0)
    usd_to_peso = models.DecimalField(max_digits=15, decimal_places=6, default=0)
    htg_to_peso = models.DecimalField(max_digits=15, decimal_places=6, default=0)
    eur_to_usd = models.DecimalField(max_digits=15, decimal_places=6, default=0)
    eur_to_htg = models.DecimalField(max_digits=15, decimal_places=6, default=0)
    eur_to_peso = models.DecimalField(max_digits=15, decimal_places=6, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"Taux de change ({self.created_at:%Y-%m-%d %H:%M})"

class CommissionConfig(models.Model):
    TYPE_CHOICES = (
        ('pourcentage', 'Pourcentage'),
        ('fixe', 'Fixe'),
        ('variable', 'Variable'),
    )
    
    nom = models.CharField(max_length=100, unique=True)
    valeur = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    type = models.CharField(max_length=50, choices=TYPE_CHOICES)
    description = models.TextField(blank=True)
    actif = models.BooleanField(default=True)
    date_modification = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.nom}: {self.valeur} ({self.type})"

    class Meta:
        verbose_name = 'Configuration Commission'
        verbose_name_plural = 'Configurations Commissions'
        ordering = ['nom']


class WithdrawalCommissionTier(models.Model):
    currency = models.CharField(max_length=10, default='HTG')
    min_amount = models.DecimalField(max_digits=15, decimal_places=2)
    max_amount = models.DecimalField(max_digits=15, decimal_places=2)
    total_fee = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    system_fee = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    agent_fee = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    description = models.CharField(max_length=255, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Tranche Commission Retrait'
        verbose_name_plural = 'Tranches Commission Retrait'
        ordering = ['min_amount']

    def __str__(self):
        return f"{self.description or f'{self.min_amount}-{self.max_amount} {self.currency}'}"


class WithdrawalTransaction(models.Model):
    withdrawal_request = models.ForeignKey('WithdrawalRequest', on_delete=models.CASCADE, related_name='withdrawal_transactions', null=True, blank=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='withdrawal_transactions')
    agent = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='agent_withdrawal_transactions')
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    currency = models.CharField(max_length=10, default='HTG')
    account_type = models.CharField(max_length=20, blank=True)
    fee_total = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    fee_system = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    fee_agent = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    type = models.CharField(max_length=50, default='withdrawal')
    status = models.CharField(max_length=50, default='completed')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Transaction Retrait'
        verbose_name_plural = 'Transactions Retrait'
        ordering = ['-created_at']

    def __str__(self):
        return f"Retrait {self.amount} {self.currency} - {self.user.username if self.user else 'Inconnu'}"


class AdminCommissionLog(models.Model):
    ACTION_CHOICES = (
        ('create', 'Création'),
        ('update', 'Mise à jour'),
        ('delete', 'Suppression'),
        ('toggle', 'Activation / Désactivation'),
    )
    admin = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='commission_logs')
    action_type = models.CharField(max_length=20, choices=ACTION_CHOICES)
    target_name = models.CharField(max_length=200)
    target_type = models.CharField(max_length=100, default='WithdrawalCommissionTier')
    old_value = models.TextField(blank=True, null=True)
    new_value = models.TextField(blank=True, null=True)
    ip_address = models.CharField(max_length=45, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Journal Modification Commission'
        verbose_name_plural = 'Journaux Modification Commission'
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.get_action_type_display()}] {self.target_name} par {self.admin.username if self.admin else 'Inconnu'}"


class ActivityMenuItem(models.Model):
    title = models.CharField(max_length=120)
    url = models.CharField(max_length=255, blank=True, default='#')
    icon_class = models.CharField(max_length=120, blank=True, default='fa-solid fa-circle-check')
    description = models.TextField(blank=True, help_text='Utilisez des retours à la ligne pour séparer les points de menu.')
    is_active = models.BooleanField(default=True)
    order = models.PositiveIntegerField(default=100)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Élément de menu activité'
        verbose_name_plural = 'Éléments de menu activité'
        ordering = ['order', 'title']

    def __str__(self):
        return self.title


# -------------------------------
# Classe utilitaire pour les catégories (utilise des raw queries)
# -------------------------------
class CategoryManager:
    @staticmethod
    def get_main_categories():
        """Récupère les catégories principales (sans parent)"""
        from django.apps import apps
        Category = apps.get_model('marketplace', 'Category')
        return list(Category.objects.filter(parent__isnull=True, is_active=True)
                    .order_by('name')
                    .values('id', 'name', 'slug', 'description', 'image', 'is_active', 'created_at', 'updated_at'))

    @staticmethod
    def get_category_by_slug(slug):
        """Récupère une catégorie par son slug"""
        from django.apps import apps
        Category = apps.get_model('marketplace', 'Category')
        return Category.objects.filter(
            slug=slug,
            is_active=True
        ).values(
            'id', 'name', 'slug', 'description', 'parent_id', 'image', 'is_active', 'created_at', 'updated_at'
        ).first()

    @staticmethod
    def get_category_children(parent_id):
        """Récupère les sous-catégories d'une catégorie"""
        from django.apps import apps
        Category = apps.get_model('marketplace', 'Category')
        return list(Category.objects.filter(parent_id=parent_id, is_active=True)
                    .order_by('name')
                    .values('id', 'name', 'slug', 'description', 'image', 'is_active'))

    @staticmethod
    def get_category_products_count(category_id):
        """Compte les produits dans une catégorie et ses sous-catégories"""
        from django.apps import apps
        Category = apps.get_model('marketplace', 'Category')
        Product = apps.get_model('marketplace', 'Product')

        category_ids = [category_id]
        category_ids.extend(list(Category.objects.filter(parent_id=category_id, is_active=True).values_list('id', flat=True)))

        return Product.objects.filter(category_id__in=category_ids, quantity__gt=0).count()

    @staticmethod
    def get_category_full_path(category_id):
        """Construit le chemin complet d'une catégorie"""
        from django.apps import apps
        Category = apps.get_model('marketplace', 'Category')

        path_parts = []
        current_id = category_id

        while current_id:
            category = Category.objects.filter(id=current_id).values('name', 'parent_id').first()
            if category:
                path_parts.insert(0, category['name'])
                current_id = category['parent_id']
            else:
                break

        return ' > '.join(path_parts)

# -------------------------------
# Boutique / Shop
# -------------------------------
class Shop(models.Model):
    owner = models.ForeignKey(User, on_delete=models.CASCADE)
    name = models.CharField(max_length=100, default="Ma Boutique")
    created_at = models.DateTimeField(auto_now_add=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, help_text="Latitude de la boutique")
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True, help_text="Longitude de la boutique")

    def get_cover_photos(self):
        return self.cover_photos.order_by('sort_order', 'uploaded_at')


class ShopCoverPhoto(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='cover_photos')
    image = models.ImageField(upload_to='shop_covers/%Y/%m/', help_text='Photo de couverture du studio')
    sort_order = models.PositiveIntegerField(default=0)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['sort_order', 'uploaded_at']
        verbose_name = 'Photo de couverture studio'
        verbose_name_plural = 'Photos de couverture studio'

    def __str__(self):
        return f"Cover photo {self.id} for {self.shop.name}"


# -------------------------------
# Produit
# -------------------------------
class PriorityGroup(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name='Nom du groupe')
    priority = models.PositiveIntegerField(default=100, verbose_name='Priorité')
    weight = models.PositiveIntegerField(default=1, verbose_name='Poids de diffusion')
    is_active = models.BooleanField(default=True, verbose_name='Groupe actif')
    start_date = models.DateTimeField(blank=True, null=True, verbose_name='Date de début')
    end_date = models.DateTimeField(blank=True, null=True, verbose_name='Date de fin')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['priority', 'name']
        verbose_name = 'Groupe de priorité'
        verbose_name_plural = 'Groupes de priorité'

    def __str__(self):
        return self.name

    def is_scheduled_active(self, now=None):
        now = now or timezone.now()
        return (
            self.is_active
            and (self.start_date is None or self.start_date <= now)
            and (self.end_date is None or self.end_date >= now)
        )

    def is_expired(self, now=None):
        now = now or timezone.now()
        return bool(self.end_date and self.end_date < now)

    def is_scheduled(self, now=None):
        now = now or timezone.now()
        return self.is_active and self.start_date and self.start_date > now


class Product(models.Model):
    CURRENCY_CHOICES = (
        ('USD', 'USD ($)'),
        ('HTG', 'Gourdes (HTG)'),
        ('DOP', 'Peso Dominicain (DOP)'),
        ('EUR', 'Euro (€)'),
    )
    
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE)
    category = models.ForeignKey('Category', on_delete=models.CASCADE, null=True, blank=True, related_name='products')
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, default='')
    price_ht = models.DecimalField(max_digits=15, decimal_places=2, help_text="Prix en USD (devise interne)")  # DEVISE INTERNE: USD
    price_original = models.DecimalField(max_digits=15, decimal_places=2, blank=True, null=True, help_text="Prix original saisi par le vendeur dans la devise choisie")
    price_original_currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, blank=True, null=True, default='USD', help_text="Devise du prix saisi par le vendeur")
    price_input_currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default='USD', help_text="Devise saisie par le vendeur")
    quantity = models.PositiveIntegerField()
    image = models.URLField(blank=True, null=True, help_text="Image générée automatiquement")  # Image auto-générée
    custom_image = models.ImageField(upload_to="products/", blank=True, null=True, help_text="Image personnalisée uploadée")  # Image custom
    # Dimensions du produit
    largeur = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True, help_text="Largeur en cm")
    hauteur = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True, help_text="Hauteur en cm")
    longueur = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True, help_text="Longueur en cm")
    poids = models.DecimalField(max_digits=10, decimal_places=2, blank=True, null=True, help_text="Poids en kg")
    created_at = models.DateTimeField(auto_now_add=True)
    
    # Contrôle de l'affichage en bannière/carrousel
    banner_display_allowed = models.BooleanField(default=True, help_text="Autoriser l'affichage en bannière (par défaut: True si image valide)")
    banner_blocked_by_admin = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='blocked_banner_products', help_text="Admin qui a bloqué")
    banner_blocked_at = models.DateTimeField(null=True, blank=True, help_text="Date du blocage")
    banner_block_reason = models.TextField(blank=True, default='', help_text="Raison du blocage")
    priority_group = models.ForeignKey(PriorityGroup, on_delete=models.SET_NULL, null=True, blank=True, related_name='products', verbose_name='Groupe de priorité')
    banner_priority = models.PositiveIntegerField(default=100, verbose_name='Priorité individuelle')
    banner_weight = models.PositiveIntegerField(default=1, verbose_name='Poids individuel')
    
    def get_display_image(self):
        """Retourne l'image à afficher (custom si existe, sinon auto-générée)"""
        return self.custom_image.url if self.custom_image else self.image
    
    def has_valid_image(self):
        """Vérifie si le produit a une image valide"""
        return bool(self.custom_image or self.image)
    
    def is_eligible_for_banner(self):
        """Vérifie si le produit est éligible pour la bannière
        Règle: image valide + admin_allowed = True"""
        return self.has_valid_image() and self.banner_display_allowed
    
    def get_images(self):
        """Retourne toutes les images du produit"""
        images = list(self.images.all().values_list('image', flat=True))
        display_image = self.get_display_image()
        if display_image and display_image not in images:
            images.insert(0, display_image)
        return images
    
    def get_primary_image(self):
        """Retourne l'image principale"""
        primary = self.images.filter(is_primary=True).first()
        if primary:
            return primary.image.url if primary.image else None
        return self.get_display_image()

    def create_copy_for_reseller(self, reseller_user):
        """Crée une copie produit dans la boutique du revendeur."""
        shop = Shop.objects.filter(owner=reseller_user).first()
        if not shop:
            shop = Shop.objects.create(owner=reseller_user, name=f'Boutique {reseller_user.username}')
        new_prod = Product.objects.create(
            shop=shop,
            category=self.category,
            name=self.name,
            description=self.description,
            price_ht=self.price_ht,
            price_original=self.price_original,
            price_original_currency=self.price_original_currency,
            price_input_currency=self.price_input_currency,
            quantity=self.quantity,
            image=self.image,
            custom_image=self.custom_image,
            largeur=self.largeur,
            hauteur=self.hauteur,
            longueur=self.longueur,
            poids=self.poids,
        )
        for img in self.images.all():
            try:
                ProductImage.objects.create(
                    product=new_prod,
                    image=img.image,
                    is_primary=img.is_primary,
                    alt_text=img.alt_text,
                    sort_order=img.sort_order
                )
            except Exception:
                pass
        return new_prod

# -------------------------------
# Images de Produit (Galerie)
# -------------------------------
class ProductImage(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to="products/%Y/%m/", help_text="Image du produit")
    is_primary = models.BooleanField(default=False, help_text="Image affichée par défaut")
    alt_text = models.CharField(max_length=200, blank=True, help_text="Description pour l'accessibilité")
    sort_order = models.PositiveIntegerField(default=0)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['sort_order', 'uploaded_at']
        verbose_name = 'Image du produit'
        verbose_name_plural = 'Images du produit'
    
    def __str__(self):
        return f"{self.product.name} - {self.uploaded_at}"
    
    def save(self, *args, **kwargs):
        # Si cette image est marquée comme principale, supprimer les autres
        if self.is_primary:
            ProductImage.objects.filter(product=self.product, is_primary=True).update(is_primary=False)
        super().save(*args, **kwargs)


class SiteBanner(models.Model):
    """Bannière premium placée au-dessus du header, avec un produit réel associé."""
    DISPLAY_MODE_CHOICES = (
        ('static', 'Image statique'),
        ('carousel', 'Carrousel'),
    )
    SCOPE_CHOICES = (
        ('all', 'Toutes les boutiques'),
        ('selected', 'Boutiques sélectionnées'),
    )
    ACCESS_MODE_CHOICES = (
        ('free', 'Gratuit pour tous'),
        ('selected', 'Accès individuel'),
        ('paid', 'Payant via MicroCash'),
    )
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='site_banners', help_text='Produit réel affiché dans la bannière')
    title = models.CharField(max_length=120, default='Offre du moment', verbose_name='Titre')
    subtitle = models.CharField(max_length=220, blank=True, default='', verbose_name='Sous-titre')
    button_text = models.CharField(max_length=40, default='Voir le produit', verbose_name='Texte du bouton')
    image = models.ImageField(upload_to='site_banner/%Y/%m/', blank=True, null=True, verbose_name='Image de la bannière')
    is_active = models.BooleanField(default=True, verbose_name='Activer la bannière')
    display_order = models.PositiveIntegerField(default=0)
    start_date = models.DateTimeField(blank=True, null=True)
    end_date = models.DateTimeField(blank=True, null=True)
    display_mode = models.CharField(max_length=20, choices=DISPLAY_MODE_CHOICES, default='static')
    autoplay_seconds = models.PositiveSmallIntegerField(default=0, help_text='0 désactive la lecture automatique')
    autoplay_enabled = models.BooleanField(default=True, verbose_name='Défilement automatique actif')
    scope = models.CharField(max_length=20, choices=SCOPE_CHOICES, default='all')
    shops = models.ManyToManyField(Shop, blank=True, related_name='site_banners')
    access_mode = models.CharField(max_length=20, choices=ACCESS_MODE_CHOICES, default='free')
    access_price = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['display_order', '-created_at']
        verbose_name = 'Bannière du site'
        verbose_name_plural = 'Bannières du site'

    def __str__(self):
        return f"{self.title} - {self.product.name}"

    def get_product_image_url(self):
        if self.image and not str(self.image.name).startswith(('http://', 'https://')):
            return self.image.url
        if self.product and self.product.get_primary_image():
            return self.product.get_primary_image()
        if self.product and self.product.custom_image:
            return self.product.custom_image.url
        if self.product and self.product.image:
            return self.product.image
        return ''

    def get_media_items(self):
        items = [item.image.url for item in self.images.order_by('display_order', 'id')]
        if self.image and not str(self.image.name).startswith(('http://', 'https://')):
            items.insert(0, self.image.url)
        elif not items:
            product_image = self.get_product_image_url()
            if product_image:
                items.append(product_image)
        return items

    def get_image_sources(self):
        if not self.image or str(self.image.name).startswith(('http://', 'https://')):
            return {'fallback': self.get_product_image_url(), 'webp': '', 'avif': '', 'sizes': '(max-width: 768px) 88px, 120px'}
        base, _ = os.path.splitext(self.image.name)
        variants = []
        for width in (480, 768, 1024, 1280, 1600):
            webp = f'{base}_{width}w.webp'
            avif = f'{base}_{width}w.avif'
            if default_storage.exists(webp):
                variants.append((width, default_storage.url(webp), default_storage.url(avif) if default_storage.exists(avif) else ''))
        return {
            'fallback': self.image.url,
            'webp': ', '.join(f'{url} {width}w' for width, url, _ in variants),
            'avif': ', '.join(f'{url} {width}w' for width, _, url in variants if url),
            'sizes': '(max-width: 768px) 88px, 120px',
        }

    @classmethod
    def get_active_banners(cls):
        now = timezone.now()
        queryset = cls.objects.filter(is_active=True).select_related('product', 'product__shop')
        queryset = queryset.filter(models.Q(start_date__isnull=True) | models.Q(start_date__lte=now))
        queryset = queryset.filter(models.Q(end_date__isnull=True) | models.Q(end_date__gte=now))
        return queryset.order_by('display_order', '-created_at')

    def is_visible_for_shop(self, shop):
        return self.scope == 'all' or (shop is not None and self.shops.filter(pk=shop.pk).exists())

    def can_access(self, user):
        if self.access_mode == 'free':
            return True
        if not user or not user.is_authenticated:
            return False
        if self.access_mode == 'selected':
            return self.access_grants.filter(user=user).exists()
        return self.payments.filter(user=user, status='confirmed').exists()


class SiteBannerImage(models.Model):
    banner = models.ForeignKey(SiteBanner, on_delete=models.CASCADE, related_name='images')
    image = models.ImageField(upload_to='site_banner/%Y/%m/')
    display_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['display_order', 'id']


class SiteBannerPermission(models.Model):
    banner = models.ForeignKey(SiteBanner, on_delete=models.CASCADE, related_name='permissions')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='site_banner_permissions')
    granted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='granted_site_banner_permissions')
    can_manage = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['banner', 'user'], name='unique_site_banner_permission')]


class SiteBannerAccess(models.Model):
    banner = models.ForeignKey(SiteBanner, on_delete=models.CASCADE, related_name='access_grants')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='site_banner_access_grants')
    granted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='granted_site_banner_access')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['banner', 'user'], name='unique_site_banner_access')]


class SiteBannerPayment(models.Model):
    STATUS_CHOICES = (('pending', 'En attente'), ('confirmed', 'Confirmé'), ('failed', 'Échoué'))
    banner = models.ForeignKey(SiteBanner, on_delete=models.CASCADE, related_name='payments')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='site_banner_payments')
    transaction = models.OneToOneField('Transaction', on_delete=models.SET_NULL, null=True, blank=True, related_name='site_banner_payment')
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=['banner', 'user'], name='unique_site_banner_payment')]


class SiteBannerEvent(models.Model):
    EVENT_CHOICES = (
        ('impression', 'Impression'), ('click', 'Clic'), ('created', 'Création'),
        ('updated', 'Modification'), ('activated', 'Activation'), ('deactivated', 'Désactivation'),
        ('deleted', 'Suppression'), ('image_added', 'Ajout image'), ('image_replaced', 'Remplacement image'), ('image_deleted', 'Suppression image'), ('cropped', 'Recadrage'), ('scope_changed', 'Changement portée'), ('permission_granted', 'Attribution permission'), ('permission_revoked', 'Révocation permission'), ('access_mode_changed', 'Mode accès modifié'), ('access_granted', 'Accès accordé'), ('access_revoked', 'Accès révoqué'), ('payment_required', 'Paiement requis'), ('payment_confirmed', 'Paiement confirmé'), ('payment_failed', 'Paiement échoué'),
    )
    banner = models.ForeignKey(SiteBanner, on_delete=models.SET_NULL, null=True, related_name='events')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    event_type = models.CharField(max_length=30, choices=EVENT_CHOICES)
    session_key = models.CharField(max_length=40, blank=True, default='')
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

# -------------------------------
# Marketplace / Revendeurs
# -------------------------------
class ProductAccessRequest(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    )

    seller = models.ForeignKey(User, on_delete=models.CASCADE, related_name='access_requests')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='access_requests')
    owner_shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name='incoming_access_requests')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    commission_type = models.CharField(max_length=10, choices=(('percent','Percent'),('fixed','Fixed')), default='percent')
    commission_value = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Valeur de la commission (pourcentage ou montant fixe selon le type)")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'product_access_requests'
        ordering = ['-created_at']

    def __str__(self):
        return f"Request #{self.id} - {self.seller.username} -> {self.product.name} ({self.status})"


class ResellerProduct(models.Model):
    STATUS_CHOICES = (
        ('active', 'Active'),
        ('suspended', 'Suspended'),
        ('removed', 'Removed'),
    )

    seller = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reseller_products')
    original_product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='resold_instances')
    copied_product = models.ForeignKey(Product, on_delete=models.CASCADE, null=True, blank=True, related_name='copied_instances')
    commission_type = models.CharField(max_length=10, choices=(('percent','Percent'),('fixed','Fixed')), default='percent')
    commission_value = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    custom_price = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True, help_text="Prix personnalisé affiché dans la boutique du revendeur")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'reseller_products'
        unique_together = (('seller','original_product'),)

    def __str__(self):
        return f"ResellerProduct {self.id} - {self.seller.username} / {self.original_product.name}"


class BeautyAppointment(models.Model):
    BOOKING_TYPE_CHOICES = (
        ('home', 'Service à domicile'),
        ('studio', 'Service au studio'),
    )
    STATUS_CHOICES = (
        ('pending', 'En attente'),
        ('confirmed', 'Confirmé'),
        ('completed', 'Complété'),
        ('cancelled', 'Annulé'),
    )

    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='beauty_appointments')
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True, related_name='beauty_appointments')
    booking_type = models.CharField(max_length=20, choices=BOOKING_TYPE_CHOICES, default='studio')
    scheduled_date = models.DateField()
    scheduled_time = models.TimeField()
    address = models.CharField(max_length=300, blank=True, help_text='Adresse à domicile ou adresse de rendez-vous au studio')
    instructions = models.TextField(blank=True, help_text='Informations supplémentaires pour le technicien')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    technician = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_beauty_appointments')
    payment_confirmed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Réservation Beauté'
        verbose_name_plural = 'Réservations Beauté'
        ordering = ['-scheduled_date', '-scheduled_time', '-created_at']

    def __str__(self):
        return f"Réservation Beauté #{self.id} - {self.user.username} - {self.get_booking_type_display()}"


class BeautyStudioService(models.Model):
    SERVICE_TYPE_CHOICES = (
        ('manicure', 'Manucure'),
        ('pedicure', 'Pédicure'),
        ('haircare', 'Soin Capillaire'),
        ('african_braids', 'Tresse Africaine'),
    )

    shop = models.ForeignKey('Shop', on_delete=models.CASCADE, related_name='beauty_services')
    service_type = models.CharField(max_length=30, choices=SERVICE_TYPE_CHOICES, default='manicure')
    title = models.CharField(max_length=120, help_text='Nom du service')
    price_ht = models.DecimalField(max_digits=15, decimal_places=2, help_text='Prix en USD (devise interne)')
    image = models.ImageField(upload_to='beauty_services/%Y/%m/', blank=True, null=True, help_text='Photo du service')
    description = models.TextField(blank=True, help_text='Description courte du service')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Service Studio Beauté'
        verbose_name_plural = 'Services Studio Beauté'
        ordering = ['service_type', 'title']

    def __str__(self):
        return f"{self.get_service_type_display()} - {self.title} ({self.shop.owner.username})"


class BeautyStudioRequest(models.Model):
    STATUS_CHOICES = (
        ('pending', 'En attente'),
        ('approved', 'Approuvé'),
        ('rejected', 'Rejeté'),
    )
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='beauty_studio_request')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    studio_name = models.CharField(max_length=100, help_text='Nom du studio de beauté')
    description = models.TextField(blank=True, help_text='Description des services proposés')
    phone = models.CharField(max_length=20, blank=True, help_text='Numéro de téléphone du studio')
    address = models.CharField(max_length=300, blank=True, help_text='Adresse du studio')
    specialties = models.CharField(max_length=500, blank=True, help_text='Spécialités (ex: coiffure, maquillage, massages)')
    
    # Shop created after approval
    approved_shop = models.OneToOneField(Shop, on_delete=models.SET_NULL, null=True, blank=True, related_name='beauty_studio_request')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_beauty_studios')
    
    class Meta:
        verbose_name = 'Demande Studio Beauté'
        verbose_name_plural = 'Demandes Studio Beauté'
        ordering = ['-created_at']
    
    def __str__(self):
        return f"Demande Studio Beauté - {self.user.username} ({self.get_status_display()})"
    
    def approve(self, admin_user):
        """Approuve la demande et crée le shop du studio de beauté"""
        if self.status != 'pending':
            return False
        
        # Créer le shop
        shop, created = Shop.objects.get_or_create(
            owner=self.user,
            defaults={'name': self.studio_name}
        )
        
        self.approved_shop = shop
        self.status = 'approved'
        self.approved_at = timezone.now()
        self.approved_by = admin_user
        self.save()
        
        return True


class MarketplaceSettings(models.Model):
    # Singleton settings for the marketplace
    default_commission_type = models.CharField(max_length=10, choices=(('percent','Percent'),('fixed','Fixed')), default='percent')
    default_commission_value = models.DecimalField(max_digits=10, decimal_places=2, default=10.00, help_text='Commission par défaut (pourcentage ou montant fixe selon le type)')
    commission_admin_share = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('70.00'), help_text='Part de la commission versée au portefeuille admin (%)')
    commission_distribution_share = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('30.00'), help_text='Part de la commission versée à la réserve de distribution (%)')
    validation_required = models.BooleanField(default=True)
    allow_auto_copy = models.BooleanField(default=False)
    copy_limit_per_product = models.PositiveIntegerField(default=10)
    max_active_copies_per_seller = models.PositiveIntegerField(default=50, help_text='Nombre maximum de copies actives par vendeur')
    enable_real_estate_auto_loan = models.BooleanField(default=False, verbose_name='Prêt automatique immobilier')
    real_estate_membership_fee_htg = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('100.00'), verbose_name='Frais d’adhésion immobilier (HTG)')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Marketplace Settings'
        verbose_name_plural = 'Marketplace Settings'

    def __str__(self):
        return 'Marketplace settings'

    @staticmethod
    def get_solo():
        settings, _ = MarketplaceSettings.objects.get_or_create(pk=1)
        return settings

    def get_seller_commission(self, seller):
        from .models import MarketplaceSellerCommission

        override = MarketplaceSellerCommission.objects.filter(seller=seller, is_active=True).first()
        if override:
            return override.commission_type, override.commission_value
        return self.default_commission_type, self.default_commission_value

    def clean(self):
        if self.commission_admin_share < Decimal('0'):
            self.commission_admin_share = Decimal('0')
        if self.commission_distribution_share < Decimal('0'):
            self.commission_distribution_share = Decimal('0')
        if self.commission_admin_share + self.commission_distribution_share > Decimal('100'):
            self.commission_distribution_share = Decimal('100') - self.commission_admin_share
            if self.commission_distribution_share < Decimal('0'):
                self.commission_distribution_share = Decimal('0')

    def get_commission_split(self, amount):
        admin_share = min(max(self.commission_admin_share, Decimal('0')), Decimal('100'))
        distribution_share = min(max(self.commission_distribution_share, Decimal('0')), Decimal('100') - admin_share)
        distribution_amount = (amount * distribution_share / Decimal('100')).quantize(Decimal('0.01'))
        admin_amount = amount - distribution_amount
        return admin_amount, distribution_amount

    def get_copy_limit(self):
        return self.copy_limit_per_product

    def get_max_active_copies_for_seller(self):
        return self.max_active_copies_per_seller


class SDISolSettings(models.Model):
    FREQUENCY_CHOICES = (
        ('weekly', 'Hebdomadaire'),
        ('monthly', 'Mensuelle'),
    )

    max_members = models.PositiveSmallIntegerField(default=10)
    contribution_amount_usd = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('100.00'))
    contribution_amount_htg = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('2600.00'))
    frequency = models.CharField(max_length=10, choices=FREQUENCY_CHOICES, default='weekly')
    withdrawal_fee_htg = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('1000.00'))
    withdrawal_fee_usd = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('10.00'))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'SDI Sol Settings'
        verbose_name_plural = 'SDI Sol Settings'

    def __str__(self):
        return 'SDI Sol Settings'

    @staticmethod
    def get_solo():
        settings, _ = SDISolSettings.objects.get_or_create(pk=1)
        return settings

    def get_period_timedelta(self):
        if self.frequency == 'monthly':
            return timezone.timedelta(days=30)
        return timezone.timedelta(days=7)


class SDISolMember(models.Model):
    STATUS_CHOICES = (
        ('ontime', 'À jour'),
        ('late', 'En retard'),
        ('pending', 'En attente'),
    )

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='sdi_sol_member')
    joined_at = models.DateTimeField(auto_now_add=True)
    position = models.PositiveSmallIntegerField(default=0)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    last_payment_date = models.DateTimeField(null=True, blank=True)
    next_due_date = models.DateTimeField(null=True, blank=True)
    total_paid_usd = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_paid_htg = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    active = models.BooleanField(default=True)
    admin_approved = models.BooleanField(default=False)
    admin_approval_date = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True, default='')

    class Meta:
        verbose_name = 'SDI Sol Member'
        verbose_name_plural = 'SDI Sol Members'
        ordering = ['position', 'joined_at']

    def __str__(self):
        return f'{self.user.username} - Sol SDI'

    def update_status(self):
        if self.next_due_date and timezone.now() > self.next_due_date:
            self.status = 'late'
        elif self.last_payment_date:
            self.status = 'ontime'
        else:
            self.status = 'pending'
        self.save(update_fields=['status'])

    def schedule_next_due_date(self):
        settings = SDISolSettings.get_solo()
        period = settings.get_period_timedelta()
        base_date = self.last_payment_date or timezone.now()
        self.next_due_date = base_date + period

    @staticmethod
    def recalculate_rankings():
        members = list(SDISolMember.objects.filter(active=True, admin_approved=True).order_by('status', '-last_payment_date', 'joined_at'))
        members.sort(key=lambda m: (m.status != 'ontime', m.last_payment_date is None, m.last_payment_date or timezone.now(), m.joined_at))
        for idx, member in enumerate(members, start=1):
            if member.position != idx:
                member.position = idx
                member.save(update_fields=['position'])

    def approve(self):
        self.admin_approved = True
        self.admin_approval_date = timezone.now()
        self.save(update_fields=['admin_approved', 'admin_approval_date'])

    @property
    def is_approved(self):
        return self.admin_approved

    def get_status_badge(self):
        return {
            'ontime': '🟢',
            'late': '🟡',
            'pending': '🟡',
        }.get(self.status, '🟡')


class SDISolPayment(models.Model):
    STATUS_CHOICES = (
        ('pending', 'En attente'),
        ('completed', 'Effectué'),
        ('late', 'En retard'),
    )

    member = models.ForeignKey(SDISolMember, on_delete=models.CASCADE, related_name='payments')
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    currency = models.CharField(max_length=3, choices=(('USD', 'USD'), ('HTG', 'HTG')))
    fee = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    receipt_number = models.CharField(max_length=100, unique=True)
    due_date = models.DateTimeField()
    paid_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'SDI Sol Payment'
        verbose_name_plural = 'SDI Sol Payments'
        ordering = ['-created_at']

    def __str__(self):
        return f'{self.receipt_number} - {self.member.user.username} ({self.amount} {self.currency})'

    def save(self, *args, **kwargs):
        if not self.receipt_number:
            self.receipt_number = f'SDISOL-{secrets.token_hex(6).upper()}'
        if self.paid_at and self.due_date:
            self.status = 'completed' if self.paid_at <= self.due_date else 'late'
        elif self.paid_at:
            self.status = 'completed'
        super().save(*args, **kwargs)

    def mark_paid(self, paid_at=None):
        self.paid_at = paid_at or timezone.now()
        self.status = 'completed' if self.paid_at <= self.due_date else 'late'
        self.save()
        member = self.member
        if self.currency == 'USD':
            member.total_paid_usd += self.amount
        else:
            member.total_paid_htg += self.amount
        member.last_payment_date = self.paid_at
        member.schedule_next_due_date()
        member.update_status()
        member.save(update_fields=['total_paid_usd', 'total_paid_htg', 'last_payment_date', 'next_due_date', 'status'])

    def get_receipt_summary(self):
        return {
            'member_name': self.member.user.username,
            'position': self.member.position,
            'date': self.paid_at or self.created_at,
            'amount': self.amount,
            'currency': self.currency,
            'fee': self.fee,
            'receipt_number': self.receipt_number,
        }


class CommissionCategory(models.Model):
    CATEGORY_CHOICES = (
        ('peuple', 'Commission Peuple'),
        ('privilege', 'Utilisateur Privilégié'),
        ('premiere', 'Utilisateur Première'),
    )

    slug = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, default='')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Catégorie de commission'
        verbose_name_plural = 'Catégories de commission'
        ordering = ['name']

    def __str__(self):
        return self.name

    @staticmethod
    def get_default_categories():
        return [
            {'slug': 'peuple', 'name': 'Commission Peuple', 'description': 'Éligibilité basée sur l’activité des utilisateurs.', 'is_active': True},
            {'slug': 'privilege', 'name': 'Utilisateur Privilégié', 'description': 'Accès réservé aux utilisateurs attribués au statut privilège.', 'is_active': True},
            {'slug': 'premiere', 'name': 'Utilisateur Première', 'description': 'Niveau premium avec avantages supplémentaires.', 'is_active': True},
        ]

    @staticmethod
    def ensure_default_categories():
        for category in CommissionCategory.get_default_categories():
            CommissionCategory.objects.get_or_create(slug=category['slug'], defaults={
                'name': category['name'],
                'description': category['description'],
                'is_active': category['is_active'],
            })
        return CommissionCategory.objects.all()


class UserCommissionCategory(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='commission_categories')
    category = models.ForeignKey(CommissionCategory, on_delete=models.CASCADE, related_name='users')
    assigned_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'category')
        verbose_name = 'Attribution Catégorie Commission'
        verbose_name_plural = 'Attributions Catégorie Commission'

    def __str__(self):
        return f"{self.user.username} - {self.category.name}"


class CommissionDistributionLog(models.Model):
    ACTION_CHOICES = (
        ('distribution', 'Distribution de commissions'),
        ('return', 'Retour au système'),
        ('assignment', 'Attribution de catégorie'),
        ('unassignment', 'Retrait de catégorie'),
    )
    admin = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='commission_distribution_logs')
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='commission_distribution_events')
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    amount = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    currency = models.CharField(max_length=10, default='USD')
    description = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Journal de distribution de commission'
        verbose_name_plural = 'Journaux de distribution de commission'
        ordering = ['-created_at']

    def __str__(self):
        user_part = self.user.username if self.user else 'Système'
        return f"{self.get_action_display()} ({self.amount} {self.currency}) -> {user_part}"


class MarketplaceSellerCommission(models.Model):
    COMMISSION_TYPE_CHOICES = (
        ('percent', 'Pourcentage'),
        ('fixed', 'Montant fixe'),
    )
    seller = models.ForeignKey(User, on_delete=models.CASCADE, related_name='marketplace_commissions')
    commission_type = models.CharField(max_length=10, choices=COMMISSION_TYPE_CHOICES, default='percent')
    commission_value = models.DecimalField(max_digits=10, decimal_places=2, default=10.00)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Commission spéciale par vendeur'
        verbose_name_plural = 'Commissions spéciales par vendeur'
        unique_together = ('seller',)

    def __str__(self):
        return f'{self.seller.username} - {self.commission_value} {self.commission_type}'


# -------------------------------
# Synchronisation des copies
# -------------------------------
from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver


@receiver(post_save, sender=Product)
def sync_product_to_reseller_copies(sender, instance, **kwargs):
    """Synchronise les champs essentiels du produit original vers les copies locales des revendeurs."""
    copies = ResellerProduct.objects.filter(original_product=instance)
    for rp in copies:
        copied = rp.copied_product
        if not copied:
            continue
        # Mettre à jour les champs basiques si la copie n'a pas de custom_price
        if not rp.custom_price:
            copied.name = instance.name
            copied.description = instance.description
            copied.price_ht = instance.price_ht
        # Toujours synchroniser le stock et l'image principale
        copied.quantity = instance.quantity
        copied.image = instance.image
        try:
            copied.save()
        except Exception:
            pass


@receiver(post_delete, sender=Product)
def handle_original_product_deleted(sender, instance, **kwargs):
    """Si le produit original est supprimé, marquer les entrées revendeurs et supprimer les copies."""
    copies = ResellerProduct.objects.filter(original_product=instance)
    for rp in copies:
        # Supprimer la copie locale si elle existe
        try:
            if rp.copied_product:
                rp.copied_product.delete()
        except Exception:
            pass
        rp.status = 'removed'
        rp.save()


# -------------------------------
# Avis produit
class ProductReview(models.Model):
    RATING_CHOICES = [(i, str(i)) for i in range(1, 6)]

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    rating = models.PositiveSmallIntegerField(choices=RATING_CHOICES)
    comment = models.TextField(blank=True)
    is_approved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('product', 'user')
        ordering = ['-created_at']
        verbose_name = 'Avis produit'
        verbose_name_plural = 'Avis produits'

    def __str__(self):
        return f"{self.product.name} - {self.user.username} ({self.rating})"

# -------------------------------
# Wallet
# -------------------------------
class Wallet(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    balance = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    balance_usd = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    balance_htg = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    real_estate_loan_balance_htg = models.DecimalField(max_digits=15, decimal_places=2, default=0, help_text="Solde du prêt immobilier en cours - HTG")
    balance_peso = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    balance_eur = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    # Comptes Livreur Multi-Devises (commissions)
    commission_balance_usd = models.DecimalField(max_digits=15, decimal_places=2, default=0, help_text="Comptes Livreur Multi-Devises - USD")
    commission_balance_htg = models.DecimalField(max_digits=15, decimal_places=2, default=0, help_text="Comptes Livreur Multi-Devises - HTG")
    commission_balance_peso = models.DecimalField(max_digits=15, decimal_places=2, default=0, help_text="Comptes Livreur Multi-Devises - PESO")
    commission_balance_eur = models.DecimalField(max_digits=15, decimal_places=2, default=0, help_text="Comptes Livreur Multi-Devises - EUR")
    distribution_balance_usd = models.DecimalField(max_digits=15, decimal_places=2, default=0, help_text="Réserve de distribution de commissions - USD")
    distribution_balance_htg = models.DecimalField(max_digits=15, decimal_places=2, default=0, help_text="Réserve de distribution de commissions - HTG")
    distribution_balance_peso = models.DecimalField(max_digits=15, decimal_places=2, default=0, help_text="Réserve de distribution de commissions - PESO")
    distribution_balance_eur = models.DecimalField(max_digits=15, decimal_places=2, default=0, help_text="Réserve de distribution de commissions - EUR")
    # Commission Peuple - Soldes dédiés
    peuple_commission_balance_usd = models.DecimalField(max_digits=15, decimal_places=2, default=0, help_text="Commission Peuple - USD")
    peuple_commission_balance_htg = models.DecimalField(max_digits=15, decimal_places=2, default=0, help_text="Commission Peuple - HTG")
    peuple_commission_balance_peso = models.DecimalField(max_digits=15, decimal_places=2, default=0, help_text="Commission Peuple - PESO")
    peuple_commission_balance_eur = models.DecimalField(max_digits=15, decimal_places=2, default=0, help_text="Commission Peuple - EUR")
    can_transfer = models.BooleanField(default=False)
    is_blocked = models.BooleanField(default=False)

    def get_balance_in(self, currency):
        from .business_logic import convert_currency
        currency_code = currency.strip().upper()
        if currency_code == 'USD':
            return self.balance
        return convert_currency(self.balance, 'USD', currency_code)

    def repay_real_estate_loan(self, amount_htg):
        amount = amount_htg or Decimal('0')
        loan_balance = self.real_estate_loan_balance_htg or Decimal('0')
        repayment = min(amount, loan_balance)
        if repayment > 0:
            self.real_estate_loan_balance_htg = loan_balance - repayment
            self.save(update_fields=['real_estate_loan_balance_htg'])
        return repayment

    def get_multi_currency_summary(self):
        return {
            'USD': self.balance,
            'HTG': self.get_balance_in('HTG'),
            'PESO': self.get_balance_in('PESO'),
            'EUR': self.get_balance_in('EUR'),
        }

    def get_commission_summary(self):
        return {
            'USD': self.commission_balance_usd,
            'HTG': self.commission_balance_htg,
            'PESO': self.commission_balance_peso,
            'EUR': self.commission_balance_eur,
        }

    def get_commission_multi_currency_summary(self):
        rate = ExchangeRate.objects.filter(is_active=True).order_by('-created_at').first()
        total_usd = self.commission_balance_usd
        if rate and rate.usd_to_htg:
            total_usd += self.commission_balance_htg / rate.usd_to_htg
        if rate and rate.usd_to_peso:
            total_usd += self.commission_balance_peso / rate.usd_to_peso
        if rate and rate.eur_to_usd:
            total_usd += self.commission_balance_eur * rate.eur_to_usd
        return {
            'USD': self.commission_balance_usd,
            'HTG': self.commission_balance_htg,
            'PESO': self.commission_balance_peso,
            'EUR': self.commission_balance_eur,
            'total_usd': total_usd.quantize(Decimal('0.01')),
        }

    def get_distribution_summary(self):
        return {
            'USD': self.distribution_balance_usd,
            'HTG': self.distribution_balance_htg,
            'PESO': self.distribution_balance_peso,
            'EUR': self.distribution_balance_eur,
        }

    def get_peuple_commission_summary(self):
        return {
            'USD': self.peuple_commission_balance_usd,
            'HTG': self.peuple_commission_balance_htg,
            'PESO': self.peuple_commission_balance_peso,
            'EUR': self.peuple_commission_balance_eur,
        }

    def credit_peuple_commission(self, amount, currency='USD'):
        currency = currency.strip().upper()
        field_name = f'peuple_commission_balance_{currency.lower()}'
        if hasattr(self, field_name):
            current = getattr(self, field_name) or Decimal('0')
            setattr(self, field_name, current + amount)
            self.save(update_fields=[field_name])
        return self

    def credit_commission(self, amount, currency='USD'):
        currency = currency.strip().upper()
        field_name = f'commission_balance_{currency.lower()}'
        if hasattr(self, field_name):
            current = getattr(self, field_name) or Decimal('0')
            setattr(self, field_name, current + amount)
            self.save(update_fields=[field_name])
        return self

    def credit_distribution(self, amount, currency='USD'):
        currency = currency.strip().upper()
        field_name = f'distribution_balance_{currency.lower()}'
        if hasattr(self, field_name):
            current = getattr(self, field_name) or Decimal('0')
            setattr(self, field_name, current + amount)
            self.save(update_fields=[field_name])
        return self

    def transfer_distribution_to_commission(self, currency='USD', amount=None):
        currency = currency.strip().upper()
        distribution_field = f'distribution_balance_{currency.lower()}'
        commission_field = f'commission_balance_{currency.lower()}'
        if not hasattr(self, distribution_field) or not hasattr(self, commission_field):
            return Decimal('0')
        current_distribution = getattr(self, distribution_field) or Decimal('0')
        transfer_amount = current_distribution if amount is None else min(current_distribution, amount)
        if transfer_amount <= 0:
            return Decimal('0')
        current_commission = getattr(self, commission_field) or Decimal('0')
        setattr(self, commission_field, current_commission + transfer_amount)
        setattr(self, distribution_field, current_distribution - transfer_amount)
        self.save(update_fields=[distribution_field, commission_field])
        return transfer_amount

class ChatGroup(models.Model):
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    participants = models.ManyToManyField(User, related_name='chat_groups', blank=True)
    description = models.TextField(blank=True, default='')
    is_global = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Groupe de chat'
        verbose_name_plural = 'Groupes de chat'

    def __str__(self):
        return self.name

    @staticmethod
    def get_global_group():
        group, created = ChatGroup.objects.get_or_create(
            slug='marche-mondial-sdi',
            defaults={
                'name': 'Marché Mondial SDI',
                'description': 'Groupe principal de discussion pour tous les utilisateurs',
                'is_global': True,
            }
        )
        if created:
            group.participants.set(User.objects.filter(is_active=True))
        return group

    def add_participant(self, user):
        if user and user.is_active:
            self.participants.add(user)
        return self

class ChatMessage(models.Model):
    group = models.ForeignKey(ChatGroup, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='chat_messages')
    content = models.TextField(blank=True)
    image = models.ImageField(upload_to='chat/messages/%Y/%m/', blank=True, null=True)
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True, related_name='shared_in_messages')
    is_system = models.BooleanField(default=False)
    is_advertisement = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'Message de chat'
        verbose_name_plural = 'Messages de chat'

    def __str__(self):
        author = self.sender.username if self.sender else 'Système'
        return f"[{self.group.name}] {author}: {self.content[:40]}"

    def is_read_by(self, user):
        if not user or user.is_anonymous:
            return False
        if hasattr(self, 'read_by_user'):
            return bool(self.read_by_user)
        return self.read_receipts.filter(user=user).exists()

class ChatMessageRead(models.Model):
    message = models.ForeignKey(ChatMessage, on_delete=models.CASCADE, related_name='read_receipts')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chat_message_reads')
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('message', 'user')
        verbose_name = 'Lecture de message'
        verbose_name_plural = 'Lectures de messages'

    def __str__(self):
        return f"{self.user.username} a lu le message #{self.message.id}"


class PrivateConversation(models.Model):
    user1 = models.ForeignKey(User, on_delete=models.CASCADE, related_name='private_conversations_as_user1')
    user2 = models.ForeignKey(User, on_delete=models.CASCADE, related_name='private_conversations_as_user2')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('user1', 'user2')
        ordering = ['-updated_at']
        verbose_name = 'Conversation privée'
        verbose_name_plural = 'Conversations privées'

    def __str__(self):
        return f"Conversation privée : {self.user1.username} / {self.user2.username}"

    @staticmethod
    def get_or_create(user_a, user_b):
        if user_a.id < user_b.id:
            user1, user2 = user_a, user_b
        else:
            user1, user2 = user_b, user_a
        conversation, created = PrivateConversation.objects.get_or_create(
            user1=user1,
            user2=user2,
        )
        return conversation, created

    def other_user(self, user):
        return self.user2 if self.user1 == user else self.user1

    def latest_message(self):
        return self.messages.order_by('-created_at').first()

    def unread_count_for(self, user):
        return self.messages.filter(receiver=user, is_read=False).count()


class PrivateMessage(models.Model):
    conversation = models.ForeignKey(PrivateConversation, on_delete=models.CASCADE, related_name='messages')
    sender = models.ForeignKey(User, on_delete=models.CASCADE, related_name='private_sent_messages')
    receiver = models.ForeignKey(User, on_delete=models.CASCADE, related_name='private_received_messages')
    content = models.TextField(blank=True)
    image = models.ImageField(upload_to='private_chat/%Y/%m/', blank=True, null=True)
    product = models.ForeignKey(Product, on_delete=models.SET_NULL, null=True, blank=True, related_name='private_messages')
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at']
        verbose_name = 'Message privé'
        verbose_name_plural = 'Messages privés'

    def __str__(self):
        return f"{self.sender.username} -> {self.receiver.username} : {self.content[:40]}"

# -------------------------------
# Commandes / Orders
# -------------------------------
class Order(models.Model):
    buyer = models.ForeignKey(User, on_delete=models.CASCADE, related_name="orders")
    total_amount = models.DecimalField(max_digits=15, decimal_places=2, help_text="Montant total en USD (devise interne)")
    delivery_address = models.TextField()
    buyer_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    buyer_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    buyer_address_details = models.TextField(blank=True, null=True)  # Adresse détaillée avec instructions
    distance_km = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)  # Distance en km
    date_achat = models.DateTimeField(default=timezone.now, editable=False)
    product_name = models.CharField(max_length=255, blank=True, null=True)
    payment_method_choices = (
        ("htg_wallet", "HTG - MicroSDICash / MonCash / NatCash"),
        ("htg_moncash", "HTG - MonCash"),
        ("htg_natcash", "HTG - NatCash"),
        ("htg_cod", "HTG - Cash à la livraison"),
        ("htg_transfer", "HTG - Virement local HTG"),
        ("dop_tpag", "DOP - tPago"),
        ("dop_local_transfer", "DOP - Virement local DOP"),
        ("eur_card", "EUR - Carte Visa/Mastercard"),
        ("eur_paypal", "EUR - PayPal"),
        ("int_card", "International - Carte Visa/Mastercard"),
        ("int_paypal", "International - PayPal"),
    )
    payment_method = models.CharField(max_length=50, choices=payment_method_choices, default="htg_wallet")
    payment_status = models.CharField(
        max_length=20,
        choices=(
            ("pending", "En attente"),
            ("approved", "Confirmé"),
            ("failed", "Échoué"),
        ),
        default="pending"
    )
    blocked_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    status_choices = (("pending","Pending"),("paid","Paid"),("awaiting_delivery","Awaiting Delivery"),("delivered","Delivered"))
    status = models.CharField(max_length=20, choices=status_choices, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)
    delivery_estimated_at = models.DateTimeField(null=True, blank=True)
    date_reception_confirmee = models.DateTimeField(null=True, blank=True)
    timer_hidden = models.BooleanField(default=False)
    
    # Confirmation fields
    buyer_confirmed_delivery = models.BooleanField(default=False, help_text="L'acheteur a confirmé la réception")
    driver_confirmed_delivery = models.BooleanField(default=False, help_text="Le livreur a confirmé la livraison")
    buyer_confirmed_at = models.DateTimeField(null=True, blank=True, help_text="Moment où l'acheteur a confirmé")
    driver_confirmed_at = models.DateTimeField(null=True, blank=True, help_text="Moment où le livreur a confirmé")
    admin_notified = models.BooleanField(default=False, help_text="L'admin a été notifié de la livraison")
    admin_notification_sent_at = models.DateTimeField(null=True, blank=True)
    
    def __str__(self):
        return f"Order #{self.id} - {self.buyer.username}"

class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField()
    price_ht = models.DecimalField(max_digits=15, decimal_places=2, help_text="Prix en USD (devise interne)")

# -------------------------------
# Transaction
# -------------------------------
class Transaction(models.Model):
    sender = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="sent_transactions")
    receiver = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="received_transactions")
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    currency = models.CharField(max_length=10, default='HTG')
    type = models.CharField(max_length=50)  # transfer, recharge, admin_add
    status = models.CharField(max_length=50, default="pending")  # pending, approved, rejected
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def type_display(self):
        return self.type.replace('_', ' ').title()

class TransferCommissionTier(models.Model):
    currency = models.CharField(max_length=10, default='HTG')
    min_amount = models.DecimalField(max_digits=15, decimal_places=2)
    max_amount = models.DecimalField(max_digits=15, decimal_places=2)
    total_fee = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    system_fee = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    agent_fee = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    description = models.CharField(max_length=255, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Tranche Commission Transfert'
        verbose_name_plural = 'Tranches Commission Transfert'
        ordering = ['min_amount']

    def __str__(self):
        return f"{self.description or f'{self.min_amount}-{self.max_amount} {self.currency}'}"

class Transfer(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('success', 'Success'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled'),
    )
    ACCOUNT_SOURCE_CHOICES = (
        ('principal', 'Solde Principal'),
        ('micro_device', 'MicroSDI Multi-appareils'),
    )
    CURRENCY_CHOICES = (
        ('USD', 'USD'),
        ('HTG', 'HTG'),
        ('EUR', 'EUR'),
        ('DOP', 'DOP'),
    )

    transaction_id = models.CharField(max_length=40, unique=True, blank=True)
    sender = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='sent_transfers')
    receiver = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='received_transfers')
    sender_account_type = models.CharField(max_length=30, choices=ACCOUNT_SOURCE_CHOICES, default='principal')
    currency = models.CharField(max_length=10, choices=CURRENCY_CHOICES, default='USD')
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    fee = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    system_fee = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    agent_fee = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    notes = models.TextField(blank=True, null=True)

    def save(self, *args, **kwargs):
        if not self.transaction_id:
            self.transaction_id = f"TR-{uuid.uuid4().hex[:12].upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        sender_name = self.sender.username if self.sender else 'Inconnu'
        receiver_name = self.receiver.username if self.receiver else 'Inconnu'
        return f"Transfer {self.transaction_id} - {sender_name} → {receiver_name} ({self.amount} {self.currency})"

class TransferReceipt(models.Model):
    ROLE_CHOICES = (
        ('sender', 'Expéditeur'),
        ('receiver', 'Destinataire'),
        ('admin', 'Administrateur'),
        ('agent', 'Agent'),
    )

    transfer = models.ForeignKey(Transfer, on_delete=models.CASCADE, related_name='receipts')
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='transfer_receipts')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    receipt_number = models.CharField(max_length=100, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"Reçu {self.receipt_number} - {self.user.username} ({self.role})"

class TransferLog(models.Model):
    transfer = models.ForeignKey(Transfer, on_delete=models.CASCADE, related_name='logs')
    action = models.CharField(max_length=100)
    details = models.TextField(blank=True, null=True)
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='transfer_logs')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.transfer.transaction_id} - {self.action}"

class TransferNotification(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('sent', 'Sent'),
        ('failed', 'Failed'),
    )

    transfer = models.ForeignKey(Transfer, on_delete=models.CASCADE, related_name='notifications')
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='transfer_notifications')
    title = models.CharField(max_length=255)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Notification {self.title} -> {self.recipient.username}"

class AdminAddTransaction(Transaction):
    class Meta:
        proxy = True
        verbose_name = "Ajout d'argent"
        verbose_name_plural = "Ajouts d'argent"
        ordering = ['-created_at']

# -------------------------------
# Agent
# -------------------------------
class Agent(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    is_active = models.BooleanField(default=True)

# -------------------------------
# Catégories
# -------------------------------
class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True, blank=True)
    description = models.TextField(blank=True)
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='children')
    image = models.ImageField(upload_to='categories/', blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Catégorie'
        verbose_name_plural = 'Catégories'

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base_slug = slugify(self.name) or 'categorie'
            slug = base_slug
            counter = 1
            while Category.objects.filter(slug=slug).exclude(pk=self.pk).exists():
                slug = f"{base_slug}-{counter}"
                counter += 1
            self.slug = slug
        super().save(*args, **kwargs)

    def get_full_path(self):
        """Retourne le chemin complet de la catégorie (parent > enfant)"""
        if self.parent:
            return f"{self.parent.get_full_path()} > {self.name}"
        return self.name

    def get_products_count(self):
        """Retourne le nombre de produits dans cette catégorie et ses sous-catégories"""
        count = self.products.filter(quantity__gt=0).count()
        for child in self.children.filter(is_active=True):
            count += child.get_products_count()
        return count

# -------------------------------
# Panier / Cart
# -------------------------------
class Cart(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def get_total_price(self):
        return sum(item.get_total_price() for item in self.items.all())

    def get_total_items(self):
        return sum(item.quantity for item in self.items.all())

class CartItem(models.Model):
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity = models.PositiveIntegerField(default=1)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('cart', 'product')

    def get_total_price(self):
        return self.product.price_ht * self.quantity

# -------------------------------
# Employé Livraison
# -------------------------------
class DeliveryEmployee(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    identifier = models.CharField(max_length=50, unique=True)
    wallet_balance = models.DecimalField(max_digits=15, decimal_places=2, default=0.0)
    current_location = models.CharField(max_length=200, blank=True, null=True)
    current_latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    current_longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    assigned_zone = models.CharField(max_length=100)  # zone obligatoire
    is_available = models.BooleanField(default=True)
    last_location_update = models.DateTimeField(null=True, blank=True)
    vehicle_type = models.CharField(max_length=50, choices=(
        ('bike', 'Vélo'),
        ('scooter', 'Scooter'),
        ('car', 'Voiture'),
        ('truck', 'Camionnette')
    ), default='bike')
    max_delivery_radius = models.PositiveIntegerField(default=10)  # en km
    rating = models.DecimalField(max_digits=3, decimal_places=2, default=5.0)
    total_deliveries = models.PositiveIntegerField(default=0)
    successful_deliveries = models.PositiveIntegerField(default=0)

    def update_location(self, latitude, longitude, location_name=None):
        """Mettre à jour la position actuelle"""
        self.current_latitude = latitude
        self.current_longitude = longitude
        if location_name:
            self.current_location = location_name
        self.last_location_update = timezone.now()
        self.save()

    def get_success_rate(self):
        """Calculer le taux de réussite des livraisons"""
        if self.total_deliveries == 0:
            return 100.0
        return (self.successful_deliveries / self.total_deliveries) * 100

    def is_within_radius(self, target_lat, target_lng):
        """Vérifier si une position cible est dans le rayon de livraison"""
        if not self.current_latitude or not self.current_longitude:
            return False

        # Calcul de distance approximative (formule de Haversine simplifiée)
        from math import radians, sin, cos, sqrt, atan2

        lat1, lon1 = radians(float(self.current_latitude)), radians(float(self.current_longitude))
        lat2, lon2 = radians(float(target_lat)), radians(float(target_lng))

        dlat = lat2 - lat1
        dlon = lon2 - lon1

        a = sin(dlat/2)**2 + cos(lat1) * cos(lat2) * sin(dlon/2)**2
        c = 2 * atan2(sqrt(a), sqrt(1-a))

        distance = 6371 * c  # Rayon terrestre en km
        return distance <= self.max_delivery_radius

# -------------------------------
# Journal d'audit
# -------------------------------
class AuditLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name="audit_logs")
    action = models.CharField(max_length=100)  # ex: 'wallet_balance_change', 'order_status_update'
    details = models.TextField()  # JSON ou texte descriptif
    timestamp = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
# -------------------------------
# Dépôts MicrosDiCash et entités associées
# -------------------------------

class DepositCommissionConfig(models.Model):
    """Configuration des commissions pour les dépôts MicrosDiCash"""
    TYPE_CHOICES = (
        ('pourcentage', 'Pourcentage (%)'),
        ('fixe', 'Montant fixe'),
    )

    currency = models.CharField(max_length=3, choices=[('USD', 'USD'), ('HTG', 'HTG'), ('DOP', 'DOP'), ('EUR', 'EUR')], unique=True)
    commission_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='pourcentage')
    commission_value = models.DecimalField(max_digits=10, decimal_places=2, default=0, help_text="Valeur de commission (% ou montant fixe)")

    min_deposit = models.DecimalField(max_digits=15, decimal_places=2, default=0, help_text="Dépôt minimum")
    max_deposit = models.DecimalField(max_digits=15, decimal_places=2, default=999999, help_text="Dépôt maximum")

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name = 'Configuration Commission Dépôt'
        verbose_name_plural = 'Configurations Commissions Dépôt'
        ordering = ['currency']

    def __str__(self):
        return f"{self.currency} - {self.commission_value} ({self.get_commission_type_display()})"

    def calculate_commission(self, amount):
        """Calcule la commission selon le type et la valeur"""
        from decimal import Decimal
        if not self.is_active:
            return Decimal('0')

        amount = Decimal(str(amount))

        if self.commission_type == 'pourcentage':
            return (amount * Decimal(str(self.commission_value)) / Decimal('100')).quantize(Decimal('0.01'))
        else:  # fixe
            return Decimal(str(self.commission_value))


class Deposit(models.Model):
    """Transactions de dépôt via agents MicrosDiCash"""
    STATUS_CHOICES = (
        ('pending', 'En attente de confirmation'),
        ('confirmed', 'Confirmé'),
        ('rejected', 'Rejeté'),
        ('completed', 'Complété'),
    )

    agent = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='deposits_made', limit_choices_to={'is_agent': True})
    client = models.ForeignKey(User, on_delete=models.CASCADE, related_name='deposits_received')

    amount = models.DecimalField(max_digits=15, decimal_places=2, help_text="Montant du dépôt")
    currency = models.CharField(max_length=3, choices=[('USD', 'USD'), ('HTG', 'HTG'), ('DOP', 'DOP'), ('EUR', 'EUR')])

    commission = models.DecimalField(max_digits=15, decimal_places=2, default=0, help_text="Commission de l'agent")
    tikane_deposit = models.BooleanField(default=False, verbose_name='Dépôt Ti Kanè')
    tikane_account = models.ForeignKey('TiKaneAccount', on_delete=models.SET_NULL, null=True, blank=True, related_name='tikane_deposits')

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    reference = models.CharField(max_length=50, unique=True, blank=True, help_text="Référence unique du dépôt")

    confirmed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='deposits_confirmed')
    confirmed_at = models.DateTimeField(null=True, blank=True)

    rejection_reason = models.TextField(blank=True, help_text="Raison du rejet si applicable")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Dépôt MicrosDiCash'
        verbose_name_plural = 'Dépôts MicrosDiCash'
        ordering = ['-created_at']

    def __str__(self):
        agent_name = self.agent.username if self.agent else 'N/A'
        return f"Dépôt {self.amount} {self.currency} - {self.client.username} par {agent_name}"

    def save(self, *args, **kwargs):
        import uuid
        if not self.reference:
            self.reference = f"MDC{uuid.uuid4().hex[:10].upper()}"
        super().save(*args, **kwargs)


class AgentCommission(models.Model):
    agent = models.ForeignKey(User, on_delete=models.CASCADE, related_name='agent_commissions')
    deposit = models.ForeignKey(Deposit, on_delete=models.CASCADE, related_name='agent_commissions')
    commission_amount = models.DecimalField(max_digits=15, decimal_places=2)
    source_account = models.CharField(max_length=100, blank=True, null=True)
    credited = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)


class DepositReceipt(models.Model):
    receipt_number = models.CharField(max_length=64, unique=True)
    client = models.ForeignKey(User, on_delete=models.CASCADE, related_name='deposit_receipts')
    agent = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='issued_deposit_receipts')
    deposit = models.ForeignKey(Deposit, on_delete=models.SET_NULL, null=True, blank=True, related_name='deposit_receipt')
    content = models.TextField(blank=True)
    pdf = models.FileField(upload_to='deposit_receipts/', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Reçu Dépôt'
        verbose_name_plural = 'Reçus Dépôt'
        ordering = ['-created_at']

    def __str__(self):
        return f"Reçu {self.receipt_number} - {self.client.username}"

    def generate_content(self):
        client_name = f"{self.client.first_name or ''} {self.client.last_name or ''}".strip() or self.client.username
        previous_balance = ''
        current_balance = None
        current_balance_display = 'N/A'
        if self.deposit and self.deposit.client and hasattr(self.deposit.client, 'wallet'):
            wallet_field = 'balance' if self.deposit.currency == 'USD' else f"balance_{self.deposit.currency.lower()}"
            current_balance = getattr(self.deposit.client.wallet, wallet_field, None)
            if current_balance is not None:
                previous_balance = f"{(current_balance - self.deposit.amount):.2f} {self.deposit.currency}"
                current_balance_display = f"{current_balance:.2f}"
        self.content = (
            f"MicroSDICash - Reçu Bancaire Sécurisé\n"
            f"Client : {client_name}\n"
            f"ID Client : {self.client.account_code}\n"
            f"Numéro de compte : {self.client.account_code}\n"
            f"Ancien Solde : {previous_balance}\n"
            f"Montant Déposé : {self.deposit.amount:.2f} {self.deposit.currency}\n"
            f"Commission agent : {self.deposit.commission:.2f} {self.deposit.currency}\n"
            f"Destination : {'Ti Kanè Digital' if self.deposit and self.deposit.tikane_deposit else 'Portefeuille principal'}\n"
            f"Nouveau Solde : {current_balance_display} {self.deposit.currency if current_balance is not None else ''}\n"
            f"Type : {'Dépôt Ti Kanè' if self.deposit and self.deposit.tikane_deposit else 'Dépôt Principal'}\n"
            f"Date : {self.created_at.strftime('%d %B %Y')}\n"
            f"Heure : {self.created_at.strftime('%H:%M')}\n"
            f"Numéro de Reçu : {self.receipt_number}\n"
            f"Signature : MicroSDICash • Sécurité • Innovation\n"
        )


class TransactionLog(models.Model):
    transaction_type = models.CharField(max_length=64)
    transaction_ref = models.CharField(max_length=128, blank=True, null=True)
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    details = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)


class AdminSetting(models.Model):
    key = models.CharField(max_length=128, unique=True)
    value = models.TextField(blank=True, null=True)
    updated_at = models.DateTimeField(auto_now=True)


class DepositLimit(models.Model):
    min_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    max_amount = models.DecimalField(max_digits=15, decimal_places=2, default=1000000)
    daily_limit = models.DecimalField(max_digits=15, decimal_places=2, default=5000000)
    per_agent_daily_limit = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class CommissionRule(models.Model):
    agent = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='commission_rules')
    min_amount = models.DecimalField(max_digits=15, decimal_places=2)
    max_amount = models.DecimalField(max_digits=15, decimal_places=2)
    commission_amount = models.DecimalField(max_digits=15, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        agent_name = self.agent.username if self.agent else 'Global'
        return f"{agent_name}: {self.min_amount}-{self.max_amount} => {self.commission_amount}"

# -------------------------------
# Assignation Livraison
# -------------------------------
class DeliveryAssignment(models.Model):
    employee = models.ForeignKey(DeliveryEmployee, on_delete=models.CASCADE)
    order = models.ForeignKey(Order, on_delete=models.CASCADE)
    delivery_zone = models.CharField(max_length=100, blank=True, null=True)
    seller_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    seller_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    buyer_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    buyer_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    current_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    current_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    driver_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)  # Position actuelle du livreur
    driver_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)  # Position actuelle du livreur
    driver_address_details = models.TextField(blank=True, null=True)  # Adresse détaillée du livreur
    status_choices = (
        ("assigned","Assigned"),
        ("picked_up","Picked Up"),
        ("in_transit","In Transit"),
        ("arrived","Arrived at Destination"),
        ("delivered","Delivered"),
        ("failed","Failed Delivery"),
        ("returned","Returned")
    )
    status = models.CharField(max_length=20, choices=status_choices, default="assigned")
    assigned_at = models.DateTimeField(auto_now_add=True)
    picked_up_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    estimated_delivery_time = models.DateTimeField(null=True, blank=True)
    actual_delivery_time = models.DateTimeField(null=True, blank=True)
    delivery_notes = models.TextField(blank=True, null=True)
    customer_feedback = models.TextField(blank=True, null=True)
    rating = models.PositiveIntegerField(null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)])
    
    # Confirmation fields
    driver_confirmed_delivery = models.BooleanField(default=False, help_text="Le livreur a confirmé la livraison")
    driver_confirmed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('employee', 'order')

    def save(self, *args, **kwargs):
        # Auto-update timestamps based on status
        if self.status == 'picked_up' and not self.picked_up_at:
            self.picked_up_at = timezone.now()
        elif self.status == 'delivered' and not self.delivered_at:
            self.delivered_at = timezone.now()
            self.actual_delivery_time = timezone.now()
        super().save(*args, **kwargs)

# -------------------------------
# Suivi GPS et étapes de livraison
# -------------------------------
class DeliveryTracking(models.Model):
    assignment = models.ForeignKey(DeliveryAssignment, on_delete=models.CASCADE, related_name='tracking_updates')
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    location_name = models.CharField(max_length=200, blank=True, null=True)
    status_update = models.CharField(max_length=100)  # Description de l'étape
    timestamp = models.DateTimeField(auto_now_add=True)
    estimated_eta = models.DateTimeField(null=True, blank=True)  # ETA estimé

    class Meta:
        ordering = ['-timestamp']

# -------------------------------
# Notifications de livraison
# -------------------------------
class DeliveryNotification(models.Model):
    assignment = models.ForeignKey(DeliveryAssignment, on_delete=models.CASCADE, related_name='notifications')
    recipient = models.ForeignKey(User, on_delete=models.CASCADE)  # Client ou employé
    notification_type = models.CharField(max_length=50)  # 'status_update', 'delay', 'arrival', 'delivered'
    title = models.CharField(max_length=200)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)

# -------------------------------
# Notifications persistantes avec sonnerie
# -------------------------------
class PersistentNotification(models.Model):
    """
    Notifications persistantes qui sonnent jusqu'à ce qu'elles soient lues.
    Utilisées pour les assignations de livraison importantes.
    """
    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name='persistent_notifications')
    title = models.CharField(max_length=200)
    message = models.TextField()
    notification_type = models.CharField(max_length=50)  # 'delivery_assigned', 'admin_alert', etc.
    related_assignment = models.ForeignKey(DeliveryAssignment, on_delete=models.CASCADE, null=True, blank=True)
    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_sound_at = models.DateTimeField(null=True, blank=True)  # Dernière fois que la notification a sonné
    sound_interval_minutes = models.PositiveIntegerField(default=1)  # Intervalle entre les sons (minutes)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Notification persistante'
        verbose_name_plural = 'Notifications persistantes'

    def __str__(self):
        return f"{self.recipient.username}: {self.title}"

    def mark_as_read(self):
        """Marquer la notification comme lue"""
        self.is_read = True
        self.read_at = timezone.now()
        self.save()

    def get_sound_interval_seconds(self):
        """Retourner l'intervalle de son en secondes."""
        # Pour les notifications admin critiques, sonner toutes les 30 secondes.
        if self.notification_type in ['admin_delivery_assigned', 'delivery_confirmed', 'delivery_completed']:
            return 30
        return self.sound_interval_minutes * 60

    def should_sound(self):
        """Vérifier si la notification devrait sonner maintenant"""
        if self.is_read:
            return False

        if not self.last_sound_at:
            return True  # Première fois, doit sonner

        # Vérifier l'intervalle en fonction du type de notification.
        time_since_last_sound = timezone.now() - self.last_sound_at
        return time_since_last_sound.total_seconds() >= self.get_sound_interval_seconds()

    def update_sound_timestamp(self):
        """Mettre à jour le timestamp du dernier son"""
        self.last_sound_at = timezone.now()
        self.save()

# -------------------------------
# Demandes de retour
# -------------------------------
class ReturnRequest(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='return_requests')
    customer = models.ForeignKey(User, on_delete=models.CASCADE)
    reason = models.CharField(max_length=100, choices=(
        ('damaged', 'Produit endommagé'),
        ('wrong_item', 'Mauvais produit reçu'),
        ('not_as_described', 'Produit différent de la description'),
        ('defective', 'Produit défectueux'),
        ('changed_mind', 'Changement d\'avis'),
        ('other', 'Autre')
    ))
    description = models.TextField()
    status_choices = (
        ('pending', 'En attente'),
        ('approved', 'Approuvé'),
        ('rejected', 'Rejeté'),
        ('refunded', 'Remboursé'),
        ('returned', 'Retourné')
    )
    status = models.CharField(max_length=20, choices=status_choices, default='pending')
    requested_at = models.DateTimeField(auto_now_add=True)
    processed_at = models.DateTimeField(null=True, blank=True)
    refund_amount = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    admin_notes = models.TextField(blank=True, null=True)

    def approve_return(self):
        """Approuver la demande de retour"""
        self.status = 'approved'
        self.processed_at = timezone.now()
        self.save()

    def reject_return(self):
        """Rejeter la demande de retour"""
        self.status = 'rejected'
        self.processed_at = timezone.now()
        self.save()

    def process_refund(self, amount=None):
        """Traiter le remboursement"""
        if amount is None:
            amount = self.order.total_amount
        self.refund_amount = amount
        self.status = 'refunded'
        self.processed_at = timezone.now()
        self.save()

        # Créer une transaction de remboursement
        Transaction.objects.create(
            sender=None,  # Système
            receiver=self.customer,
            amount=amount,
            type='refund',
            status='approved'
        )

# -------------------------------
# Paramètres système
# -------------------------------
class SystemSettings(models.Model):
    banner_enabled = models.BooleanField(default=True, verbose_name='Activer le système de bannière')
    banner_expand_enabled = models.BooleanField(default=False, verbose_name='Autoriser l’agrandissement du Banner')
    banner_normal_height = models.PositiveIntegerField(default=150, verbose_name='Hauteur normale du Banner')
    banner_expanded_height = models.PositiveIntegerField(default=220, verbose_name='Hauteur agrandie du Banner')
    banner_visible_to_admins = models.BooleanField(default=True, verbose_name='Afficher la bannière aux administrateurs')
    principal_banner_visible = models.BooleanField(default=True, verbose_name='Afficher la bannière à l’administrateur principal')
    enable_role_management = models.BooleanField(default=False, verbose_name="Activer la gestion des rôles et permissions")
    enable_financial_audit = models.BooleanField(default=False, verbose_name="Activer la traçabilité financière")
    enable_alerts = models.BooleanField(default=False, verbose_name="Activer le système d'alertes intelligentes")
    enable_rollback = models.BooleanField(default=False, verbose_name="Activer le système de rollback")
    enable_dispute_management = models.BooleanField(default=False, verbose_name="Activer la gestion des litiges")
    enable_cybersecurity = models.BooleanField(default=False, verbose_name="Activer la surveillance cybersécurité")
    emergency_lockdown = models.BooleanField(default=False, verbose_name="Mode verrouillage d'urgence")
    microsdicash_account_name = models.CharField(
        max_length=255,
        default='MicroSDICash',
        verbose_name='Nom du compte MicroSDICash'
    )
    microsdicash_account_number = models.CharField(
        max_length=50,
        default='44481629',
        verbose_name='Numéro du compte MicroSDICash'
    )
    microsdicash_account_phone = models.CharField(
        max_length=50,
        blank=True,
        default='',
        verbose_name='Téléphone du compte MicroSDICash'
    )
    microsdicash_payment_instructions = models.TextField(
        blank=True,
        default='Rechargez votre compte via l’administration SDI Marché Mondial ou via un agent local. Vous pouvez aussi envoyer l’argent sur MonCash et télécharger le reçu ici.',
        verbose_name='Instructions de paiement MicroSDICash'
    )
    # Round-robin pour assignation livreurs
    last_assigned_delivery_employee_index = models.PositiveIntegerField(default=0, help_text="Index du dernier livreur assigné (round-robin)")

    class Meta:
        verbose_name = "Paramètre système"
        verbose_name_plural = "Paramètres système"


class SecurityIncident(models.Model):
    """Enregistre les alertes et incidents de cybersécurité"""
    INCIDENT_TYPE_CHOICES = [
        ('brute_force', 'Brute force'),
        ('injection', 'Injection SQL / XSS'),
        ('suspicious_access', 'Accès suspect'),
        ('malware', 'Malware / fichier malveillant'),
        ('other', 'Autre'),
    ]
    SEVERITY_CHOICES = [
        ('info', 'Info'),
        ('warning', 'Alerte'),
        ('critical', 'Critique'),
    ]

    incident_type = models.CharField(max_length=50, choices=INCIDENT_TYPE_CHOICES, default='other')
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='warning')
    description = models.TextField(blank=True)
    source_ip = models.CharField(max_length=50, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    resolved = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'Incident de cybersécurité'
        verbose_name_plural = 'Incidents de cybersécurité'
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.get_severity_display()}] {self.get_incident_type_display()} - {self.created_at.strftime('%d/%m/%Y %H:%M')}"


class SecurityEvent(models.Model):
    """Enregistre les événements de sécurité et d'activité pour le tableau de bord"""
    EVENT_TYPE_CHOICES = [
        ('login_success', 'Connexion réussie'),
        ('login_failed', 'Connexion échouée'),
        ('admin_access', 'Accès page admin'),
        ('api_error', 'Erreur API'),
        ('http_4xx', 'Erreur 4xx (client)'),
        ('http_5xx', 'Erreur 5xx (serveur)'),
        ('suspicious_access', 'Accès suspect'),
        ('brute_force', 'Brute force détecté'),
        ('malicious_payload', 'Payload malveillant'),
        ('other', 'Autre'),
    ]

    event_type = models.CharField(max_length=50, choices=EVENT_TYPE_CHOICES, default='other')
    source_ip = models.CharField(max_length=50, blank=True, null=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='security_events')
    path = models.CharField(max_length=255, blank=True, help_text="URL accédée")
    method = models.CharField(max_length=10, blank=True, help_text="GET, POST, PUT, DELETE, etc.")
    status_code = models.IntegerField(blank=True, null=True, help_text="Code HTTP réponse")
    response_time_ms = models.IntegerField(blank=True, null=True, help_text="Temps réponse en ms")
    user_agent = models.CharField(max_length=500, blank=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Événement de sécurité'
        verbose_name_plural = 'Événements de sécurité'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['source_ip', '-created_at']),
            models.Index(fields=['event_type', '-created_at']),
        ]

    def __str__(self):
        return f"{self.get_event_type_display()} - {self.source_ip} - {self.created_at.strftime('%d/%m/%Y %H:%M')}"


class IPBlocklist(models.Model):
    """Liste des IPs à bloquer"""
    ip_address = models.CharField(max_length=50, unique=True)
    reason = models.CharField(max_length=255, blank=True, help_text="Raison du blocage")

    class Meta:
        verbose_name = 'IP bloquée'
        verbose_name_plural = 'IPs bloquées'
        ordering = ['ip_address']

    def __str__(self):
        return self.ip_address


# ==========================================
# SYSTÈME CYBERSÉCURITÉ INTELLIGENT
# ==========================================

class PortMonitoring(models.Model):
    """Surveillance des ports réseau en temps réel"""
    PORT_CHOICES = [
        (80, 'HTTP (80)'),
        (443, 'HTTPS (443)'),
        (22, 'SSH (22)'),
        (3306, 'MySQL (3306)'),
        (8080, 'HTTP Alt (8080)'),
        (8443, 'HTTPS Alt (8443)'),
        (21, 'FTP (21)'),
        (25, 'SMTP (25)'),
        (53, 'DNS (53)'),
        (110, 'POP3 (110)'),
        (143, 'IMAP (143)'),
        (993, 'IMAPS (993)'),
        (995, 'POP3S (995)'),
    ]

    port = models.IntegerField(choices=PORT_CHOICES, unique=True)
    is_open = models.BooleanField(default=False)
    traffic_count = models.IntegerField(default=0)
    suspicious_activity = models.BooleanField(default=False)
    risk_level = models.CharField(max_length=20, choices=[
        ('low', 'Faible'),
        ('medium', 'Moyen'),
        ('high', 'Élevé'),
        ('critical', 'Critique')
    ], default='low')
    last_scan = models.DateTimeField(auto_now=True)
    blocked_connections = models.IntegerField(default=0)

    class Meta:
        verbose_name = 'Surveillance Port'
        verbose_name_plural = 'Surveillance Ports'
        ordering = ['port']

    def __str__(self):
        return f"Port {self.port} - {self.get_risk_level_display()}"


class AIThreatAnalysis(models.Model):
    """Analyse IA des menaces et comportements suspects"""
    THREAT_LEVEL_CHOICES = [
        ('safe', 'Sûr'),
        ('low', 'Faible'),
        ('medium', 'Moyen'),
        ('high', 'Élevé'),
        ('critical', 'Critique'),
    ]

    threat_score = models.FloatField(default=0.0, help_text="Score de menace IA (0-100)")
    threat_level = models.CharField(max_length=20, choices=THREAT_LEVEL_CHOICES, default='safe')
    detected_anomalies = models.JSONField(default=dict, blank=True)
    bot_detections = models.IntegerField(default=0)
    brute_force_attempts = models.IntegerField(default=0)
    sql_injection_attempts = models.IntegerField(default=0)
    xss_attempts = models.IntegerField(default=0)
    suspicious_patterns = models.JSONField(default=dict, blank=True)
    ai_confidence = models.FloatField(default=0.0, help_text="Confiance de l'analyse IA (0-1)")
    last_analysis = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Analyse IA Menaces'
        verbose_name_plural = 'Analyses IA Menaces'

    def __str__(self):
        return f"IA Threat Analysis - Score: {self.threat_score}"


class HoneypotEvent(models.Model):
    """Événements du système honeypot"""
    EVENT_TYPE_CHOICES = [
        ('admin_access', 'Accès faux admin'),
        ('login_attempt', 'Tentative connexion'),
        ('file_upload', 'Upload fichier'),
        ('sql_injection', 'Injection SQL'),
        ('xss_attempt', 'Tentative XSS'),
        ('brute_force', 'Brute force'),
        ('other', 'Autre'),
    ]

    event_type = models.CharField(max_length=50, choices=EVENT_TYPE_CHOICES, default='other')
    source_ip = models.CharField(max_length=50)
    user_agent = models.CharField(max_length=500, blank=True)
    attempted_username = models.CharField(max_length=100, blank=True)
    attempted_password = models.CharField(max_length=100, blank=True)
    payload = models.TextField(blank=True)
    device_info = models.JSONField(default=dict, blank=True)
    geolocation = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    alerted = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'Événement Honeypot'
        verbose_name_plural = 'Événements Honeypot'
        ordering = ['-created_at']

    def __str__(self):
        return f"Honeypot: {self.get_event_type_display()} - {self.source_ip}"


class SecurityAlert(models.Model):
    """Système d'alertes avancées"""
    ALERT_TYPE_CHOICES = [
        ('port_scan', 'Scan de ports'),
        ('brute_force', 'Attaque brute force'),
        ('sql_injection', 'Injection SQL'),
        ('xss', 'Attaque XSS'),
        ('malware', 'Malware détecté'),
        ('honeypot', 'Activation honeypot'),
        ('suspicious_ip', 'IP suspecte'),
        ('high_traffic', 'Trafic élevé'),
        ('system_error', 'Erreur système'),
        ('other', 'Autre'),
    ]

    PRIORITY_CHOICES = [
        ('low', 'Faible'),
        ('medium', 'Moyen'),
        ('high', 'Élevé'),
        ('critical', 'Critique'),
    ]

    alert_type = models.CharField(max_length=50, choices=ALERT_TYPE_CHOICES, default='other')
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='medium')
    title = models.CharField(max_length=200)
    description = models.TextField()
    source_ip = models.CharField(max_length=50, blank=True, null=True)
    affected_system = models.CharField(max_length=100, blank=True)
    resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(blank=True, null=True)
    resolved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    telegram_sent = models.BooleanField(default=False)
    email_sent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Alerte Sécurité'
        verbose_name_plural = 'Alertes Sécurité'
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.get_priority_display()}] {self.title}"


class SecurityLog(models.Model):
    """Logs temps réel du système de sécurité"""
    LOG_LEVEL_CHOICES = [
        ('debug', 'Debug'),
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('error', 'Error'),
        ('critical', 'Critical'),
    ]

    COMPONENT_CHOICES = [
        ('auth', 'Authentification'),
        ('api', 'API'),
        ('admin', 'Administration'),
        ('network', 'Réseau'),
        ('honeypot', 'Honeypot'),
        ('ai', 'IA'),
        ('firewall', 'Firewall'),
        ('other', 'Autre'),
    ]

    level = models.CharField(max_length=20, choices=LOG_LEVEL_CHOICES, default='info')
    component = models.CharField(max_length=50, choices=COMPONENT_CHOICES, default='other')
    message = models.TextField()
    source_ip = models.CharField(max_length=50, blank=True, null=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Log Sécurité'
        verbose_name_plural = 'Logs Sécurité'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['level', '-created_at']),
            models.Index(fields=['component', '-created_at']),
        ]

    def __str__(self):
        return f"[{self.get_level_display()}] {self.component}: {self.message[:50]}"


class SecurityMetrics(models.Model):
    """Métriques temps réel du système de sécurité"""
    timestamp = models.DateTimeField(auto_now_add=True)

    # Métriques de base
    active_connections = models.IntegerField(default=0)
    requests_per_minute = models.FloatField(default=0.0)
    blocked_requests = models.IntegerField(default=0)
    suspicious_ips = models.IntegerField(default=0)

    # Métriques IA
    ai_threat_score = models.FloatField(default=0.0)
    bot_detections = models.IntegerField(default=0)
    anomaly_detections = models.IntegerField(default=0)

    # Métriques réseau
    network_traffic = models.BigIntegerField(default=0)  # bytes
    port_scans_detected = models.IntegerField(default=0)

    # Métriques système
    cpu_usage = models.FloatField(default=0.0)
    memory_usage = models.FloatField(default=0.0)
    disk_usage = models.FloatField(default=0.0)

    # Métriques sécurité
    active_alerts = models.IntegerField(default=0)
    resolved_alerts_today = models.IntegerField(default=0)
    honeypot_triggers = models.IntegerField(default=0)

    class Meta:
        verbose_name = 'Métrique Sécurité'
        verbose_name_plural = 'Métriques Sécurité'
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['-timestamp']),
        ]

    def __str__(self):
        return f"Métriques - {self.timestamp.strftime('%d/%m/%Y %H:%M')}"


class AntiBotField(models.Model):
    """Champ honeypot anti-bot pour les formulaires"""
    form_name = models.CharField(max_length=100, help_text="Nom du formulaire (login, register, contact, etc.)")
    field_name = models.CharField(max_length=100, default='website_url', help_text="Nom du champ caché")
    field_label = models.CharField(max_length=200, blank=True, help_text="Label visible si nécessaire")
    is_visible = models.BooleanField(default=False, help_text="Si le champ doit être visible (pour debug)")
    css_classes = models.CharField(max_length=200, blank=True, help_text="Classes CSS pour le champ")
    blocked_submissions = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Champ Anti-Bot'
        verbose_name_plural = 'Champs Anti-Bot'
        unique_together = ['form_name', 'field_name']

    def __str__(self):
        return f"Anti-bot: {self.form_name} - {self.field_name}"


class AntiBotDetection(models.Model):
    """Détections de bots via les champs honeypot"""
    field = models.ForeignKey(AntiBotField, on_delete=models.CASCADE)
    source_ip = models.CharField(max_length=50)
    user_agent = models.CharField(max_length=500, blank=True)
    submitted_value = models.CharField(max_length=500, blank=True)
    form_data = models.JSONField(default=dict, blank=True)
    blocked = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Détection Anti-Bot'
        verbose_name_plural = 'Détections Anti-Bot'
        ordering = ['-created_at']

    def __str__(self):
        return f"Bot détecté: {self.source_ip} - {self.field.form_name}"


class SiteConfiguration(models.Model):
    """Configuration globale du site (logos, titres, etc.)"""
    CONFIGURATION_CHOICES = [
        ('main', 'Logo Principal'),
        ('favicon', 'Favicon'),
        ('footer', 'Logo Footer'),
    ]
    
    config_type = models.CharField(
        max_length=50,
        choices=CONFIGURATION_CHOICES,
        unique=True,
        verbose_name='Type de configuration'
    )
    image = models.ImageField(
        upload_to='site_config/%Y/%m/',
        verbose_name='Image/Logo'
    )
    alt_text = models.CharField(
        max_length=255,
        help_text='Texte alternatif pour l\'image',
        blank=True
    )
    width = models.IntegerField(
        default=200,
        help_text='Largeur en pixels',
        blank=True
    )
    height = models.IntegerField(
        default=60,
        help_text='Hauteur en pixels',
        blank=True
    )
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        related_name='config_updates',
        verbose_name='Modifié par'
    )
    
    class Meta:
        verbose_name = 'Configuration du site'
        verbose_name_plural = 'Configurations du site'
        ordering = ['config_type']
    
    def __str__(self):
        return f"{self.get_config_type_display()} - Mise à jour: {self.updated_at.strftime('%d/%m/%Y %H:%M')}"


class SiteConfigurationPermission(models.Model):
    """Modèle pour gérer les permissions de modification des logos du site"""
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='logo_permission',
        verbose_name='Utilisateur autorisé'
    )
    can_edit_logos = models.BooleanField(
        default=False,
        verbose_name='Autorisé à modifier les logos'
    )
    granted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='granted_logo_permissions',
        verbose_name='Permission accordée par',
        help_text='Admin principal qui a accordé cette permission'
    )
    granted_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name='Date d\'octroi'
    )
    
    class Meta:
        verbose_name = 'Permission de modification des logos'
        verbose_name_plural = 'Permissions de modification des logos'
    
    def __str__(self):
        return f"{self.user.username} - {'Autorisé' if self.can_edit_logos else 'Non autorisé'}"


# -------------------------------
# Demandes de Retrait avec Reçus
# -------------------------------
class WithdrawalRequest(models.Model):
    """Modèle pour tracker les demandes de retrait"""
    STATUS_CHOICES = (
        ('pending', 'En attente de confirmation'),
        ('approved', 'Approuvé'),
        ('rejected', 'Rejeté'),
        ('completed', 'Complété'),
    )
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='withdrawal_requests')
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    currency = models.CharField(max_length=10)
    account_type = models.CharField(max_length=20)  # 'principal' ou 'multidevice'
    fee_total = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    fee_system = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    fee_agent = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    
    # Débitage immédiat
    amount_debited = models.BooleanField(default=False)
    
    # Confirmation admin
    confirmed_at = models.DateTimeField(blank=True, null=True)
    confirmed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='confirmed_withdrawals')
    rejection_reason = models.TextField(blank=True)
    
    # Agent qui a traité le retrait
    processed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='processed_withdrawals',
                                     limit_choices_to={'is_agent': True})
    notes = models.TextField(blank=True, help_text="Commentaires additionnels sur le retrait")
    
    # Reçu
    receipt_generated = models.BooleanField(default=False)
    receipt_sent_to_email = models.BooleanField(default=False)
    receipt_file = models.FileField(upload_to='withdrawal_receipts/', blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Demande de Retrait'
        verbose_name_plural = 'Demandes de Retrait'
        ordering = ['-created_at']

    def __str__(self):
        return f"Retrait {self.amount} {self.currency} - {self.user.username} ({self.status})"


class AdminWithdrawalPermission(models.Model):
    """Permissions pour les admins secondaires à confirmer les retraits"""
    admin = models.OneToOneField(User, on_delete=models.CASCADE, related_name='withdrawal_permission', 
                                 limit_choices_to={'role': 'admin_secondary'})
    can_confirm_withdrawals = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    granted_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='granted_withdrawal_permissions')

    class Meta:
        verbose_name = 'Permission de Confirmation de Retrait'
        verbose_name_plural = 'Permissions de Confirmation de Retrait'

    def __str__(self):
        return f"{self.admin.username} - {'Peut confirmer' if self.can_confirm_withdrawals else 'Ne peut pas confirmer'}"


# -------------------------------
# Contrôle Système - Gestion des Mots de Passe et Permissions Admin
# -------------------------------
class PasswordManagementPermission(models.Model):
    """Modèle pour gérer les permissions d'accès aux mots de passe des utilisateurs"""
    admin = models.ForeignKey(User, on_delete=models.CASCADE, related_name='password_management_permissions', 
                             limit_choices_to={'is_staff': True})
    can_view_passwords = models.BooleanField(default=False, verbose_name="Peut voir les mots de passe")
    can_change_passwords = models.BooleanField(default=False, verbose_name="Peut modifier les mots de passe")
    can_manage_other_admins = models.BooleanField(default=False, verbose_name="Peut gérer les autres admins")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='permission_updates')
    
    class Meta:
        verbose_name = "Permission de Gestion des Mots de Passe"
        verbose_name_plural = "Permissions de Gestion des Mots de Passe"
        unique_together = ('admin',)
    
    def __str__(self):
        return f"Permissions de {self.admin.username}"

# -------------------------------
# Reçus MonCash
# -------------------------------
class Receipt(models.Model):
    """Modèle pour stocker les reçus MonCash téléversés par les utilisateurs"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='receipts')
    receipt_image = models.ImageField(upload_to='receipts/', verbose_name='Image du reçu')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    status_choices = (
        ('pending', 'En attente de vérification'),
        ('approved', 'Approuvé'),
        ('rejected', 'Rejeté'),
    )
    status = models.CharField(max_length=20, choices=status_choices, default='pending')
    admin_notes = models.TextField(blank=True, null=True, verbose_name='Notes administrateur')
    processed_at = models.DateTimeField(null=True, blank=True)
    processed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, 
                                   related_name='processed_receipts', 
                                   limit_choices_to={'role__in': ['super_admin', 'admin_secondary']})

    class Meta:
        verbose_name = "Reçu MonCash"
        verbose_name_plural = "Reçus MonCash"
        ordering = ['-uploaded_at']

    def __str__(self):
        return f"Reçu de {self.user.username} - {self.uploaded_at.strftime('%d/%m/%Y %H:%M')}"

    def approve(self, admin_user, notes=None):
        """Approuver le reçu"""
        self.status = 'approved'
        self.processed_at = timezone.now()
        self.processed_by = admin_user
        if notes:
            self.admin_notes = notes
        self.save()

    def reject(self, admin_user, notes=None):
        """Rejeter le reçu"""
        self.status = 'rejected'
        self.processed_at = timezone.now()
        self.processed_by = admin_user
        if notes:
            self.admin_notes = notes
        self.save()


# ==========================================
# SYSTÈME DE DÉTECTION ET CORRECTION DE FAILLES IA
# ==========================================

class SecurityVulnerability(models.Model):
    """Détection des failles de sécurité"""
    VULNERABILITY_TYPE_CHOICES = [
        ('sql_injection', 'Injection SQL'),
        ('xss', 'Cross-Site Scripting (XSS)'),
        ('csrf', 'Cross-Site Request Forgery (CSRF)'),
        ('brute_force', 'Brute Force'),
        ('weak_auth', 'Authentification faible'),
        ('path_traversal', 'Traversée de répertoires'),
        ('insecure_deserialization', 'Désérialisation non sécurisée'),
        ('sensitive_data_exposure', 'Exposition de données sensibles'),
        ('broken_access_control', 'Contrôle d\'accès cassé'),
        ('security_misconfiguration', 'Mauvaise configuration de sécurité'),
        ('insecure_dependencies', 'Dépendances non sécurisées'),
        ('weak_encryption', 'Chiffrement faible'),
        ('api_vulnerability', 'Vulnérabilité API'),
        ('upload_vulnerability', 'Vulnérabilité upload fichiers'),
        ('jwt_vulnerability', 'Vulnérabilité JWT'),
        ('session_vulnerability', 'Vulnérabilité de session'),
        ('other', 'Autre'),
    ]

    SEVERITY_CHOICES = [
        ('critical', 'Critique'),
        ('high', 'Élevée'),
        ('medium', 'Moyenne'),
        ('low', 'Faible'),
        ('info', 'Information'),
    ]

    STATUS_CHOICES = [
        ('detected', 'Détectée'),
        ('confirmed', 'Confirmée'),
        ('fixing', 'En cours de correction'),
        ('fixed', 'Corrigée'),
        ('verified', 'Vérifiée'),
        ('false_positive', 'Faux positif'),
    ]

    # Identification
    vulnerability_type = models.CharField(max_length=50, choices=VULNERABILITY_TYPE_CHOICES)
    title = models.CharField(max_length=200)
    description = models.TextField()
    severity = models.CharField(max_length=20, choices=SEVERITY_CHOICES, default='medium')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='detected')

    # Localisation
    file_path = models.CharField(max_length=500, blank=True, help_text="Chemin du fichier vulnérable")
    line_number = models.IntegerField(blank=True, null=True, help_text="Numéro de ligne du code")
    route = models.CharField(max_length=255, blank=True, help_text="Route API/URL affectée")
    code_snippet = models.TextField(blank=True, help_text="Extrait de code problématique")

    # Détection
    detection_method = models.CharField(max_length=100, blank=True, help_text="Méthode de détection utilisée")
    ai_confidence = models.FloatField(default=0.0, help_text="Confiance de l'IA (0-1)")
    detected_at = models.DateTimeField(auto_now_add=True)
    detected_by = models.CharField(max_length=50, default='ai_scanner')

    # Correction
    recommended_fix = models.TextField(blank=True, help_text="Correction recommandée par l'IA")
    fix_code = models.TextField(blank=True, help_text="Code de correction suggéré")
    fix_applied_at = models.DateTimeField(blank=True, null=True)
    fix_applied_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='fixed_vulnerabilities')
    fix_notes = models.TextField(blank=True, help_text="Notes sur la correction appliquée")

    # Vérification
    verification_passed = models.BooleanField(default=False)
    verified_at = models.DateTimeField(blank=True, null=True)
    verified_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='verified_vulnerabilities', help_text="Admin qui a vérifié la correction")

    # Métadonnées
    impact_description = models.TextField(blank=True, help_text="Description de l'impact")
    cve_reference = models.CharField(max_length=50, blank=True, help_text="Référence CVE")
    external_reference = models.URLField(blank=True, help_text="Lien vers ressource externe")
    metadata = models.JSONField(default=dict, blank=True)

    # Backup avant correction
    backup_before_fix = models.TextField(blank=True, help_text="Backup du code avant correction")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Vulnérabilité'
        verbose_name_plural = 'Vulnérabilités'
        ordering = ['-detected_at']
        indexes = [
            models.Index(fields=['severity', '-detected_at']),
            models.Index(fields=['status', '-detected_at']),
            models.Index(fields=['vulnerability_type', '-detected_at']),
        ]

    def __str__(self):
        return f"[{self.get_severity_display()}] {self.title}"

    def get_display_severity_color(self):
        """Retourne la couleur pour l'affichage"""
        color_map = {
            'critical': '#dc2626',
            'high': '#ef4444',
            'medium': '#f59e0b',
            'low': '#10b981',
            'info': '#3b82f6',
        }
        return color_map.get(self.severity, '#6b7280')


class VulnerabilityFix(models.Model):
    """Historique des corrections appliquées"""
    vulnerability = models.ForeignKey(SecurityVulnerability, on_delete=models.CASCADE, related_name='fixes')
    
    applied_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    applied_at = models.DateTimeField(auto_now_add=True)
    
    original_code = models.TextField(help_text="Code avant correction")
    fixed_code = models.TextField(help_text="Code après correction")
    fix_description = models.TextField(blank=True)
    
    successful = models.BooleanField(default=True)
    error_message = models.TextField(blank=True, help_text="Message d'erreur si la correction a échoué")
    
    tested = models.BooleanField(default=False)
    test_results = models.TextField(blank=True, help_text="Résultats des tests")
    
    rollback_possible = models.BooleanField(default=True)
    rollback_applied = models.BooleanField(default=False)
    rollback_applied_at = models.DateTimeField(blank=True, null=True)

    class Meta:
        verbose_name = 'Correction de Vulnérabilité'
        verbose_name_plural = 'Corrections de Vulnérabilités'
        ordering = ['-applied_at']

    def __str__(self):
        return f"Fix for {self.vulnerability.title} - {self.applied_at.strftime('%d/%m/%Y %H:%M')}"


class AISecurityAudit(models.Model):
    """Audit de sécurité automatique par IA"""
    STATUS_CHOICES = [
        ('pending', 'En attente'),
        ('running', 'En cours'),
        ('completed', 'Terminé'),
        ('error', 'Erreur'),
    ]

    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')

    # Domaines scannés
    scan_routes = models.BooleanField(default=True, help_text="Scanner les routes API")
    scan_database = models.BooleanField(default=True, help_text="Analyser la base de données")
    scan_dependencies = models.BooleanField(default=True, help_text="Vérifier les dépendances")
    scan_authentication = models.BooleanField(default=True, help_text="Analyser l'authentification")
    scan_authorization = models.BooleanField(default=True, help_text="Analyser l'autorisation")
    scan_file_uploads = models.BooleanField(default=True, help_text="Vérifier les uploads")
    scan_forms = models.BooleanField(default=True, help_text="Analyser les formulaires")
    scan_errors = models.BooleanField(default=True, help_text="Analyser les erreurs")

    # Résultats
    vulnerabilities_found = models.IntegerField(default=0)
    vulnerabilities_critical = models.IntegerField(default=0)
    vulnerabilities_high = models.IntegerField(default=0)
    vulnerabilities_medium = models.IntegerField(default=0)
    vulnerabilities_low = models.IntegerField(default=0)

    # Métriques
    overall_security_score = models.FloatField(default=0.0, help_text="Score de sécurité global (0-100)")
    scan_duration_seconds = models.IntegerField(default=0)
    files_scanned = models.IntegerField(default=0)
    routes_tested = models.IntegerField(default=0)

    # Rapport détaillé
    report = models.JSONField(default=dict, blank=True)
    error_log = models.TextField(blank=True)

    # Création automatique
    automatic = models.BooleanField(default=False, help_text="Audit créé automatiquement")
    triggered_by = models.CharField(max_length=100, blank=True, help_text="Qui a déclenché l'audit")

    class Meta:
        verbose_name = 'Audit Sécurité IA'
        verbose_name_plural = 'Audits Sécurité IA'
        ordering = ['-started_at']

    def __str__(self):
        return f"Audit IA - {self.started_at.strftime('%d/%m/%Y %H:%M')} ({self.status})"


class ContinuousSecurityMonitoring(models.Model):
    """Surveillance continue des failles"""
    SCAN_INTERVAL_CHOICES = [
        ('hourly', 'Chaque heure'),
        ('daily', 'Quotidien'),
        ('weekly', 'Hebdomadaire'),
    ]

    is_enabled = models.BooleanField(default=True)
    scan_interval = models.CharField(max_length=20, choices=SCAN_INTERVAL_CHOICES, default='daily')
    
    last_scan = models.DateTimeField(blank=True, null=True)
    next_scan = models.DateTimeField(blank=True, null=True)
    
    auto_fix_critical = models.BooleanField(default=False, help_text="Corriger automatiquement les failles critiques")
    auto_fix_high = models.BooleanField(default=False, help_text="Corriger automatiquement les failles élevées")
    auto_fix_medium = models.BooleanField(default=False, help_text="Corriger automatiquement les failles moyennes")
    
    notify_on_detection = models.BooleanField(default=True)
    notify_email = models.EmailField(blank=True)
    notify_telegram = models.BooleanField(default=False)
    
    backup_before_fix = models.BooleanField(default=True, help_text="Créer un backup avant chaque correction")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Surveillance Sécurité Continue'
        verbose_name_plural = 'Surveillances Sécurité Continues'

    def __str__(self):
        return f"Surveillance Continue - {'Activée' if self.is_enabled else 'Désactivée'}"


class AISecurityRecommendation(models.Model):
    """Recommandations de sécurité par IA"""
    RECOMMENDATION_TYPE_CHOICES = [
        ('update', 'Mise à jour'),
        ('configuration', 'Configuration'),
        ('best_practice', 'Meilleure pratique'),
        ('dependency', 'Dépendance'),
        ('architecture', 'Architecture'),
        ('authentication', 'Authentification'),
    ]

    PRIORITY_CHOICES = [
        ('critical', 'Critique'),
        ('high', 'Élevée'),
        ('medium', 'Moyenne'),
        ('low', 'Faible'),
    ]

    recommendation_type = models.CharField(max_length=50, choices=RECOMMENDATION_TYPE_CHOICES)
    title = models.CharField(max_length=200)
    description = models.TextField()
    implementation_steps = models.TextField(blank=True)
    expected_impact = models.CharField(max_length=255, blank=True)
    
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='medium')
    
    implemented = models.BooleanField(default=False)
    implemented_at = models.DateTimeField(blank=True, null=True)
    implemented_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='implemented_recommendations')
    
    ai_confidence = models.FloatField(default=0.0)
    external_reference = models.URLField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Recommandation Sécurité IA'
        verbose_name_plural = 'Recommandations Sécurité IA'
        ordering = ['-priority', '-created_at']

    def __str__(self):
        return f"[{self.get_priority_display()}] {self.title}"


# ==========================================
# SYSTÈME D'ANNONCES ADMINISTRATIVES
# ==========================================

class AdminAnnouncement(models.Model):
    """Modèle pour gérer les annonces administratives prioritaires"""
    
    STATUS_CHOICES = (
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('scheduled', 'Planifiée'),
        ('archived', 'Archivée'),
    )
    
    SCROLL_SPEED_CHOICES = (
        ('very_slow', 'Très lent (20px/s)'),
        ('slow', 'Lent (40px/s)'),
        ('normal', 'Normal (60px/s)'),
        ('fast', 'Rapide (80px/s)'),
        ('very_fast', 'Très rapide (100px/s)'),
    )
    
    # Informations de base
    title = models.CharField(max_length=200, verbose_name="Titre de l'annonce")
    message = models.TextField(verbose_name="Message administratif", help_text="Contenu principal de l'annonce")
    
    # Status et visibilité
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='inactive', verbose_name="Statut")
    is_priority = models.BooleanField(default=False, verbose_name="Annonce prioritaire", help_text="Les annonces prioritaires s'affichent en premier")
    is_active = models.BooleanField(default=True, verbose_name="Activée")
    
    # Planification
    start_date = models.DateTimeField(null=True, blank=True, verbose_name="Date de début", help_text="Quand cette annonce devient active")
    end_date = models.DateTimeField(null=True, blank=True, verbose_name="Date de fin", help_text="Quand cette annonce devient inactive")
    
    # Apparence visuelle
    background_color = models.CharField(
        max_length=7,
        default='#1a3a52',
        verbose_name="Couleur de fond",
        help_text="Format hexadécimal (#RRGGBB)"
    )
    text_color = models.CharField(
        max_length=7,
        default='#ffffff',
        verbose_name="Couleur du texte",
        help_text="Format hexadécimal (#RRGGBB)"
    )
    accent_color = models.CharField(
        max_length=7,
        default='#00bcd4',
        verbose_name="Couleur d'accent",
        help_text="Format hexadécimal (#RRGGBB)"
    )
    
    # Animation et vitesse
    scroll_speed = models.CharField(
        max_length=20,
        choices=SCROLL_SPEED_CHOICES,
        default='normal',
        verbose_name="Vitesse de défilement"
    )
    enable_loop = models.BooleanField(default=True, verbose_name="Défilement en boucle")
    animation_effect = models.CharField(
        max_length=50,
        choices=(
            ('slide', 'Glissement'),
            ('fade', 'Fondu'),
            ('bounce', 'Rebond'),
            ('wave', 'Vague'),
            ('pulse', 'Pulsation'),
        ),
        default='slide',
        verbose_name="Effet d'animation"
    )
    
    # Icons et émojis
    icon = models.CharField(
        max_length=20,
        default='📢',
        verbose_name="Emoji/Icône",
        help_text="Emoji qui s'affiche avant le message"
    )
    
    # Metadata
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_announcements',
        verbose_name="Créée par"
    )
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Date de création")
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='updated_announcements',
        verbose_name="Dernière modification par"
    )
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Dernière modification")
    
    # Statistiques
    view_count = models.IntegerField(default=0, verbose_name="Nombre de vues")
    click_count = models.IntegerField(default=0, verbose_name="Nombre de clics")
    
    class Meta:
        verbose_name = "Annonce administrative"
        verbose_name_plural = "Annonces administratives"
        ordering = ['-is_priority', '-created_at']
        indexes = [
            models.Index(fields=['-is_priority', '-created_at']),
            models.Index(fields=['status', 'is_active']),
            models.Index(fields=['start_date', 'end_date']),
        ]
    
    def __str__(self):
        return f"{'📢 ' if self.is_priority else ''}{self.title} ({'Active' if self.status == 'active' else self.status.title()})"
    
    def activate(self):
        """Activer l'annonce"""
        self.is_active = True
        self.status = 'active'
        self.save(update_fields=['is_active', 'status'])
    
    def deactivate(self):
        """Désactiver l'annonce"""
        self.is_active = False
        self.status = 'inactive'
        self.save(update_fields=['is_active', 'status'])
    
    def set_priority(self, is_priority=True):
        """Définir ou retirer la priorité"""
        self.is_priority = is_priority
        self.save(update_fields=['is_priority'])
    
    @classmethod
    def get_active_announcements(cls):
        """Récupère les annonces actuellement actives"""
        from django.utils import timezone
        now = timezone.now()
        return cls.objects.filter(
            is_active=True,
            status='active'
        ).filter(
            models.Q(start_date__isnull=True) | models.Q(start_date__lte=now)
        ).filter(
            models.Q(end_date__isnull=True) | models.Q(end_date__gt=now)
        ).order_by('-is_priority', '-created_at')
    
    @classmethod
    def get_priority_announcement(cls):
        """Récupère l'annonce prioritaire active s'il y en a une"""
        active = cls.get_active_announcements()
        return active.filter(is_priority=True).first()
    
    def increment_views(self):
        """Incrémenter le compteur de vues"""
        self.view_count += 1
        self.save(update_fields=['view_count'])
    
    def increment_clicks(self):
        """Incrémenter le compteur de clics"""
        self.click_count += 1
        self.save(update_fields=['click_count'])


class AdminAnnouncementPermission(models.Model):
    """Gestion des permissions pour modifier les annonces administratives"""
    
    PERMISSION_LEVELS = (
        ('view', 'Lecture seulement'),
        ('create', 'Créer'),
        ('edit', 'Modifier'),
        ('delete', 'Supprimer'),
        ('manage_all', 'Gestion complète'),
    )
    
    admin = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='announcement_permissions',
        limit_choices_to={'role__in': ['super_admin', 'ai_admin', 'admin_secondary']},
        verbose_name="Administrateur"
    )
    permission_level = models.CharField(
        max_length=20,
        choices=PERMISSION_LEVELS,
        default='view',
        verbose_name="Niveau de permission"
    )
    granted_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='granted_announcement_permissions',
        verbose_name="Permission accordée par",
        help_text="Généralement l'Administrateur Principal"
    )
    granted_at = models.DateTimeField(auto_now_add=True, verbose_name="Date d'octroi")
    
    class Meta:
        verbose_name = "Permission Annonce"
        verbose_name_plural = "Permissions Annonces"
        unique_together = ('admin',)
    
    def __str__(self):
        return f"{self.admin.username} - {self.get_permission_level_display()}"
    
    def has_permission(self, required_level):
        """Vérifier si l'admin a la permission requise"""
        levels_hierarchy = {
            'view': 0,
            'create': 1,
            'edit': 2,
            'delete': 3,
            'manage_all': 4,
        }
        return levels_hierarchy.get(self.permission_level, 0) >= levels_hierarchy.get(required_level, 0)


class Course(models.Model):
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, unique=True)
    description = models.TextField(blank=True, default='')
    instructor = models.CharField(max_length=255, default='Prof. SDI')
    next_session = models.DateTimeField(blank=True, null=True)
    is_published = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = slugify(self.title)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.title

    class Meta:
        verbose_name = 'Cours'
        verbose_name_plural = 'Cours'
        ordering = ['title']


class CourseAssignment(models.Model):
    STATUS_CHOICES = [
        ('open', 'Ouvert'),
        ('closed', 'Fermé'),
        ('graded', 'Noté'),
    ]

    course = models.ForeignKey('Course', on_delete=models.CASCADE, related_name='assignments')
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, default='')
    due_date = models.DateField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='open')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.title} ({self.course.title})'

    class Meta:
        verbose_name = 'Devoir'
        verbose_name_plural = 'Devoirs'
        ordering = ['due_date', 'title']


class AssignmentSubmission(models.Model):
    STATUS_CHOICES = [
        ('submitted', 'Soumis'),
        ('reviewed', 'Revu'),
        ('approved', 'Validé'),
        ('rejected', 'Rejeté'),
    ]

    assignment = models.ForeignKey('CourseAssignment', on_delete=models.CASCADE, related_name='submissions')
    user = models.ForeignKey('User', on_delete=models.CASCADE, related_name='assignment_submissions')
    file = models.FileField(upload_to='course_submissions/%Y/%m/%d/')
    comments = models.TextField(blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='submitted')
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f'{self.assignment.title} - {self.user.username}'

    class Meta:
        verbose_name = 'Soumission de devoir'
        verbose_name_plural = 'Soumissions de devoirs'
        ordering = ['-submitted_at']


class CourseCertificate(models.Model):
    STATUS_CHOICES = [
        ('available', 'Disponible'),
        ('pending', 'En attente'),
        ('revoked', 'Révoqué'),
    ]

    course = models.ForeignKey('Course', on_delete=models.CASCADE, related_name='certificates')
    user = models.ForeignKey('User', on_delete=models.CASCADE, related_name='course_certificates')
    title = models.CharField(max_length=255)
    issued_date = models.DateField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.title} - {self.user.username}'

    class Meta:
        verbose_name = 'Certificat'
        verbose_name_plural = 'Certificats'
        unique_together = ('course', 'user', 'title')


# Import Real Estate Models
from .real_estate_models import *
