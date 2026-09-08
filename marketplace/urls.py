from django.http import HttpResponse
from django.urls import include, path
from rest_framework.routers import DefaultRouter
from . import real_estate_urls
from .views import (
    AdminViewSet, ProductViewSet, ShopViewSet, OrderViewSet, WalletViewSet,
    TransactionViewSet, DeliveryAssignmentViewSet, DeliveryEmployeeViewSet,
    AgentViewSet, ReturnRequestViewSet, add_product, admin_add_money, admin_add_agent, confirm_delivery, dashboard, home, marche_mondial, hide_order_timer, login_view, logout_view, order_confirm,
    password_reset_request,
    optimize_performance,
    agent_codes,
    sdi_transport,
    studio_beaute, studio_beaute_request, studio_beaute_requests_admin,
    order_history, order_product, product_detail, profile, get_recipient_account_info, transfer_funds, set_currency, manage_delivery_access, request_delivery_access, search, shop_detail, signup, stats, system_view,
    technician_profiles, technician_profile_create, technician_profile_detail,
    request_product_access,
    autocomplete_products, cart_view, add_to_cart, remove_from_cart, update_cart_item, clear_cart, checkout, category_products,
    delivery_tracking, return_request, delivery_dashboard, chat, chat_messages_api,
    course_detail, course_assignments, course_recordings, course_certificates, course_certificate_pdf,
    private_chat_contacts, private_chat, private_chat_messages_api, private_chat_unread_count_api,
    generate_product_image_api, get_image_suggestions_api,  # APIs génération d'images
    driver_dashboard, my_shop, manage_delivery_assignments, assign_order_to_driver, reassign_delivery_order,
    system_control_panel, refresh_exchange_rates, security_dashboard_api, view_user_password,  # Contrôle système - Gestion mots de passe et sécurité
    site_banner_activation, site_banner_activation_toggle, site_banner_expand_settings, site_banner_dashboard, site_gp_dashboard, site_banner_autoplay_toggle, site_banner_product_toggle, site_banner_toggle, site_banner_delete, site_banner_image_add, site_banner_image_delete, site_banner_image_crop, site_banner_crop, site_banner_permission, site_banner_access, site_banner_impression, site_banner_click, site_banner_purchase,
    # Notifications persistantes
    get_persistent_notifications_api, mark_persistent_notification_read_api, check_notifications_sound_api,
    persistent_notifications_page, mark_all_persistent_notifications_read_api,
    # Confirmations de livraison
    confirm_delivery_buyer, confirm_delivery_driver,
    withdraw_funds, upload_receipt, upload_identity, save_recharge_message, upload_selfie, view_receipts, process_receipt, view_withdrawal_receipt,
    transfer_receipts, view_transfer_receipt,
    sdi_sol_page, sdi_sol_join, sdi_sol_payments, sdi_sol_make_payment, sdi_sol_payment_receipt, sdi_sol_admin, sdi_sol_admin_remove_member, sdi_sol_admin_approve_member,
    tikane_access, formations_en_ligne, live_room_webrtc, live_room_jitsi, admin_tikane_requests, admin_tikane_plans,
    demo_page, microordinateur, manage_projet,
)
from .views_deposit import (
    agent_deposit_view, deposit_confirmation,
    agent_deposit_history, download_deposit_receipt,
    view_deposit_receipt, client_deposit_receipts
)
from .views_deposit import agent_client_deposit_receipts
from .api_security import (
    get_vulnerabilities, fix_vulnerability, run_security_audit,
    get_ai_recommendations, continuous_monitoring_config, security_statistics,
    ai_security_chat, ai_security_analysis, ai_port_scan, ai_threat_detection,
    ai_system_health, ai_recommendations, ai_security_alert, ai_realtime_monitoring,
    soc_dashboard_data,
)
from .views_logos import (
    manage_logos, update_logo, grant_logo_permission, revoke_logo_permission
)
from .views_commission import (
    manage_agent_commissions, edit_deposit_commission_config, edit_agent_commission_rule, add_agent_commission_rule,
    delete_agent_commission_rule, grant_commission_permission, revoke_commission_permission,
    view_agent_deposit_history, manage_withdrawal_commissions,
    update_commission_share_settings, distribute_commission_pool, return_commission_pool_to_system,
    assign_commission_category, toggle_commission_category, view_peuple_commission,
    commission_peuple_configuration_adm
)
from .views_admin_permissions import (
    manage_admin_permissions, toggle_admin_permission, grant_withdrawal_access, revoke_withdrawal_access,
    toggle_principal_power,
)
from .views_agent_withdrawal import (
    agent_withdrawal_dashboard, agent_process_withdrawal, agent_user_search
)
from .views_admin_announcements import (
    announcements_list, announcement_create, announcement_edit, announcement_delete,
    announcement_toggle_active, announcement_toggle_priority, get_active_announcements,
    announcement_record_view, announcement_record_click
)
from .api_views import (
    DeliveryAPIViewSet, ReturnRequestAPIViewSet, StatisticsAPIViewSet
)
from .modules_manager import (
    get_module_list, load_module_data, get_module_stats, invalidate_module_cache
)

router = DefaultRouter()
router.register('products', ProductViewSet)
router.register('shops', ShopViewSet)
router.register('orders', OrderViewSet)
router.register('wallets', WalletViewSet)
router.register('transactions', TransactionViewSet)
router.register('delivery-employees', DeliveryEmployeeViewSet)
router.register('delivery-assignments', DeliveryAssignmentViewSet)
router.register('agents', AgentViewSet)
router.register('return-requests', ReturnRequestViewSet)
router.register('admin', AdminViewSet, basename='admin')
# Nouvelles APIs métier
router.register('delivery-api', DeliveryAPIViewSet, basename='delivery-api')
router.register('return-api', ReturnRequestAPIViewSet, basename='return-api')
router.register('stats-api', StatisticsAPIViewSet, basename='stats-api')

urlpatterns = [
    # APIs génération d'images
    path('api/generate-image/', generate_product_image_api, name='generate_product_image'),
    path('api/image-suggestions/', get_image_suggestions_api, name='image_suggestions'),

    path('', home, name='site_root'),
    path('home/', home, name='home'),
    path('marche-mondial/', marche_mondial, name='marche_mondial'),
    path('demo/', demo_page, name='demo'),
    path('sdi-transport/', sdi_transport, name='sdi_transport'),
    path('microordinateur/', microordinateur, name='microordinateur'),
    path('manage-projet/', manage_projet, name='manage_projet'),
    path('s/', search, name='search_short'),
    path('search/', search, name='search'),
    path('formations-en-ligne/', formations_en_ligne, name='formations_en_ligne'),
    path('live/webrtc/<int:course_id>/', live_room_webrtc, name='live_webrtc'),
    path('live/jitsi/<int:course_id>/', live_room_jitsi, name='live_jitsi'),
    path('set-currency/', set_currency, name='set_currency'),
    path('signup/', signup, name='signup'),
    path('login/', login_view, name='login'),
    path('password-reset/', password_reset_request, name='password_reset'),
    path('logout/', logout_view, name='logout'),
    path('category/<slug:category_slug>/', category_products, name='category_products'),
    path('autocomplete/', autocomplete_products, name='autocomplete_products'),
    path('cart/', cart_view, name='cart'),
    path('cart/add/<int:product_id>/', add_to_cart, name='add_to_cart'),
    path('cart/remove/<int:item_id>/', remove_from_cart, name='remove_from_cart'),
    path('cart/update/<int:item_id>/', update_cart_item, name='update_cart_item'),
    path('cart/clear/', clear_cart, name='clear_cart'),
    path('checkout/', checkout, name='checkout'),
    path('profile/', profile, name='profile'),
    path('techniciens/', technician_profiles, name='technician_profiles'),
    path('technicien/creer/', technician_profile_create, name='technician_profile_create'),
    path('technicien/<slug:profile_slug>/', technician_profile_detail, name='technician_profile_detail'),
    path('course/<int:course_id>/', course_detail, name='course_detail'),
    path('course/<int:course_id>/assignments/', course_assignments, name='course_assignments'),
    path('course/<int:course_id>/recordings/', course_recordings, name='course_recordings'),
    path('course/<int:course_id>/certificates/', course_certificates, name='course_certificates'),
    path('course/<int:course_id>/certificates/<int:certificate_id>/pdf/', course_certificate_pdf, name='course_certificate_pdf'),
    path('profile/studio-beaute/', studio_beaute, name='studio_beaute'),
    path('profile/studio-beaute/create/', studio_beaute_request, name='studio_beaute_request'),
    path('profile/studio-beaute/admin/', studio_beaute_requests_admin, name='studio_beaute_requests_admin'),
    path('profile/recipient-info/', get_recipient_account_info, name='get_recipient_account_info'),
    path('profile/transfer/', transfer_funds, name='transfer_funds'),
    path('profile/transfer/receipts/', transfer_receipts, name='transfer_receipts'),
    path('profile/transfer/receipt/<int:receipt_id>/', view_transfer_receipt, name='view_transfer_receipt'),
    path('profile/transfer/receipts/', transfer_receipts, name='transfer_receipts'),
    path('profile/transfer/receipt/<int:receipt_id>/', view_transfer_receipt, name='view_transfer_receipt'),
    path('upload-receipt/', upload_receipt, name='upload_receipt'),
    path('upload-identity/', upload_identity, name='upload_identity'),
    path('save-recharge-message/', save_recharge_message, name='save_recharge_message'),
    path('upload-selfie/', upload_selfie, name='upload_selfie'),
    path('admin/receipts/', view_receipts, name='view_receipts'),
    path('admin/receipts/<int:receipt_id>/process/', process_receipt, name='process_receipt'),
    path('withdraw/', withdraw_funds, name='withdraw_funds'),
    path('withdrawal-receipt/<int:withdrawal_id>/', view_withdrawal_receipt, name='view_withdrawal_receipt'),
    path('manage-delivery-access/<int:user_id>/<str:action>/', manage_delivery_access, name='manage_delivery_access'),
    path('request-delivery-access/', request_delivery_access, name='request_delivery_access'),
    path('tikane/', tikane_access, name='tikane_access'),
    path('admin/tikane/requests/', admin_tikane_requests, name='admin_tikane_requests'),
    path('admin/tikane/plans/', admin_tikane_plans, name='admin_tikane_plans'),
    path('admin/optimize-performance/', optimize_performance, name='optimize_performance'),
    path('admin/optimize-performance', optimize_performance),
    path('my-shop/', my_shop, name='my_shop'),
    path('dashboard/', dashboard, name='dashboard'),
    path('admin/banniere/activation/', site_banner_activation, name='site_banner_activation'),
    path('admin/banniere/activation/toggle/', site_banner_activation_toggle, name='site_banner_activation_toggle'),
    path('admin/banniere/agrandissement/', site_banner_expand_settings, name='site_banner_expand_settings'),
    path('admin/banniere/', site_banner_dashboard, name='site_banner_dashboard'),
    path('admin/gp/', site_gp_dashboard, name='site_gp_dashboard'),
    path('admin/banniere/<int:banner_id>/toggle/', site_banner_toggle, name='site_banner_toggle'),
    path('admin/banniere/<int:banner_id>/autoplay/toggle/', site_banner_autoplay_toggle, name='site_banner_autoplay_toggle'),
    path('admin/banniere/product/<int:product_id>/toggle/', site_banner_product_toggle, name='site_banner_product_toggle'),
    path('admin/banniere/<int:banner_id>/delete/', site_banner_delete, name='site_banner_delete'),
    path('admin/banniere/<int:banner_id>/images/add/', site_banner_image_add, name='site_banner_image_add'),
    path('admin/banniere/images/<int:image_id>/delete/', site_banner_image_delete, name='site_banner_image_delete'),
    path('admin/banniere/images/<int:image_id>/crop/', site_banner_image_crop, name='site_banner_image_crop'),
    path('admin/banniere/<int:banner_id>/crop/', site_banner_crop, name='site_banner_crop'),
    path('admin/banniere/<int:banner_id>/permission/', site_banner_permission, name='site_banner_permission'),
    path('admin/banniere/<int:banner_id>/access/', site_banner_access, name='site_banner_access'),
    path('banniere/<int:banner_id>/impression/', site_banner_impression, name='site_banner_impression'),
    path('banniere/<int:banner_id>/click/', site_banner_click, name='site_banner_click'),
    path('banniere/<int:banner_id>/purchase/', site_banner_purchase, name='site_banner_purchase'),
    path('sdi-sol/', sdi_sol_page, name='sdi_sol'),
    path('sdi-sol/join/', sdi_sol_join, name='sdi_sol_join'),
    path('sdi-sol/payments/', sdi_sol_payments, name='sdi_sol_payments'),
    path('sdi-sol/payment/make/', sdi_sol_make_payment, name='sdi_sol_make_payment'),
    path('sdi-sol/payment/receipt/<str:receipt_id>/', sdi_sol_payment_receipt, name='sdi_sol_payment_receipt'),
    path('sdi-sol/admin/', sdi_sol_admin, name='sdi_sol_admin'),
    path('sdi-sol/admin/approve-member/<int:member_id>/', sdi_sol_admin_approve_member, name='sdi_sol_admin_approve_member'),
    path('sdi-sol/admin/remove-member/<int:member_id>/', sdi_sol_admin_remove_member, name='sdi_sol_admin_remove_member'),
    path('agent/deposit/', agent_deposit_view, name='agent_deposit'),
    path('agent/deposit/confirmation/<int:deposit_id>/', deposit_confirmation, name='deposit_confirmation'),
    path('agent/deposit/receipt/<int:receipt_id>/download/', download_deposit_receipt, name='download_deposit_receipt'),
    path('agent/deposit/receipt/<int:receipt_id>/view/', view_deposit_receipt, name='view_deposit_receipt'),
    path('deposit/receipts/', client_deposit_receipts, name='client_deposit_receipts'),
    path('agent/client/<int:client_id>/receipts/', agent_client_deposit_receipts, name='agent_client_deposit_receipts'),
    path('agent/deposit/history/', agent_deposit_history, name='agent_deposit_history'),
    path('agent/codes/', agent_codes, name='agent_codes'),
    path('shop/<int:shop_id>/', shop_detail, name='shop_detail'),
    path('add-product/', add_product, name='add_product_alias'),
    path('shop/add-product/', add_product, name='add_product'),
    path('system-view/', system_view, name='system_view'),
    path('product/<int:product_id>/', product_detail, name='product_detail'),
    path('product/<int:product_id>/request-access/', request_product_access, name='request_product_access'),
    path('product/<int:product_id>/buy/', order_product, name='order_product'),
    path('order/<int:order_id>/', order_confirm, name='order_confirm'),
    path('order/<int:order_id>/confirm-delivery/', confirm_delivery, name='confirm_delivery'),
    path('order/<int:order_id>/hide-timer/', hide_order_timer, name='order_hide_timer'),
    path('order-history/', order_history, name='order_history'),
    path('delivery-tracking/', delivery_tracking, name='delivery_tracking'),
    path('delivery-tracking/<int:order_id>/', delivery_tracking, name='delivery_tracking_detail'),
    path('return-request/<int:order_id>/', return_request, name='return_request'),
    path('chat/', chat, name='chat'),
    path('chat/messages/', chat_messages_api, name='chat_messages_api'),
    path('chat/private/', private_chat_contacts, name='private_chat_contacts'),
    path('chat/private/<int:user_id>/', private_chat, name='private_chat'),
    path('chat/private/<int:user_id>/messages/', private_chat_messages_api, name='private_chat_messages_api'),
    path('chat/private/unread-count/', private_chat_unread_count_api, name='private_chat_unread_count_api'),
    path('stats/', stats, name='stats'),
    path('test/', lambda r: HttpResponse('Hello World'), name='test'),
    path('delivery-dashboard/', delivery_dashboard, name='delivery_dashboard'),
    path('driver-dashboard/', driver_dashboard, name='driver_dashboard'),
    path('admin/add-agent/', admin_add_agent, name='admin_add_agent'),
    # Gestion des assignations de livreurs
    path('manage-delivery-assignments/', manage_delivery_assignments, name='manage_delivery_assignments'),
    path('assign-order-to-driver/', assign_order_to_driver, name='assign_order_to_driver'),
    path('reassign-order/<int:order_id>/', reassign_delivery_order, name='reassign_delivery_order'),
    # Contrôle Système - Gestion des Mots de Passe
    path('system-control/', system_control_panel, name='system_control_panel'),
    path('system-control/refresh-exchange-rates/', refresh_exchange_rates, name='refresh_exchange_rates'),
    path('api/security-dashboard/', security_dashboard_api, name='security_dashboard_api'),
    path('api/user/<int:user_id>/password/', view_user_password, name='view_user_password'),
    
    # API CYBERSÉCURITÉ INTELLIGENTE
    path('api/security/vulnerabilities/', get_vulnerabilities, name='get_vulnerabilities'),
    path('api/security/vulnerabilities/fix/', fix_vulnerability, name='fix_vulnerability'),
    path('api/security/audit/run/', run_security_audit, name='run_security_audit'),
    path('api/security/recommendations/', get_ai_recommendations, name='get_ai_recommendations'),
    path('api/security/monitoring/', continuous_monitoring_config, name='continuous_monitoring_config'),
    path('api/security/statistics/', security_statistics, name='security_statistics'),
    
    # API CHAT IA CYBERSÉCURITÉ - SOC AVANCÉ
    path('api/ai/chat/', ai_security_chat, name='ai_security_chat'),
    path('api/ai/analysis/', ai_security_analysis, name='ai_security_analysis'),
    path('api/ai/port-scan/', ai_port_scan, name='ai_port_scan'),
    path('api/ai/threat-detection/', ai_threat_detection, name='ai_threat_detection'),
    path('api/ai/system-health/', ai_system_health, name='ai_system_health'),
    path('api/ai/recommendations/', ai_recommendations, name='ai_recommendations'),
    path('api/ai/alert/', ai_security_alert, name='ai_security_alert'),
    path('api/ai/realtime-monitoring/', ai_realtime_monitoring, name='ai_realtime_monitoring'),
    path('api/soc/dashboard/', soc_dashboard_data, name='soc_dashboard_data'),

    
    # Notifications persistantes avec sonnerie
    path('api/notifications/persistent/', get_persistent_notifications_api, name='get_persistent_notifications_api'),
    path('api/notifications/persistent/<int:notification_id>/read/', mark_persistent_notification_read_api, name='mark_persistent_notification_read_api'),
    path('api/notifications/sound/', check_notifications_sound_api, name='check_notifications_sound_api'),
    path('api/notifications/mark-all-read/', mark_all_persistent_notifications_read_api, name='mark_all_persistent_notifications_read_api'),
    path('notifications/', persistent_notifications_page, name='persistent_notifications_page'),
    # Confirmations de livraison
    path('order/<int:order_id>/confirm-delivery-buyer/', confirm_delivery_buyer, name='confirm_delivery_buyer'),
    path('delivery/<int:assignment_id>/confirm-delivery-driver/', confirm_delivery_driver, name='confirm_delivery_driver'),
    # Gestion des logos du site (Admin principal)
    path('admin/logos/', manage_logos, name='manage_logos'),
    path('admin/logos/<int:logo_id>/update/', update_logo, name='update_logo'),
    path('admin/logos/grant-permission/<int:user_id>/', grant_logo_permission, name='grant_logo_permission'),
    path('admin/logos/revoke-permission/<int:user_id>/', revoke_logo_permission, name='revoke_logo_permission'),
    
    # Gestion des commissions des dépôts agents
    path('admin/commissions/', manage_agent_commissions, name='manage_agent_commissions'),
    path('admin/commissions/peuple-config/', commission_peuple_configuration_adm, name='commission_peuple_configuration_adm'),
    path('admin/commissions/deposit-config/<int:config_id>/edit/', edit_deposit_commission_config, name='edit_deposit_commission_config'),
    path('admin/commissions/rule/<int:rule_id>/edit/', edit_agent_commission_rule, name='edit_agent_commission_rule'),
    path('admin/commissions/agent/<int:agent_id>/add-rule/', add_agent_commission_rule, name='add_agent_commission_rule'),
    path('admin/commissions/rule/<int:rule_id>/delete/', delete_agent_commission_rule, name='delete_agent_commission_rule'),
    path('admin/commissions/grant/<int:user_id>/', grant_commission_permission, name='grant_commission_permission'),
    path('admin/commissions/revoke/<int:user_id>/', revoke_commission_permission, name='revoke_commission_permission'),
    path('admin/commissions/agent/<int:agent_id>/history/', view_agent_deposit_history, name='view_agent_deposit_history'),
    path('admin/commissions/settings/update/', update_commission_share_settings, name='update_commission_share_settings'),
    path('admin/commissions/distribute/', distribute_commission_pool, name='distribute_commission_pool'),
    path('admin/commissions/return/', return_commission_pool_to_system, name='return_commission_pool_to_system'),
    path('admin/commissions/categories/assign/', assign_commission_category, name='assign_commission_category'),
    path('admin/commissions/categories/toggle/<int:category_id>/', toggle_commission_category, name='toggle_commission_category'),
    path('admin/commissions/withdrawal/', manage_withdrawal_commissions, name='manage_withdrawal_commissions'),
    path('commission-peuple/', view_peuple_commission, name='view_peuple_commission'),
    # Gestion des permissions administrateur
    path('admin/permissions/', manage_admin_permissions, name='manage_admin_permissions'),
    path('admin/permissions/toggle/<int:user_id>/<str:permission_codename>/', toggle_admin_permission, name='toggle_admin_permission'),
    path('admin/permissions/grant-withdrawal/<int:user_id>/', grant_withdrawal_access, name='grant_withdrawal_access'),
    path('admin/permissions/revoke-withdrawal/<int:user_id>/', revoke_withdrawal_access, name='revoke_withdrawal_access'),
    path('admin/permissions/principal/<int:user_id>/', toggle_principal_power, name='toggle_principal_power'),
    # Retrait pour les agents
    path('agent/withdrawal/dashboard/', agent_withdrawal_dashboard, name='agent_withdrawal_dashboard'),
    path('agent/withdrawal/process/', agent_process_withdrawal, name='agent_process_withdrawal'),
    path('api/agent/user-search/', agent_user_search, name='agent_user_search'),
    # Gestion des Annonces Administratives
    path('announcements/', announcements_list, name='announcements_list'),
    path('announcements/create/', announcement_create, name='announcement_create'),
    path('announcements/<int:pk>/edit/', announcement_edit, name='announcement_edit'),
    path('announcements/<int:pk>/delete/', announcement_delete, name='announcement_delete'),
    path('announcements/<int:pk>/toggle-active/', announcement_toggle_active, name='announcement_toggle_active'),
    path('announcements/<int:pk>/toggle-priority/', announcement_toggle_priority, name='announcement_toggle_priority'),
    path('api/announcements/active/', get_active_announcements, name='get_active_announcements'),
    path('announcements/<int:pk>/record-view/', announcement_record_view, name='announcement_record_view'),
    path('announcements/<int:pk>/record-click/', announcement_record_click, name='announcement_record_click'),
    
    # === API MODULES - Lazy Loading & Architecture Modulaire ===
    path('api/modules/', get_module_list, name='get_module_list'),
    path('api/modules/<str:module_name>/load/', load_module_data, name='load_module_data'),
    path('api/modules/<str:module_name>/stats/', get_module_stats, name='get_module_stats'),
    path('api/modules/all/stats/', get_module_stats, name='get_all_module_stats'),
    path('api/modules/<str:module_name>/cache/invalidate/', invalidate_module_cache, name='invalidate_module_cache'),
    
    # Module Immobilier - Maison à Louer
    path('immobilier/', include((real_estate_urls, 'real_estate'), namespace='real_estate')),
    path('api/', include(router.urls)),
]
