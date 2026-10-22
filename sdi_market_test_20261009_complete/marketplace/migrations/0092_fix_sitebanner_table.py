from django.db import migrations


def fix_sitebanner_table(apps, schema_editor):
    connection = schema_editor.connection
    table_name = 'marketplace_sitebanner'

    table_names = connection.introspection.table_names()
    if table_name not in table_names:
        return

    columns = [row[1] for row in connection.introspection.get_table_description(connection.cursor(), table_name)]
    if 'product_id' in columns and 'display_order' in columns and 'created_at' in columns:
        return

    Product = apps.get_model('marketplace', 'Product')
    default_product_id = Product.objects.order_by('id').values_list('id', flat=True).first() or 1

    with connection.cursor() as cursor:
        cursor.execute(
            '''
            CREATE TABLE "marketplace_sitebanner_new" (
                "id" integer NOT NULL PRIMARY KEY AUTOINCREMENT,
                "title" varchar(120) NOT NULL,
                "subtitle" varchar(220) NOT NULL,
                "button_text" varchar(40) NOT NULL,
                "image" varchar(100) NULL,
                "is_active" bool NOT NULL,
                "display_order" integer NOT NULL,
                "start_date" datetime NULL,
                "end_date" datetime NULL,
                "created_at" datetime NOT NULL,
                "updated_at" datetime NOT NULL,
                "product_id" bigint NOT NULL REFERENCES "marketplace_product" ("id") DEFERRABLE INITIALLY DEFERRED
            )
            '''
        )

        cursor.execute(
            '''
            INSERT INTO "marketplace_sitebanner_new"
                ("id", "title", "subtitle", "button_text", "image", "is_active", "display_order", "start_date", "end_date", "created_at", "updated_at", "product_id")
            SELECT
                "id",
                COALESCE("title", 'Offre du moment'),
                COALESCE("subtitle", 'Produit phare de la semaine'),
                COALESCE("button_text", 'Voir le produit'),
                "image",
                COALESCE("is_active", 1),
                0,
                NULL,
                NULL,
                COALESCE("updated_at", datetime('now')),
                COALESCE("updated_at", datetime('now')),
                %s
            FROM "marketplace_sitebanner"
            ''' % default_product_id
        )

        cursor.execute('DROP TABLE "marketplace_sitebanner"')
        cursor.execute('ALTER TABLE "marketplace_sitebanner_new" RENAME TO "marketplace_sitebanner"')


class Migration(migrations.Migration):
    dependencies = [
        ('marketplace', '0089_sitebanner'),
    ]

    operations = [
        migrations.RunPython(fix_sitebanner_table, migrations.RunPython.noop),
    ]
