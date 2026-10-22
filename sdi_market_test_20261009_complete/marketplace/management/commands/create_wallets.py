from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from marketplace.models import Wallet
from decimal import Decimal

User = get_user_model()

class Command(BaseCommand):
    help = 'Crée des wallets pour tous les utilisateurs qui n\'en ont pas'

    def handle(self, *args, **options):
        users_without_wallet = User.objects.filter(wallet__isnull=True)
        count = users_without_wallet.count()
        
        if count == 0:
            self.stdout.write(self.style.SUCCESS('[OK] Tous les utilisateurs ont deja un wallet!'))
            return
        
        created_count = 0
        for user in users_without_wallet:
            wallet, created = Wallet.objects.get_or_create(
                user=user,
                defaults={
                    'balance': Decimal('0.00'),
                    'balance_usd': Decimal('0.00'),
                    'balance_htg': Decimal('0.00'),
                    'balance_peso': Decimal('0.00'),
                    'can_transfer': True,
                    'is_blocked': False
                }
            )
            if created:
                created_count += 1
                self.stdout.write('[+] Wallet cree pour {}'.format(user.username))
        
        self.stdout.write(self.style.SUCCESS('\n[OK] {} wallets crees avec succes!'.format(created_count)))
        total = User.objects.filter(wallet__isnull=False).count()
        self.stdout.write(self.style.SUCCESS('  Total: {} utilisateurs avec wallet'.format(total)))
