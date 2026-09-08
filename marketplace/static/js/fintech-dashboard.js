/**
 * FINTECH DASHBOARD - Animations & Interactions
 * Premium Modern UI Effects
 */

function onDocumentReady(callback) {
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', callback);
    } else {
        callback();
    }
}

onDocumentReady(function() {
    initializeAnimations();
    initializeInteractions();
    initializeScrollEffects();
    initializeTooltips();
});

/**
 * Initialize Smooth Animations on Page Load
 */
function initializeAnimations() {
    // Observe elements for fade-in animation
    const observerOptions = {
        threshold: 0.1,
        rootMargin: '0px 0px -50px 0px'
    };
    
    const observer = new IntersectionObserver(function(entries) {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                entry.target.style.opacity = '1';
                entry.target.style.transform = 'translateY(0)';
                observer.unobserve(entry.target);
            }
        });
    }, observerOptions);
    
    // Observe all cards
    document.querySelectorAll('.fintech-card, .feature-card, .balance-card, .transaction-item').forEach(el => {
        el.style.opacity = '0';
        el.style.transform = 'translateY(20px)';
        el.style.transition = 'opacity 0.6s ease, transform 0.6s ease';
        observer.observe(el);
    });
    
    // Stagger animation for grid items
    const gridItems = document.querySelectorAll('.content-grid > *, .features-grid > *, .how-it-works > *');
    gridItems.forEach((item, index) => {
        item.style.animationDelay = `${index * 0.1}s`;
    });
}

/**
 * Initialize Interactive Elements
 */
function initializeInteractions() {
    // Button hover effects
    document.querySelectorAll('.btn-fintech').forEach(btn => {
        btn.addEventListener('mouseenter', function() {
            this.style.transform = 'translateY(-2px) scale(1.02)';
            this.style.boxShadow = '0 12px 30px rgba(0, 102, 255, 0.3)';
        });
        
        btn.addEventListener('mouseleave', function() {
            this.style.transform = 'translateY(0) scale(1)';
            this.style.boxShadow = '0 4px 15px rgba(0, 102, 255, 0.2)';
        });
    });
    
    // Card hover effects
    document.querySelectorAll('.fintech-card, .balance-card').forEach(card => {
        card.addEventListener('mouseenter', function() {
            this.style.transform = 'translateY(-4px) scale(1.01)';
            this.style.boxShadow = '0 20px 60px rgba(0, 102, 255, 0.15)';
        });
        
        card.addEventListener('mouseleave', function() {
            this.style.transform = 'translateY(0) scale(1)';
            this.style.boxShadow = '0 10px 30px rgba(15, 23, 42, 0.08)';
        });
    });
    
    // Form input focus effects
    document.querySelectorAll('.form-input, .form-select').forEach(input => {
        input.addEventListener('focus', function() {
            this.parentElement.style.transform = 'scale(1.01)';
            this.style.boxShadow = '0 0 0 3px rgba(0, 102, 255, 0.1)';
        });
        
        input.addEventListener('blur', function() {
            this.parentElement.style.transform = 'scale(1)';
            this.style.boxShadow = 'none';
        });
    });
}

/**
 * Initialize Scroll Effects
 */
function initializeScrollEffects() {
    let lastScrollTop = 0;
    const header = document.querySelector('.dashboard-header');
    
    if (!header) return;
    
    window.addEventListener('scroll', function() {
        let scrollTop = window.pageYOffset || document.documentElement.scrollTop;
        
        // Parallax effect for header
        if (scrollTop < 500) {
            const offset = scrollTop * 0.5;
            header.style.backgroundPosition = `0 ${offset}px`;
        }
        
        lastScrollTop = scrollTop;
    });
}

/**
 * Initialize Tooltips
 */
function initializeTooltips() {
    document.querySelectorAll('[data-tooltip]').forEach(element => {
        element.addEventListener('mouseenter', function() {
            const tooltip = document.createElement('div');
            tooltip.textContent = this.getAttribute('data-tooltip');
            tooltip.style.cssText = `
                position: absolute;
                background: rgba(15, 23, 42, 0.9);
                color: white;
                padding: 8px 12px;
                border-radius: 6px;
                font-size: 0.85rem;
                pointer-events: none;
                z-index: 1000;
                animation: tooltipFade 0.2s ease;
            `;
            
            document.body.appendChild(tooltip);
            const rect = this.getBoundingClientRect();
            tooltip.style.left = (rect.left + rect.width / 2 - tooltip.offsetWidth / 2) + 'px';
            tooltip.style.top = (rect.top - tooltip.offsetHeight - 8) + 'px';
            
            this._tooltip = tooltip;
        });
        
        element.addEventListener('mouseleave', function() {
            if (this._tooltip) {
                this._tooltip.remove();
                this._tooltip = null;
            }
        });
    });
}

/**
 * Number Counter Animation
 */
function animateCounter(element, target, duration = 1000) {
    const start = parseInt(element.textContent);
    const increment = (target - start) / (duration / 50);
    let current = start;
    
    const counter = setInterval(() => {
        current += increment;
        if ((increment > 0 && current >= target) || (increment < 0 && current <= target)) {
            element.textContent = target.toLocaleString();
            clearInterval(counter);
        } else {
            element.textContent = Math.floor(current).toLocaleString();
        }
    }, 50);
}

/**
 * Initialize Balance Cards with Animation
 */
function initializeBalanceCards() {
    const balanceAmounts = document.querySelectorAll('.balance-amount');
    balanceAmounts.forEach(element => {
        const originalValue = element.textContent;
        element.addEventListener('mouseenter', function() {
            // Add glow effect
            this.style.textShadow = '0 0 20px rgba(0, 212, 255, 0.5)';
            this.style.color = '#00d4ff';
        });
        
        element.addEventListener('mouseleave', function() {
            this.style.textShadow = 'none';
            this.style.color = 'var(--primary-blue)';
        });
    });
}

/**
 * Modal Management
 */
class FinanceModal {
    constructor(modalId) {
        this.modal = document.getElementById(modalId);
        if (!this.modal) return;
        
        this.setupEventListeners();
    }
    
    setupEventListeners() {
        // Close on outside click
        this.modal.addEventListener('click', (e) => {
            if (e.target === this.modal) {
                this.close();
            }
        });
        
        // Close on Escape key
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.modal.style.display !== 'none') {
                this.close();
            }
        });
    }
    
    open() {
        this.modal.style.display = 'flex';
        this.modal.style.animation = 'fadeIn 0.3s ease';
    }
    
    close() {
        this.modal.style.animation = 'fadeOut 0.3s ease';
        setTimeout(() => {
            this.modal.style.display = 'none';
        }, 300);
    }
}

/**
 * Notification System
 */
class Notification {
    static create(message, type = 'info', duration = 4000) {
        const notification = document.createElement('div');
        notification.className = `notification notification-${type}`;
        notification.innerHTML = `
            <span class="notification-icon">
                ${type === 'success' ? '✓' : type === 'danger' ? '✗' : type === 'warning' ? '⚠️' : 'ℹ️'}
            </span>
            <div>${message}</div>
        `;
        
        notification.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            z-index: 9999;
            animation: slideIn 0.3s ease;
            max-width: 400px;
        `;
        
        document.body.appendChild(notification);
        
        setTimeout(() => {
            notification.style.animation = 'slideOut 0.3s ease';
            setTimeout(() => notification.remove(), 300);
        }, duration);
    }
}

/**
 * Currency Converter
 */
class CurrencyConverter {
    constructor() {
        this.rates = {
            'USD': 1,
            'HTG': 62.50,
            'EUR': 0.92,
            'DOP': 57.30
        };
    }
    
    convert(amount, from, to) {
        const amountInUSD = amount / this.rates[from];
        return amountInUSD * this.rates[to];
    }
    
    getRate(from, to) {
        return this.rates[to] / this.rates[from];
    }
}

/**
 * Transaction Filter
 */
class TransactionFilter {
    constructor() {
        this.transactions = [];
        this.initializeFilters();
    }
    
    initializeFilters() {
        const filterButtons = document.querySelectorAll('[data-filter]');
        filterButtons.forEach(btn => {
            btn.addEventListener('click', () => {
                this.applyFilter(btn.getAttribute('data-filter'));
            });
        });
    }
    
    applyFilter(type) {
        const filtered = this.transactions.filter(t => t.type === type);
        this.updateDisplay(filtered);
    }
    
    updateDisplay(transactions) {
        const container = document.querySelector('[data-transaction-container]');
        if (!container) return;
        
        container.innerHTML = transactions.map(t => `
            <div class="transaction-row">
                <div>${t.description}</div>
                <div>${t.amount}</div>
                <div>${t.status}</div>
            </div>
        `).join('');
    }
}

/**
 * Chart Utilities
 */
class ChartUtilities {
    static formatChartData(data) {
        return {
            labels: data.map(d => d.label),
            datasets: [{
                label: 'Amount (USD)',
                data: data.map(d => d.value),
                borderColor: '#0066ff',
                backgroundColor: 'rgba(0, 102, 255, 0.1)',
                borderWidth: 3,
                fill: true,
                tension: 0.4
            }]
        };
    }
    
    static getChartOptions() {
        return {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    display: true,
                    position: 'top',
                    labels: {
                        usePointStyle: true,
                        padding: 15,
                        font: { size: 12, weight: '600' }
                    }
                }
            },
            scales: {
                y: {
                    beginAtZero: true,
                    grid: {
                        color: 'rgba(148, 163, 184, 0.1)'
                    }
                },
                x: {
                    grid: {
                        display: false
                    }
                }
            }
        };
    }
}

/**
 * Export for use in other scripts
 */
window.FinanceApp = {
    Notification,
    CurrencyConverter,
    TransactionFilter,
    ChartUtilities,
    FinanceModal,
    animateCounter,
    initializeBalanceCards
};
