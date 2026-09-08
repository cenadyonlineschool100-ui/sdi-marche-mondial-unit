from django.urls import path
from . import views

app_name = 'savings'

urlpatterns = [
    path('', views.list_plans, name='list_plans'),
    path('choose/<int:plan_id>/', views.choose_plan, name='choose_plan'),
    path('admin/remove/<int:subscription_id>/', views.admin_remove_subscription, name='admin_remove_subscription'),
]
