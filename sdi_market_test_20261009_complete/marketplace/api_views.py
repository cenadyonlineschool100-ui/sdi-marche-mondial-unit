"""
🔥 API ENDPOINTS - Interfaces REST pour la logique métier

Structure claire et simple pour intégrer avec le frontend (React, Vue, ou templates).
"""

from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework import permissions
from django.shortcuts import get_object_or_404
from django.utils import timezone
from .models import (
    Order, DeliveryAssignment, ReturnRequest, DeliveryEmployee,
    DeliveryNotification, DeliveryTracking
)
from .business_logic import (
    DeliveryAssignmentManager, DeliveryStatusManager,
    NotificationManager, PaymentManager, ReturnManager,
    StatisticsManager
)
from .serializers import (
    DeliveryAssignmentSerializer, ReturnRequestSerializer,
    DeliveryEmployeeSerializer
)


# ═══════════════════════════════════════════════════════════════
# 🚚 DELIVERY API - Gestion complète des livraisons
# ═══════════════════════════════════════════════════════════════

class DeliveryAPIViewSet(viewsets.ViewSet):
    """
    API métier complète pour la gestion des livraisons.
    
    Endpoints:
    - POST /api/delivery/assign/ - Assigner une livraison
    - POST /api/delivery/update-status/ - Mettre à jour le statut
    - POST /api/delivery/update-location/ - Mettre à jour la position GPS
    - GET /api/delivery/track/{assignment_id}/ - Suivre une livraison
    - POST /api/delivery/reassign/ - Réassigner à un autre livreur
    - POST /api/delivery/handle-failure/ - Signaler un échec de livraison
    """
    
    permission_classes = [permissions.IsAuthenticated]
    
    def retrieve(self, request, pk=None):
        """🔎 Récupérer les informations d'une livraison par assignation"""
        try:
            assignment = DeliveryAssignment.objects.get(id=pk)
        except DeliveryAssignment.DoesNotExist:
            return Response(
                {'error': 'Assignation introuvable'},
                status=status.HTTP_404_NOT_FOUND
            )

        if not (request.user.is_staff or request.user == assignment.employee.user or request.user == assignment.order.buyer):
            return Response(
                {'error': 'Permission refusée'},
                status=status.HTTP_403_FORBIDDEN
            )

        order = assignment.order
        return Response({
            'status': 'success',
            'assignment_id': assignment.id,
            'order_id': order.id,
            'order_status': order.status,
            'order_address': order.delivery_address,
            'current_status': assignment.get_status_display(),
            'delivery_zone': assignment.delivery_zone,
            'seller_location': {
                'latitude': float(assignment.seller_lat) if assignment.seller_lat else None,
                'longitude': float(assignment.seller_lng) if assignment.seller_lng else None,
            },
            'buyer_location': {
                'latitude': float(assignment.buyer_lat) if assignment.buyer_lat else None,
                'longitude': float(assignment.buyer_lng) if assignment.buyer_lng else None,
            },
            'driver_location': {
                'latitude': float(assignment.current_lat) if assignment.current_lat else None,
                'longitude': float(assignment.current_lng) if assignment.current_lng else None,
                'name': assignment.employee.user.get_full_name(),
                'current_place': assignment.employee.current_location,
            },
            'eta': assignment.estimated_delivery_time.isoformat() if assignment.estimated_delivery_time else None,
            'tracking_history': [
                {
                    'timestamp': t.timestamp.isoformat(),
                    'status': t.status_update,
                    'latitude': float(t.latitude) if t.latitude else None,
                    'longitude': float(t.longitude) if t.longitude else None,
                    'location': t.location_name
                } for t in DeliveryTracking.objects.filter(assignment=assignment).order_by('-timestamp')[:20]
            ]
        })

    @action(detail=False, methods=['post'], url_path='assign')
    def assign_delivery(self, request):
        """🚚 Assigner automatiquement une livreur à une commande"""
        order_id = request.data.get('order_id')
        
        try:
            order = Order.objects.get(id=order_id)
        except Order.DoesNotExist:
            return Response(
                {'error': 'Commande introuvable'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Vérifier que l'utilisateur est admin ou propriétaire
        if not (request.user.is_staff or request.user == order.buyer):
            return Response(
                {'error': 'Permission refusée'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            assignment = DeliveryAssignmentManager.assign_delivery_agent_to_order(order)
            
            if assignment:
                return Response({
                    'status': 'success',
                    'message': f'Livreur assigné: {assignment.employee.user.get_full_name()}',
                    'assignment_id': assignment.id,
                    'driver': {
                        'name': assignment.employee.user.get_full_name(),
                        'phone': assignment.employee.user.phone if hasattr(assignment.employee.user, 'phone') else '',
                        'vehicle': assignment.employee.vehicle_type,
                        'rating': float(assignment.employee.rating),
                    }
                })
            else:
                return Response({
                    'status': 'warning',
                    'message': 'Aucun livreur disponible pour le moment'
                }, status=status.HTTP_202_ACCEPTED)
        
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=False, methods=['post'], url_path='update-status')
    def update_status(self, request):
        """📍 Mettre à jour le statut d'une livraison"""
        assignment_id = request.data.get('assignment_id')
        new_status = request.data.get('status')
        notes = request.data.get('notes', '')
        latitude = request.data.get('latitude')
        longitude = request.data.get('longitude')
        
        try:
            assignment = DeliveryAssignment.objects.get(id=assignment_id)
        except DeliveryAssignment.DoesNotExist:
            return Response(
                {'error': 'Assignation introuvable'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Vérifier permissions
        if not (request.user.is_staff or request.user == assignment.employee.user):
            return Response(
                {'error': 'Permission refusée'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            DeliveryStatusManager.update_delivery_status(
                assignment, new_status, notes, latitude, longitude
            )
            
            return Response({
                'status': 'success',
                'message': f'Statut mis à jour: {assignment.get_status_display()}',
                'new_status': new_status,
                'timestamp': assignment.updated_at if hasattr(assignment, 'updated_at') else None
            })
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=False, methods=['post'], url_path='update-location')
    def update_location(self, request):
        """📍 Mettre à jour la position GPS du livreur"""
        assignment_id = request.data.get('assignment_id')
        latitude = request.data.get('latitude')
        longitude = request.data.get('longitude')
        location_name = request.data.get('location_name', '')
        
        try:
            assignment = DeliveryAssignment.objects.get(id=assignment_id)
        except DeliveryAssignment.DoesNotExist:
            return Response(
                {'error': 'Assignation introuvable'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Vérifier permissions
        if not (request.user.is_staff or request.user == assignment.employee.user):
            return Response(
                {'error': 'Permission refusée'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        if not latitude or not longitude:
            return Response(
                {'error': 'Latitude et longitude requises'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Mettre à jour la position
            assignment.employee.current_latitude = latitude
            assignment.employee.current_longitude = longitude
            assignment.employee.last_location_update = timezone.now()
            assignment.employee.save()
            
            # Créer tracking
            DeliveryTracking.objects.create(
                assignment=assignment,
                latitude=latitude,
                longitude=longitude,
                location_name=location_name,
                status_update=f"Position mise à jour: {location_name}"
            )
            
            return Response({
                'status': 'success',
                'message': 'Position mise à jour',
                'location': {
                    'latitude': float(latitude),
                    'longitude': float(longitude),
                    'name': location_name
                }
            })
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=False, methods=['get'], url_path='track/(?P<assignment_id>[^/.]+)')
    def track_delivery(self, request, assignment_id=None):
        """🗺️ Suivre une livraison en temps réel"""
        try:
            assignment = DeliveryAssignment.objects.get(id=assignment_id)
        except DeliveryAssignment.DoesNotExist:
            return Response(
                {'error': 'Assignation introuvable'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Vérifier permissions
        if not (request.user.is_staff or 
                request.user == assignment.employee.user or 
                request.user == assignment.order.buyer):
            return Response(
                {'error': 'Permission refusée'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Récupérer l'historique de tracking
        tracking_history = DeliveryTracking.objects.filter(
            assignment=assignment
        ).order_by('-timestamp')[:20]
        
        return Response({
            'status': 'success',
            'assignment_id': assignment.id,
            'order_id': assignment.order.id,
            'order_status': assignment.order.status,
            'order_address': assignment.order.delivery_address,
            'delivery_zone': assignment.delivery_zone,
            'seller_location': {
                'latitude': float(assignment.seller_lat) if assignment.seller_lat else None,
                'longitude': float(assignment.seller_lng) if assignment.seller_lng else None,
            },
            'buyer_location': {
                'latitude': float(assignment.buyer_lat) if assignment.buyer_lat else None,
                'longitude': float(assignment.buyer_lng) if assignment.buyer_lng else None,
            },
            'driver': {
                'name': assignment.employee.user.get_full_name(),
                'current_location': assignment.employee.current_location,
                'current_latitude': float(assignment.employee.current_latitude) if assignment.employee.current_latitude else None,
                'current_longitude': float(assignment.employee.current_longitude) if assignment.employee.current_longitude else None,
            },
            'eta': assignment.estimated_delivery_time.isoformat() if assignment.estimated_delivery_time else None,
            'tracking_history': [{
                'timestamp': t.timestamp.isoformat(),
                'status': t.status_update,
                'latitude': float(t.latitude) if t.latitude else None,
                'longitude': float(t.longitude) if t.longitude else None,
                'location': t.location_name
            } for t in tracking_history]
        })
    
    @action(detail=False, methods=['post'], url_path='handle-failure')
    def handle_failure(self, request):
        """❌ Signaler un échec de livraison"""
        assignment_id = request.data.get('assignment_id')
        failure_reason = request.data.get('reason', 'Raison non spécifiée')
        
        try:
            assignment = DeliveryAssignment.objects.get(id=assignment_id)
        except DeliveryAssignment.DoesNotExist:
            return Response(
                {'error': 'Assignation introuvable'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Vérifier permissions
        if not (request.user.is_staff or request.user == assignment.employee.user):
            return Response(
                {'error': 'Permission refusée'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            DeliveryStatusManager.handle_failed_delivery(assignment, failure_reason)
            
            return Response({
                'status': 'success',
                'message': f'Échec signalé: {failure_reason}',
                'next_action': 'Nouvelle tentative assignée ou attente de confirmation'
            })
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


# ═══════════════════════════════════════════════════════════════
# 🔄 RETURN REQUEST API - Gestion des retours
# ═══════════════════════════════════════════════════════════════

class ReturnRequestAPIViewSet(viewsets.ViewSet):
    """
    API pour la gestion des demandes de retour.
    
    Endpoints:
    - POST /api/return/create/ - Créer une demande de retour
    - GET /api/return/list/ - Lister les demandes
    - POST /api/return/{id}/approve/ - Approuver
    - POST /api/return/{id}/reject/ - Rejeter
    - POST /api/return/{id}/process-refund/ - Traiter remboursement
    """
    
    permission_classes = [permissions.IsAuthenticated]
    
    @action(detail=False, methods=['post'], url_path='create')
    def create_return(self, request):
        """📦 Créer une demande de retour"""
        order_id = request.data.get('order_id')
        reason = request.data.get('reason')
        description = request.data.get('description')
        
        try:
            order = Order.objects.get(id=order_id, buyer=request.user)
        except Order.DoesNotExist:
            return Response(
                {'error': 'Commande introuvable'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        # Vérifier éligibilité
        is_eligible, message = ReturnManager.get_return_eligibility(order)
        
        if not is_eligible:
            return Response(
                {'error': message},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            return_request = ReturnRequest.objects.create(
                order=order,
                customer=request.user,
                reason=reason,
                description=description
            )
            
            return Response({
                'status': 'success',
                'message': 'Demande de retour créée',
                'return_id': return_request.id,
                'requested_at': return_request.requested_at.isoformat()
            }, status=status.HTTP_201_CREATED)
        
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=False, methods=['get'], url_path='list')
    def list_returns(self, request):
        """📋 Lister les demandes de retour"""
        if request.user.is_staff:
            returns = ReturnRequest.objects.all()
        else:
            returns = ReturnRequest.objects.filter(customer=request.user)
        
        return Response({
            'status': 'success',
            'total': returns.count(),
            'returns': [{
                'id': r.id,
                'order_id': r.order.id,
                'reason': r.reason,
                'status': r.status,
                'requested_at': r.requested_at.isoformat(),
                'refund_amount': float(r.refund_amount) if r.refund_amount else 0
            } for r in returns]
        })
    
    @action(detail=False, methods=['post'], url_path='(?P<return_id>[^/.]+)/approve')
    def approve_return(self, request, return_id=None):
        """✅ Approuver une demande de retour"""
        if not request.user.is_staff:
            return Response(
                {'error': 'Permission refusée'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            return_request = ReturnRequest.objects.get(id=return_id)
        except ReturnRequest.DoesNotExist:
            return Response(
                {'error': 'Demande de retour introuvable'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        try:
            ReturnManager.approve_return(return_request)
            
            return Response({
                'status': 'success',
                'message': 'Retour approuvé et remboursement traité',
                'refund_amount': float(return_request.refund_amount)
            })
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=False, methods=['post'], url_path='(?P<return_id>[^/.]+)/reject')
    def reject_return(self, request, return_id=None):
        """❌ Rejeter une demande de retour"""
        if not request.user.is_staff:
            return Response(
                {'error': 'Permission refusée'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        try:
            return_request = ReturnRequest.objects.get(id=return_id)
        except ReturnRequest.DoesNotExist:
            return Response(
                {'error': 'Demande de retour introuvable'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        reason = request.data.get('reason', '')
        
        try:
            ReturnManager.reject_return(return_request, reason)
            
            return Response({
                'status': 'success',
                'message': 'Retour rejeté'
            })
        except Exception as e:
            return Response(
                {'error': str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


# ═══════════════════════════════════════════════════════════════
# 📊 STATISTICS API - Analytics et métriques
# ═══════════════════════════════════════════════════════════════

class StatisticsAPIViewSet(viewsets.ViewSet):
    """
    API pour les statistiques et metrics.
    
    Endpoints:
    - GET /api/stats/platform/ - Stats globales
    - GET /api/stats/driver/{driver_id}/ - Stats livreur
    - GET /api/stats/returns/ - Stats retours
    - GET /api/stats/dashboard/ - Dashboard complet
    """
    
    permission_classes = [permissions.IsAdminUser]
    
    @action(detail=False, methods=['get'], url_path='platform')
    def platform_stats(self, request):
        """📊 Statistiques globales de la plateforme"""
        stats = StatisticsManager.get_platform_stats()
        
        return Response({
            'status': 'success',
            'data': stats
        })
    
    @action(detail=False, methods=['get'], url_path='driver/(?P<driver_id>[^/.]+)')
    def driver_stats(self, request, driver_id=None):
        """🚚 Statistiques d'un livreur"""
        try:
            driver = DeliveryEmployee.objects.get(id=driver_id)
        except DeliveryEmployee.DoesNotExist:
            return Response(
                {'error': 'Livreur introuvable'},
                status=status.HTTP_404_NOT_FOUND
            )
        
        stats = StatisticsManager.get_delivery_agent_stats(driver)
        
        return Response({
            'status': 'success',
            'driver_id': driver_id,
            'data': stats
        })
    
    @action(detail=False, methods=['get'], url_path='returns')
    def return_stats(self, request):
        """🔄 Statistiques des retours"""
        stats = StatisticsManager.get_return_stats()
        
        return Response({
            'status': 'success',
            'data': stats
        })
    
    @action(detail=False, methods=['get'], url_path='dashboard')
    def dashboard(self, request):
        """🎯 Dashboard complet"""
        platform_stats = StatisticsManager.get_platform_stats()
        return_stats = StatisticsManager.get_return_stats()
        
        # Drivers top performers
        top_drivers = DeliveryEmployee.objects.order_by('-rating')[:5]
        drivers_data = [StatisticsManager.get_delivery_agent_stats(d) for d in top_drivers]
        
        return Response({
            'status': 'success',
            'dashboard': {
                'platform': platform_stats,
                'returns': return_stats,
                'top_drivers': drivers_data
            }
        })


# ═══════════════════════════════════════════════════════════════
# ⚙️ Helper: Importer dans urls.py
# ═══════════════════════════════════════════════════════════════

"""
Dans marketplace/urls.py, ajouter:

from .api_views import (
    DeliveryAPIViewSet, ReturnRequestAPIViewSet, StatisticsAPIViewSet
)

router.register('delivery-api', DeliveryAPIViewSet, basename='delivery-api')
router.register('return-api', ReturnRequestAPIViewSet, basename='return-api')
router.register('stats-api', StatisticsAPIViewSet, basename='stats-api')

Les URLs seront:
- /api/delivery-api/assign/ (POST)
- /api/delivery-api/update-status/ (POST)
- /api/delivery-api/update-location/ (POST)
- /api/delivery-api/track/{id}/ (GET)
- /api/delivery-api/handle-failure/ (POST)

- /api/return-api/create/ (POST)
- /api/return-api/list/ (GET)
- /api/return-api/{id}/approve/ (POST)
- /api/return-api/{id}/reject/ (POST)

- /api/stats-api/platform/ (GET)
- /api/stats-api/driver/{id}/ (GET)
- /api/stats-api/returns/ (GET)
- /api/stats-api/dashboard/ (GET)
"""
