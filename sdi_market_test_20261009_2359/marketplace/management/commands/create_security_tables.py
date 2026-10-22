from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = 'Create missing security tables'

    def handle(self, *args, **options):
        with connection.cursor() as cursor:
            # Create SecurityEvent table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS marketplace_securityevent (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type VARCHAR(50) NOT NULL,
                    source_ip VARCHAR(50),
                    path VARCHAR(255),
                    method VARCHAR(10),
                    status_code INTEGER,
                    response_time_ms INTEGER,
                    user_agent VARCHAR(500),
                    description TEXT,
                    created_at DATETIME NOT NULL,
                    user_id INTEGER REFERENCES marketplace_user(id)
                )
            ''')

            # Create IPBlocklist table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS marketplace_ipblocklist (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ip_address VARCHAR(50) NOT NULL UNIQUE,
                    reason VARCHAR(255),
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    created_at DATETIME NOT NULL,
                    blocked_until DATETIME,
                    created_by_id INTEGER REFERENCES marketplace_user(id)
                )
            ''')

            # Create indexes for SecurityEvent
            cursor.execute('CREATE INDEX IF NOT EXISTS marketplace_securityevent_created_at_idx ON marketplace_securityevent (created_at DESC)')
            cursor.execute('CREATE INDEX IF NOT EXISTS marketplace_securityevent_source_ip_created_at_idx ON marketplace_securityevent (source_ip, created_at DESC)')
            cursor.execute('CREATE INDEX IF NOT EXISTS marketplace_securityevent_event_type_created_at_idx ON marketplace_securityevent (event_type, created_at DESC)')

            self.stdout.write(self.style.SUCCESS('Successfully created security tables'))