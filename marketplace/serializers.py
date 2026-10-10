from rest_framework import serializers
from .models import Product, Shop, Order, Wallet, OrderItem, Transaction, DeliveryEmployee, DeliveryAssignment, Agent, DeliveryTracking, DeliveryNotification, ReturnRequest

class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = "__all__"

class ShopSerializer(serializers.ModelSerializer):
    class Meta:
        model = Shop
        fields = "__all__"

class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = "__all__"

class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    class Meta:
        model = Order
        fields = "__all__"

class WalletSerializer(serializers.ModelSerializer):
    class Meta:
        model = Wallet
        fields = (
            'id', 'user', 'balance', 'balance_usd', 'balance_htg',
            'real_estate_loan_balance_htg', 'balance_peso', 'balance_eur',
            'commission_balance_usd', 'commission_balance_htg',
            'commission_balance_peso', 'commission_balance_eur',
            'can_transfer', 'is_blocked',
        )
        read_only_fields = fields

class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        fields = ('id', 'sender', 'receiver', 'amount', 'currency', 'type', 'status', 'created_at')
        read_only_fields = fields

class DeliveryEmployeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryEmployee
        fields = "__all__"

class DeliveryAssignmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryAssignment
        fields = "__all__"

class AgentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Agent
        fields = ('id', 'user', 'is_active')
        read_only_fields = ('id',)

    def validate(self, attrs):
        user = attrs.get('user', getattr(self.instance, 'user', None))
        if user and not (user.is_agent or user.role == 'agent'):
            raise serializers.ValidationError({'user': 'Le compte doit avoir le rôle agent.'})
        return attrs


class DeliveryTrackingSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryTracking
        fields = "__all__"


class DeliveryNotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryNotification
        fields = "__all__"


class ReturnRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReturnRequest
        fields = "__all__"