self.addEventListener('push', function (event) {
    let payload = {};
    try {
        payload = event.data ? event.data.json() : {};
    } catch (error) {
        payload = {};
    }

    if (payload.action === 'dismiss') {
        event.waitUntil(self.registration.getNotifications().then(function (notifications) {
            notifications.forEach(function (notification) {
                const notificationId = notification.data && notification.data.notificationId;
                if (payload.id === null || String(notificationId) === String(payload.id)) {
                    notification.close();
                }
            });
        }));
        return;
    }

    const title = payload.title || 'SDI MICROTECH GLOBAL MARKET UNIT';
    const options = {
        body: payload.body || 'Vous avez une nouvelle notification sur SDI.',
        tag: 'sdi-notification-' + String(payload.id || Date.now()),
        data: {
            notificationId: payload.id || null,
            url: payload.url || '/notifications/'
        }
    };

    event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', function (event) {
    event.notification.close();
    const data = event.notification.data || {};
    let destination;
    try {
        destination = new URL(data.url || '/notifications/', self.location.origin);
        if (destination.origin !== self.location.origin) {
            destination = new URL('/notifications/', self.location.origin);
        }
    } catch (error) {
        destination = new URL('/notifications/', self.location.origin);
    }

    event.waitUntil((async function () {
        if (data.notificationId) {
            try {
                const csrfResponse = await fetch('/api/web-push/csrf-token/', { credentials: 'same-origin' });
                const csrfData = await csrfResponse.json();
                await fetch('/api/notifications/persistent/' + encodeURIComponent(data.notificationId) + '/read/', {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: {
                        'Content-Type': 'application/json',
                        'X-CSRFToken': csrfData.csrf_token
                    },
                    body: '{}'
                });
            } catch (error) {
                // Navigation remains useful if the SDI session has expired.
            }
        }

        const windows = await clients.matchAll({ type: 'window', includeUncontrolled: true });
        for (const client of windows) {
            if (new URL(client.url).origin === self.location.origin) {
                if (client.url !== destination.href && client.navigate) {
                    await client.navigate(destination.href);
                }
                return client.focus();
            }
        }
        return clients.openWindow(destination.href);
    })());
});

self.addEventListener('message', function (event) {
    const message = event.data || {};
    event.waitUntil(self.registration.getNotifications().then(function (notifications) {
        notifications.forEach(function (notification) {
            const notificationId = notification.data && notification.data.notificationId;
            if (message.type === 'close-all-notifications' ||
                (message.type === 'close-notification' && String(notificationId) === String(message.id))) {
                notification.close();
            }
        });
    }));
});