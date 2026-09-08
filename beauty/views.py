from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from .models import Studio
from django.http import HttpResponse


def studio_list(request):
    studios = Studio.objects.filter(is_published=True)
    # keep special 'create' card rendered in template
    return render(request, 'beauty/studio_list.html', {'studios': studios})


def studio_detail(request, slug):
    studio = get_object_or_404(Studio, slug=slug)
    return render(request, 'beauty/studio_detail.html', {'studio': studio})


@login_required
def create_studio(request):
    # minimal placeholder: redirect to profile creation flow (to implement)
    if request.method == 'POST':
        # Implement form processing later
        return HttpResponse('Création du studio: fonctionnalité à implémenter')
    return render(request, 'beauty/create_studio.html')
