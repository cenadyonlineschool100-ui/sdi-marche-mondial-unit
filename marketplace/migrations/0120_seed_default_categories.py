from django.db import migrations


CATEGORIES = (
    ('Électronique', 'electronique'),
    ('Mode', 'mode'),
    ('Maison & déco', 'maison-deco'),
    ('Beauté', 'beaute'),
    ('Alimentation', 'alimentation'),
)


def seed_default_categories(apps, schema_editor):
    Category = apps.get_model('marketplace', 'Category')
    database = schema_editor.connection.alias

    for name, slug in CATEGORIES:
        categories = Category.objects.using(database)
        by_slug = categories.filter(slug=slug).first()
        by_name = categories.filter(name=name).first()

        if by_slug and by_name and by_slug.pk != by_name.pk:
            raise RuntimeError(
                f'Conflicting marketplace categories for {name!r} ({slug!r}).'
            )

        category = by_slug or by_name
        if category is None:
            Category.objects.using(database).create(
                name=name,
                slug=slug,
                is_active=True,
                parent_id=None,
            )
            continue

        category.name = name
        category.slug = slug
        category.is_active = True
        category.parent_id = None
        category.save(
            using=database,
            update_fields=('name', 'slug', 'is_active', 'parent'),
        )


class Migration(migrations.Migration):

    dependencies = [
        ('marketplace', '0119_alter_paypalpayment_status_paypalstockevent_and_more'),
    ]

    operations = [
        migrations.RunPython(
            seed_default_categories,
            migrations.RunPython.noop,
        ),
    ]
