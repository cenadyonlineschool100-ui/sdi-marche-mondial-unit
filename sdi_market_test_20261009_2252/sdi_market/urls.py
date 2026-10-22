from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.conf.urls.static import static
from django.views.static import serve
from marketplace.views import admin_add_money, admin_add_agent, manage_delivery_assignments
from .request_error_handler import handler500 as custom_handler500
from django.urls import include as dj_include

handler500 = custom_handler500

urlpatterns = [
    path('', include('marketplace.urls')),
    path('beauty-studios/', include('beauty.urls')),
    path('admin/add-money/', admin_add_money, name='admin_add_money'),
    path('admin/add-agent/', admin_add_agent, name='admin_add_agent'),
    path('admin/manage-delivery-assignments/', manage_delivery_assignments, name='admin_manage_delivery_assignments'),
    path('admin/', admin.site.urls),
    path('savings/', include('savings.urls')),
]

# Servir les fichiers médias pour l'instance locale
urlpatterns += [
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
]

if settings.DEBUG:
    try:
        import debug_toolbar
        urlpatterns = [
            path('__debug__/', include(debug_toolbar.urls)),
        ] + urlpatterns
    except Exception:
        # debug_toolbar not installed
        pass