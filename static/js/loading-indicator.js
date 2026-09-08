/**
 * Loading Indicator System - Critical Performance Module
 * Provides instant visual feedback for user actions (< 50ms response)
 */

class PerformanceIndicator {
    constructor() {
        this.activeRequests = 0;
        this.bar = null;
        this.spinner = null;
        this.badge = null;
        this.init();
    }

    init() {
        this.createUI();
        this.interceptFetch();
        this.interceptXHR();
        this.setupButtonInterception();
    }

    createUI() {
        // Top progress bar
        this.bar = document.createElement('div');
        this.bar.className = 'loading-indicator';
        this.bar.id = 'perf-loading-bar';
        document.body.appendChild(this.bar);

        // Spinner modal
        this.spinner = document.createElement('div');
        this.spinner.className = 'loading-spinner';
        this.spinner.id = 'perf-loading-spinner';
        this.spinner.innerHTML = '<div class="spinner"></div>';
        document.body.appendChild(this.spinner);

        // Badge showing active requests
        this.badge = document.createElement('div');
        this.badge.className = 'loading-badge';
        this.badge.id = 'perf-loading-badge';
        document.body.appendChild(this.badge);
    }

    show(options = {}) {
        this.activeRequests++;
        
        // Show bar immediately (< 10ms)
        if (this.activeRequests === 1) {
            this.bar?.classList.add('active');
        }

        // Show spinner for longer requests (> 500ms)
        if (options.showSpinner !== false) {
            setTimeout(() => {
                if (this.activeRequests > 0) {
                    this.spinner?.classList.add('active');
                }
            }, 500);
        }

        // Update badge
        this.updateBadge();
    }

    hide() {
        this.activeRequests = Math.max(0, this.activeRequests - 1);
        
        if (this.activeRequests === 0) {
            this.bar?.classList.remove('active');
            this.spinner?.classList.remove('active');
            this.badge?.classList.remove('active');
        } else {
            this.updateBadge();
        }
    }

    updateBadge() {
        if (this.activeRequests > 0) {
            this.badge.textContent = `⏳ ${this.activeRequests} requête${this.activeRequests > 1 ? 's' : ''}`;
            this.badge.classList.add('active');
        }
    }

    interceptFetch() {
        const originalFetch = window.fetch;
        const self = this;

        window.fetch = function(...args) {
            self.show();
            return originalFetch.apply(this, args)
                .finally(() => self.hide());
        };
    }

    interceptXHR() {
        const self = this;
        const originalOpen = XMLHttpRequest.prototype.open;
        const originalSend = XMLHttpRequest.prototype.send;

        XMLHttpRequest.prototype.open = function(method, url, ...args) {
            this._perfTracking = { method, url };
            return originalOpen.apply(this, [method, url, ...args]);
        };

        XMLHttpRequest.prototype.send = function(...args) {
            self.show();
            
            const onStateChange = () => {
                if (this.readyState === XMLHttpRequest.DONE) {
                    self.hide();
                }
            };

            this.addEventListener('readystatechange', onStateChange);
            this.addEventListener('error', () => self.hide());
            this.addEventListener('abort', () => self.hide());

            return originalSend.apply(this, args);
        };
    }

    setupButtonInterception() {
        const self = this;
        
        document.addEventListener('click', (e) => {
            const button = e.target.closest('button');
            if (!button || button.disabled) return;

            // Do not show the loading indicator for UI-only buttons such as menu toggles
            if (button.classList.contains('menu-btn') || button.closest('.mobile-nav-panel')) {
                return;
            }

            // Only show indicator for buttons that submit a form.
            const form = button.closest('form');
            if (!form) return;
            if (button.type && button.type.toLowerCase() === 'button') return;
            if (button.type && button.type.toLowerCase() === 'reset') return;

            // Show indicator for form submission buttons only.
            self.show({ showSpinner: false });
            setTimeout(() => {
                self.hide();
            }, 200);
        }, true);
    }

    // Manual control for custom operations
    startOperation(label) {
        this.show();
        if (label) {
            console.debug(`[Performance] Started: ${label}`);
        }
    }

    endOperation(label) {
        this.hide();
        if (label) {
            console.debug(`[Performance] Ended: ${label}`);
        }
    }
}

// Initialize on DOM ready (not DOMContentLoaded to be even faster)
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
        window.perfIndicator = new PerformanceIndicator();
    });
} else {
    window.perfIndicator = new PerformanceIndicator();
}

// Export for manual use
window.PerformanceIndicator = PerformanceIndicator;
