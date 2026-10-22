from django.contrib import admin
from .models import Studio, Service, Photo, Favorite, Visit


@admin.register(Studio)
class StudioAdmin(admin.ModelAdmin):
    list_display = ('name', 'owner', 'city', 'phone', 'is_published', 'created_at')
    search_fields = ('name', 'short_desc', 'full_desc', 'city')
    prepopulated_fields = {'slug': ('name',)}


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ('name', 'studio', 'price')
    search_fields = ('name', 'studio__name')


@admin.register(Photo)
class PhotoAdmin(admin.ModelAdmin):
    list_display = ('studio', 'caption', 'order')


@admin.register(Favorite)
class FavoriteAdmin(admin.ModelAdmin):
    list_display = ('user', 'studio', 'created_at')


@admin.register(Visit)
class VisitAdmin(admin.ModelAdmin):
    list_display = ('studio', 'timestamp', 'ip')
