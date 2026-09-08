# WebSocket routing for real-time delivery tracking
from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/delivery/(?P<assignment_id>\d+)/$', consumers.DeliveryTrackingConsumer.as_asgi()),
    re_path(r'ws/driver/(?P<driver_id>\d+)/$', consumers.DriverLocationConsumer.as_asgi()),
    re_path(r'ws/admin/delivery/$', consumers.AdminDeliveryConsumer.as_asgi()),
]
