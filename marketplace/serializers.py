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
        fields = "__all__"

class TransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transaction
        fields = "__all__"

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
        fields = "__all__"


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