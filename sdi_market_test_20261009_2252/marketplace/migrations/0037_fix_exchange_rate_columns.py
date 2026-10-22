from django.db import migrations, models, connection


def add_missing_exchange_rate_columns(apps, schema_editor):
    table_name = 'marketplace_exchangerate'
    existing_columns = set()
    with connection.cursor() as cursor:
        cursor.execute(f"PRAGMA table_info('{table_name}')")
        for row in cursor.fetchall():
            existing_columns.add(row[1])

    alter_statements = []
    if 'eur_to_usd' not in existing_columns:
        alter_statements.append("ALTER TABLE marketplace_exchangerate ADD COLUMN eur_to_usd DECIMAL(15,6) DEFAULT 0")
    if 'eur_to_htg' not in existing_columns:
        alter_statements.append("ALTER TABLE marketplace_exchangerate ADD COLUMN eur_to_htg DECIMAL(15,6) DEFAULT 0")
    if 'eur_to_peso' not in existing_columns:
        alter_statements.append("ALTER TABLE marketplace_exchangerate ADD COLUMN eur_to_peso DECIMAL(15,6) DEFAULT 0")

    with connection.cursor() as cursor:
        for stmt in alter_statements:
            cursor.execute(stmt)


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ('marketplace', '0036_exchangerate_eur_to_htg_exchangerate_eur_to_peso_and_more'),
    ]

    operations = [
        migrations.RunPython(add_missing_exchange_rate_columns, noop),
    ]
