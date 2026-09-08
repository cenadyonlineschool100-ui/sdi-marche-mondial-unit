# ==========================================
# GESTION DES CONFIRMATIONS DE LIVRAISON
# ==========================================

@login_required
def confirm_delivery_buyer(request, order_id):
    """L'acheteur confirme qu'il a reçu sa commande"""
    order = get_object_or_404(Order, id=order_id, buyer=request.user)
    
    if order.buyer_confirmed_delivery:
        messages.warning(request, "Vous avez déjà confirmé la réception de cette commande.")
        return redirect('order_detail', order_id=order.id)
    
    if request.method == 'POST':
        order.buyer_confirmed_delivery = True
        order.buyer_confirmed_at = timezone.now()
        order.status = 'delivered'
        order.date_reception_confirmee = timezone.now()
        order.save()
        
        # Envoyer une notification à l'admin
        admin_user = User.objects.filter(is_superuser=True).first()
        if admin_user:
            # Créer un message privé d'alerte
            conversation, created = PrivateConversation.objects.get_or_create(
                user1_id=min(request.user.id, admin_user.id),
                user2_id=max(request.user.id, admin_user.id)
            )
            
            message = PrivateMessage.objects.create(
                conversation=conversation,
                sender=request.user,
                receiver=admin_user,
                content=f"🎉 Commande #{order.id} confirmée comme livrée par l'acheteur {order.buyer.username}. Montant: {order.total_amount} HTG"
            )
            
            # Créer une notification persistante avec sonnerie
            notification = PersistentNotification.objects.create(
                recipient=admin_user,
                title="✅ Confirmation de livraison",
                message=f"Commande #{order.id} de {order.buyer.username} a été confirmée livrée. Montant: {order.total_amount} HTG",
                notification_type='delivery_confirmed',
                related_assignment=None,
                sound_interval_minutes=1  # Sonner chaque minute
            )
        
        messages.success(request, "✅ Merci! Vous avez confirmé la réception de votre commande.")
        return redirect('order_detail', order_id=order.id)
    
    return render(request, 'marketplace/confirm_delivery.html', {'order': order})


@login_required
def confirm_delivery_driver(request, assignment_id):
    """Le livreur confirme qu'il a livré la commande"""
    assignment = get_object_or_404(DeliveryAssignment, id=assignment_id, employee__user=request.user)
    
    if assignment.driver_confirmed_delivery:
        messages.warning(request, "Vous avez déjà confirmé cette livraison.")
        return redirect('delivery_detail', assignment_id=assignment.id)
    
    if request.method == 'POST':
        assignment.driver_confirmed_delivery = True
        assignment.driver_confirmed_at = timezone.now()
        assignment.status = 'delivered'
        assignment.delivered_at = timezone.now()
        assignment.actual_delivery_time = timezone.now()
        assignment.save()
        
        # Mettre à jour la commande
        order = assignment.order
        order.status = 'delivered'
        order.driver_confirmed_delivery = True
        order.driver_confirmed_at = timezone.now()
        order.save()
        
        # Envoyer des notifications
        admin_user = User.objects.filter(is_superuser=True).first()
        if admin_user:
            # Message privé d'alerte pour l'admin
            conversation, created = PrivateConversation.objects.get_or_create(
                user1_id=min(assignment.employee.user.id, admin_user.id),
                user2_id=max(assignment.employee.user.id, admin_user.id)
            )
            
            message = PrivateMessage.objects.create(
                conversation=conversation,
                sender=assignment.employee.user,
                receiver=admin_user,
                content=f"🚚 Le livreur {assignment.employee.identifier} a confirmé la livraison de la commande #{order.id} à {order.buyer.username}. Montant: {order.total_amount} HTG"
            )
            
            # Notification persistante avec sonnerie
            notification = PersistentNotification.objects.create(
                recipient=admin_user,
                title="🚚 Livraison confirmée par le livreur",
                message=f"Livreur {assignment.employee.identifier} - Commande #{order.id} de {order.buyer.username}. Montant: {order.total_amount} HTG",
                notification_type='driver_confirmed_delivery',
                related_assignment=assignment,
                sound_interval_minutes=1
            )
        
        # Notifier l'acheteur
        buyer_notification = PersistentNotification.objects.create(
            recipient=order.buyer,
            title="📦 Votre commande est en cours de livraison!",
            message=f"Le livreur {assignment.employee.identifier} a confirmé qu'il achemine votre commande #{order.id}.",
            notification_type='delivery_in_progress',
            sound_interval_minutes=5  # Moins urgent pour l'acheteur
        )
        
        messages.success(request, "✅ Livraison confirmée! L'administration a été notifiée.")
        return redirect('delivery_detail', assignment_id=assignment.id)
    
    return render(request, 'marketplace/confirm_delivery_driver.html', {'assignment': assignment})


@login_required
def get_delivery_status_api(request, order_id):
    """API pour obtenir le statut actuel d'une commande"""
    order = get_object_or_404(Order, id=order_id)
    
    # Vérifier les permissions
    if request.user != order.buyer and not request.user.is_superuser:
        return JsonResponse({'error': 'Permission denied'}, status=403)
    
    data = {
        'order_id': order.id,
        'status': order.status,
        'buyer_confirmed': order.buyer_confirmed_delivery,
        'driver_confirmed': order.driver_confirmed_delivery,
        'admin_notified': order.admin_notified,
        'buyer_confirmed_at': order.buyer_confirmed_at.isoformat() if order.buyer_confirmed_at else None,
        'driver_confirmed_at': order.driver_confirmed_at.isoformat() if order.driver_confirmed_at else None,
    }
    
    return JsonResponse(data)


@login_required
def acknowledge_delivery_notification(request, order_id):
    """L'acheteur reconnaît l'alerte de livraison"""
    order = get_object_or_404(Order, id=order_id, buyer=request.user)
    
    if request.method == 'POST':
        # Marquer les notifications comme lues
        PersistentNotification.objects.filter(
            recipient=request.user,
            notification_type__in=['delivery_in_progress', 'delivery_confirmed'],
            is_read=False
        ).update(is_read=True, read_at=timezone.now())
        
        return JsonResponse({'status': 'success', 'message': 'Notification acknowledged'})
    
    return JsonResponse({'error': 'Method not allowed'}, status=405)


@login_required 
def list_pending_deliveries(request):
    """Liste toutes les livraisons en attente de confirmation (pour acheteur et livreur)"""
    pending_orders = []
    pending_assignments = []
    
    # Commandes en attente de confirmation de l'acheteur
    if request.user.is_buyer:
        pending_orders = Order.objects.filter(
            buyer=request.user,
            status='delivered',
            buyer_confirmed_delivery=False
        ).order_by('-created_at')
    
    # Livraisons en attente de confirmation du livreur
    if request.user.is_delivery_agent:
        pending_assignments = DeliveryAssignment.objects.filter(
            employee__user=request.user,
            status__in=['arrived', 'in_transit'],
            driver_confirmed_delivery=False
        ).order_by('-assigned_at')
    
    context = {
        'pending_orders': pending_orders,
        'pending_assignments': pending_assignments,
    }
    
    return render(request, 'marketplace/pending_deliveries.html', context)


