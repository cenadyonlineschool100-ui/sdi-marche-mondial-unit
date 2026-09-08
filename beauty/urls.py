from django.urls import path
from . import views

app_name = 'beauty'

urlpatterns = [
    path('', views.studio_list, name='studio_list'),
    path('create/', views.create_studio, name='create_studio'),
    path('<slug:slug>/', views.studio_detail, name='studio_detail'),
]
