from django.db import models
from django.conf import settings
from django.utils.text import slugify


class Studio(models.Model):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='studios')
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    short_desc = models.CharField(max_length=255, blank=True)
    full_desc = models.TextField(blank=True)
    city = models.CharField(max_length=120, blank=True)
    address = models.CharField(max_length=255, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    logo = models.ImageField(upload_to='studios/logos/', blank=True, null=True)
    cover = models.ImageField(upload_to='studios/covers/', blank=True, null=True)
    is_published = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)[:180]
            slug = base
            n = 1
            while Studio.objects.filter(slug=slug).exists():
                slug = f"{base}-{n}"
                n += 1
            self.slug = slug
        super().save(*args, **kwargs)


class Service(models.Model):
    studio = models.ForeignKey(Studio, on_delete=models.CASCADE, related_name='services')
    name = models.CharField(max_length=200)
    image = models.ImageField(upload_to='studios/services/', blank=True, null=True)
    price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    currency = models.CharField(max_length=8, default='$')
    description = models.TextField(blank=True)

    def __str__(self):
        return f"{self.name} — {self.studio.name}"


class Photo(models.Model):
    studio = models.ForeignKey(Studio, on_delete=models.CASCADE, related_name='photos')
    image = models.ImageField(upload_to='studios/gallery/')
    caption = models.CharField(max_length=255, blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order']

    def __str__(self):
        return f"Photo {self.id} for {self.studio.name}"


class Favorite(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    studio = models.ForeignKey(Studio, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'studio')


class Visit(models.Model):
    studio = models.ForeignKey(Studio, on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=True)
    ip = models.CharField(max_length=45, blank=True)

    def __str__(self):
        return f"Visit to {self.studio.name} @ {self.timestamp}"
