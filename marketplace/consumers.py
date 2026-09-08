import json
from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.utils import timezone
from .models import DeliveryAssignment, DeliveryEmployee, DeliveryTracking, DeliveryNotification
from .business_logic import DeliveryStatusManager, NotificationManager


class DeliveryTrackingConsumer(AsyncWebsocketConsumer):
    """
    Consumer pour le suivi en temps réel d'une livraison spécifique
    Utilisé par les clients et vendeurs pour suivre leur livraison
    """

    async def connect(self):
        self.assignment_id = self.scope['url_route']['kwargs']['assignment_id']
        self.room_group_name = f'delivery_{self.assignment_id}'

        # Vérifier les permissions
        user = self.scope['user']
        if await self.can_access_delivery(user, self.assignment_id):
            await self.channel_layer.group_add(
                self.room_group_name,
                self.channel_name
            )
            await self.accept()
            await self.send_initial_data()
        else:
            await self.close()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        # Les clients peuvent envoyer des messages si nécessaire
        pass

    async def delivery_update(self, event):
        """Envoi des mises à jour de livraison"""
        await self.send(text_data=json.dumps(event['data']))

    async def location_update(self, event):
        """Envoi des mises à jour de position GPS"""
        await self.send(text_data=json.dumps(event['data']))

    @database_sync_to_async
    def can_access_delivery(self, user, assignment_id):
        try:
            assignment = DeliveryAssignment.objects.get(id=assignment_id)
            return (
                user.is_staff or
                user == assignment.employee.user or
                user == assignment.order.buyer
            )
        except DeliveryAssignment.DoesNotExist:
            return False

    async def send_initial_data(self):
        try:
            assignment = await self.get_initial_assignment()
            if not assignment:
                return

            data = {
                'type': 'initial_data',
                'assignment': {
                    'id': assignment.id,
                    'status': assignment.status,
                    'driver_location': {
                        'lat': float(assignment.current_lat) if assignment.current_lat else None,
                        'lng': float(assignment.current_lng) if assignment.current_lng else None,
                    },
                    'seller_location': {
                        'lat': float(assignment.seller_lat) if assignment.seller_lat else None,
                        'lng': float(assignment.seller_lng) if assignment.seller_lng else None,
                    },
                    'buyer_location': {
                        'lat': float(assignment.buyer_lat) if assignment.buyer_lat else None,
                        'lng': float(assignment.buyer_lng) if assignment.buyer_lng else None,
                    },
                    'eta': assignment.estimated_delivery_time.isoformat() if assignment.estimated_delivery_time else None,
                }
            }
            await self.send(text_data=json.dumps(data))
        except DeliveryAssignment.DoesNotExist:
            pass

    @database_sync_to_async
    def get_initial_assignment(self):
        return DeliveryAssignment.objects.get(id=self.assignment_id)


class DriverLocationConsumer(AsyncWebsocketConsumer):
    """
    Consumer pour les livreurs - reçoit les instructions et envoie la position GPS
    """

    async def connect(self):
        self.driver_id = self.scope['url_route']['kwargs']['driver_id']
        self.room_group_name = f'driver_{self.driver_id}'

        user = self.scope['user']
        if await self.can_access_driver(user, self.driver_id):
            await self.channel_layer.group_add(
                self.room_group_name,
                self.channel_name
            )
            await self.accept()
        else:
            await self.close()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        """Recevoir les mises à jour de position du livreur"""
        try:
            data = json.loads(text_data)
            if data.get('type') == 'location_update':
                await self.update_driver_location(data)
        except json.JSONDecodeError:
            pass

    async def driver_instruction(self, event):
        """Recevoir les instructions de l'admin"""
        await self.send(text_data=json.dumps(event['data']))

    async def new_delivery(self, event):
        """Recevoir une nouvelle livraison assignée"""
        await self.send(text_data=json.dumps(event['data']))

    @database_sync_to_async
    def can_access_driver(self, user, driver_id):
        try:
            driver = DeliveryEmployee.objects.get(id=driver_id)
            return user == driver.user
        except DeliveryEmployee.DoesNotExist:
            return False

    async def update_driver_location(self, data):
        try:
            result = await self.save_driver_location(data)
            if not result:
                return

            active_assignment_id, lat, lng, location_name = result
            from channels.layers import get_channel_layer
            channel_layer = get_channel_layer()
            await channel_layer.group_send(
                f'delivery_{active_assignment_id}',
                {
                    'type': 'location_update',
                    'data': {
                        'type': 'location_update',
                        'driver_location': {
                            'lat': float(lat),
                            'lng': float(lng),
                            'name': location_name,
                            'timestamp': timezone.now().isoformat()
                        }
                    }
                }
            )
        except Exception:
            pass

    @database_sync_to_async
    def save_driver_location(self, data):
        try:
            driver = DeliveryEmployee.objects.get(id=self.driver_id)
            lat = data.get('latitude')
            lng = data.get('longitude')
            location_name = data.get('location_name', '')

            if not lat or not lng:
                return None

            driver.current_latitude = lat
            driver.current_longitude = lng
            driver.current_location = location_name
            driver.last_location_update = timezone.now()
            driver.save()

            active_assignment = DeliveryAssignment.objects.filter(
                employee=driver,
                status__in=['assigned', 'picked_up', 'in_transit']
            ).first()

            if active_assignment:
                DeliveryTracking.objects.create(
                    assignment=active_assignment,
                    latitude=lat,
                    longitude=lng,
                    location_name=location_name,
                    status_update=f"Position mise à jour: {location_name}"
                )
                return active_assignment.id, lat, lng, location_name

            return None
        except DeliveryEmployee.DoesNotExist:
            return None


class AdminDeliveryConsumer(AsyncWebsocketConsumer):
    """
    Consumer pour l'admin - surveillance temps réel de toutes les livraisons
    """

    async def connect(self):
        self.room_group_name = 'admin_delivery'

        user = self.scope['user']
        if user.is_staff:
            await self.channel_layer.group_add(
                self.room_group_name,
                self.channel_name
            )
            await self.accept()
        else:
            await self.close()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    async def receive(self, text_data):
        # L'admin peut envoyer des instructions aux livreurs
        try:
            data = json.loads(text_data)
            if data.get('type') == 'send_instruction':
                await self.send_driver_instruction(data)
        except json.JSONDecodeError:
            pass

    async def delivery_status_change(self, event):
        """Notification de changement de statut"""
        await self.send(text_data=json.dumps(event['data']))

    async def driver_location_update(self, event):
        """Mise à jour de position d'un livreur"""
        await self.send(text_data=json.dumps(event['data']))

    async def send_driver_instruction(self, data):
        """Envoyer une instruction à un livreur"""
        driver_id = data.get('driver_id')
        instruction = data.get('instruction')

        if driver_id and instruction:
            from channels.layers import get_channel_layer
            channel_layer = get_channel_layer()
            await channel_layer.group_send(
                f'driver_{driver_id}',
                {
                    'type': 'driver_instruction',
                    'data': {
                        'type': 'instruction',
                        'instruction': instruction,
                        'timestamp': timezone.now().isoformat()
                    }
                }
            )