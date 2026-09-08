from decimal import Decimal

from .business_logic import CommissionManager

def calcul_cashback(quantite):
    cashback_par_produit = CommissionManager.get_config('cashback_par_produit_acheteur')
    return round(Decimal(str(quantite)) * cashback_par_produit, 2)