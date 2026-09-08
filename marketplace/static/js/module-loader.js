/**
 * Module Loader - Lazy Loading pour Architecture Modulaire
 * Charge les modules à la demande avec cache, pagination et requêtes asynchrones
 */

class ModuleLoaderSystem {
    constructor() {
        this.loadedModules = new Map();
        this.loadingModules = new Set();
        this.moduleCache = new Map();
        this.stats = new Map();
        this.csrfToken = this.getCSRFToken();
        this.baseUrl = '/api/modules/';
        this.requestTimeouts = new Map();
        this.TIMEOUT_MS = 30000; // 30 secondes
    }

    /**
     * Extrait le token CSRF
     */
    getCSRFToken() {
        const name = 'csrftoken';
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }

    /**
     * Charge la liste des modules disponibles
     */
    async loadModuleList() {
        try {
            const response = await fetch(`${this.baseUrl}`, {
                method: 'GET',
                credentials: 'same-origin',
                headers: {
                    'X-CSRFToken': this.csrfToken,
                    'Accept': 'application/json',
                },
            });

            if (!response.ok) throw new Error('Erreur lors du chargement des modules');
            return await response.json();
        } catch (error) {
            console.error('Erreur loadModuleList:', error);
            return { modules: [], total: 0 };
        }
    }

    /**
     * Charge un module spécifique avec pagination et filtres
     */
    async loadModule(moduleName, page = 1, filters = {}) {
        // Vérifier si le module est déjà en cours de chargement
        if (this.loadingModules.has(moduleName)) {
            console.log(`Module ${moduleName} déjà en cours de chargement`);
            return new Promise((resolve) => {
                const checkInterval = setInterval(() => {
                    if (!this.loadingModules.has(moduleName)) {
                        clearInterval(checkInterval);
                        resolve(this.loadedModules.get(moduleName) || null);
                    }
                }, 100);
            });
        }

        // Vérifier le cache
        const cacheKey = `${moduleName}:page:${page}`;
        if (this.moduleCache.has(cacheKey)) {
            console.log(`Module ${moduleName} trouvé en cache`);
            return this.moduleCache.get(cacheKey);
        }

        this.loadingModules.add(moduleName);

        try {
            const url = new URL(`${this.baseUrl}${moduleName}/load/`, window.location.origin);
            url.searchParams.append('page', page);
            Object.keys(filters).forEach(key => {
                if (filters[key] !== null && filters[key] !== undefined) {
                    url.searchParams.append(key, filters[key]);
                }
            });

            const response = await fetch(url.toString(), {
                method: 'GET',
                credentials: 'same-origin',
                headers: {
                    'X-CSRFToken': this.csrfToken,
                    'Accept': 'application/json',
                },
            });

            if (!response.ok) throw new Error('Erreur lors du chargement du module');

            const data = await response.json();
            this.loadedModules.set(moduleName, data);
            this.moduleCache.set(cacheKey, data);

            return data;
        } catch (error) {
            console.error(`Erreur lors du chargement du module ${moduleName}:`, error);
            return null;
        } finally {
            this.loadingModules.delete(moduleName);
        }
    }

    /**
     * Charge les statistiques pré-calculées d'un module
     */
    async loadModuleStats(moduleName = null) {
        try {
            let url;
            if (moduleName) {
                url = `${this.baseUrl}${moduleName}/stats/`;
            } else {
                url = `${this.baseUrl}all/stats/`;
            }

            const response = await fetch(url, {
                method: 'GET',
                credentials: 'same-origin',
                headers: {
                    'X-CSRFToken': this.csrfToken,
                    'Accept': 'application/json',
                },
            });

            if (!response.ok) throw new Error('Erreur lors du chargement des stats');

            const data = await response.json();
            if (moduleName) {
                this.stats.set(moduleName, data.stats);
            }
            return data.stats;
        } catch (error) {
            console.error(`Erreur lors du chargement des stats:`, error);
            return null;
        }
    }

    /**
     * Invalide le cache d'un module (admin only)
     */
    async invalidateModuleCache(moduleName) {
        try {
            const response = await fetch(
                `${this.baseUrl}${moduleName}/cache/invalidate/`,
                {
                    method: 'POST',
                    credentials: 'same-origin',
                    headers: {
                        'X-CSRFToken': this.csrfToken,
                        'Accept': 'application/json',
                    },
                }
            );

            if (!response.ok) throw new Error('Erreur lors de l\'invalidation du cache');

            // Vider le cache local
            for (let [key] of this.moduleCache) {
                if (key.startsWith(moduleName)) {
                    this.moduleCache.delete(key);
                }
            }

            return await response.json();
        } catch (error) {
            console.error('Erreur invalidateModuleCache:', error);
            return null;
        }
    }

    /**
     * Prépare les boutons pour répondre instantanément
     */
    initializeButtons() {
        // Boutons de pagination
        document.addEventListener('click', (e) => {
            if (e.target.classList.contains('module-pagination-btn')) {
                e.preventDefault();
                const moduleName = e.target.dataset.module;
                const page = e.target.dataset.page;
                this.onModulePageChange(moduleName, page);
            }

            // Boutons d'action instantanée
            if (e.target.classList.contains('module-action-btn')) {
                e.preventDefault();
                const action = e.target.dataset.action;
                const moduleName = e.target.dataset.module;
                const itemId = e.target.dataset.itemId;

                this.handleInstantAction(action, moduleName, itemId, e.target);
            }

            // Filtres
            if (e.target.classList.contains('module-filter-btn')) {
                e.preventDefault();
                const moduleName = e.target.dataset.module;
                const filters = this.getActiveFilters(moduleName);
                this.onModulePageChange(moduleName, 1, filters);
            }
        });
    }

    /**
     * Gère les actions instantanées des boutons
     */
    async handleInstantAction(action, moduleName, itemId, button) {
        const originalHTML = button.innerHTML;
        button.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>En cours...';
        button.disabled = true;

        try {
            let response;
            switch (action) {
                case 'add-to-cart':
                    response = await fetch(`/cart/add/${itemId}/`, {
                        method: 'POST',
                        credentials: 'same-origin',
                        headers: {
                            'X-CSRFToken': this.csrfToken,
                            'Accept': 'application/json',
                        },
                    });
                    break;

                case 'add-favorite':
                    response = await fetch(`/api/favorites/add/`, {
                        method: 'POST',
                        credentials: 'same-origin',
                        headers: {
                            'X-CSRFToken': this.csrfToken,
                            'Content-Type': 'application/json',
                            'Accept': 'application/json',
                        },
                        body: JSON.stringify({
                            item_id: itemId,
                            module: moduleName,
                        }),
                    });
                    break;

                case 'quick-buy':
                    response = await fetch(`/product/${itemId}/buy/`, {
                        method: 'POST',
                        credentials: 'same-origin',
                        headers: {
                            'X-CSRFToken': this.csrfToken,
                            'Content-Type': 'application/json',
                            'Accept': 'application/json',
                        },
                        body: JSON.stringify({ quantity: 1 }),
                    });
                    break;

                default:
                    throw new Error('Action inconnue');
            }

            if (!response.ok) throw new Error('Erreur lors de l\'action');

            const data = await response.json();

            // Animation de succès
            button.innerHTML = '✓ Succès!';
            button.style.backgroundColor = '#10b981';

            setTimeout(() => {
                button.innerHTML = originalHTML;
                button.disabled = false;
                button.style.backgroundColor = '';
            }, 2000);

            return data;
        } catch (error) {
            console.error('Erreur handleInstantAction:', error);
            button.innerHTML = '✗ Erreur';
            button.style.backgroundColor = '#ef4444';

            setTimeout(() => {
                button.innerHTML = originalHTML;
                button.disabled = false;
                button.style.backgroundColor = '';
            }, 2000);
        }
    }

    /**
     * Gère le changement de page
     */
    async onModulePageChange(moduleName, page, filters = {}) {
        const moduleContainer = document.querySelector(`[data-module="${moduleName}"]`);
        if (!moduleContainer) return;

        // Montrer un indicateur de chargement
        moduleContainer.style.opacity = '0.5';

        const data = await this.loadModule(moduleName, page, filters);

        if (data) {
            this.renderModuleData(moduleContainer, data);
            moduleContainer.style.opacity = '1';

            // Smooth scroll vers le module
            moduleContainer.scrollIntoView({ behavior: 'smooth' });
        }
    }

    /**
     * Récupère les filtres actifs
     */
    getActiveFilters(moduleName) {
        const container = document.querySelector(`[data-module="${moduleName}"]`);
        if (!container) return {};

        const filters = {};
        const searchInput = container.querySelector('[data-filter="search"]');
        if (searchInput && searchInput.value) {
            filters.search = searchInput.value;
        }

        const categorySelect = container.querySelector('[data-filter="category"]');
        if (categorySelect && categorySelect.value) {
            filters.category = categorySelect.value;
        }

        return filters;
    }

    /**
     * Rend les données d'un module dans le DOM
     */
    renderModuleData(container, data) {
        const itemsContainer = container.querySelector('.module-items');
        if (!itemsContainer) return;

        // Nettoyer
        itemsContainer.innerHTML = '';

        if (!data.items || data.items.length === 0) {
            itemsContainer.innerHTML = '<p class="text-center text-muted">Aucun élément disponible</p>';
            return;
        }

        // Rendre les éléments
        data.items.forEach(item => {
            const itemHTML = this.createItemHTML(item, data.module);
            itemsContainer.innerHTML += itemHTML;
        });

        // Rendre la pagination
        if (data.pagination) {
            const paginationHTML = this.createPaginationHTML(data);
            const paginationContainer = container.querySelector('.module-pagination');
            if (paginationContainer) {
                paginationContainer.innerHTML = paginationHTML;
            }
        }

        // Mettre à jour les stats
        if (data.stats) {
            const statsContainer = container.querySelector('.module-stats');
            if (statsContainer) {
                statsContainer.innerHTML = this.createStatsHTML(data.stats);
            }
        }

        const cacheBadge = container.querySelector('.cache-badge');
        if (cacheBadge) {
            if (data.cached) {
                cacheBadge.style.display = 'inline-block';
                cacheBadge.textContent = '📦 Chargé depuis le cache';
            } else {
                cacheBadge.style.display = 'none';
            }
        }
    }

    /**
     * Crée le HTML pour un élément
     */
    createItemHTML(item, moduleName) {
        const baseHTML = `
            <div class="module-item" data-item-id="${item.id}">
                <div class="item-header">
                    <h6>${item.name || item.title || 'Élément'}</h6>
                </div>
                <div class="item-body">
                    ${item.image ? `<img src="${item.image}" alt="" class="item-image">` : ''}
                    ${item.price ? `<p class="item-price">${item.price} HTG</p>` : ''}
                    ${item.description ? `<p class="item-description">${item.description}</p>` : ''}
                </div>
                <div class="item-actions">
                    <button class="module-action-btn btn btn-sm btn-primary" 
                            data-action="add-to-cart" 
                            data-module="${moduleName}" 
                            data-item-id="${item.id}">
                        Ajouter au panier
                    </button>
                    <button class="module-action-btn btn btn-sm btn-outline-secondary" 
                            data-action="add-favorite" 
                            data-module="${moduleName}" 
                            data-item-id="${item.id}">
                        ♥ Favori
                    </button>
                </div>
            </div>
        `;
        return baseHTML;
    }

    /**
     * Crée le HTML pour la pagination
     */
    createPaginationHTML(data) {
        const { pagination, module } = data;
        let html = '<nav aria-label="Module pagination"><ul class="pagination">';

        if (pagination.has_previous) {
            html += `
                <li class="page-item">
                    <button class="page-link module-pagination-btn" 
                            data-module="${module}" 
                            data-page="${pagination.current_page - 1}">
                        Précédent
                    </button>
                </li>
            `;
        }

        // Pages numérotées
        const startPage = Math.max(1, pagination.current_page - 2);
        const endPage = Math.min(pagination.total_pages, pagination.current_page + 2);

        for (let i = startPage; i <= endPage; i++) {
            const active = i === pagination.current_page ? 'active' : '';
            html += `
                <li class="page-item ${active}">
                    <button class="page-link module-pagination-btn" 
                            data-module="${module}" 
                            data-page="${i}">
                        ${i}
                    </button>
                </li>
            `;
        }

        if (pagination.has_next) {
            html += `
                <li class="page-item">
                    <button class="page-link module-pagination-btn" 
                            data-module="${module}" 
                            data-page="${pagination.current_page + 1}">
                        Suivant
                    </button>
                </li>
            `;
        }

        html += '</ul></nav>';
        return html;
    }

    /**
     * Crée le HTML pour les statistiques
     */
    createStatsHTML(stats) {
        if (!stats || Object.keys(stats).length === 0) return '';

        let html = '<div class="module-stats-cards">';
        for (const [key, value] of Object.entries(stats)) {
            if (typeof value === 'object') continue; // Skip nested objects
            html += `
                <div class="stat-card">
                    <span class="stat-label">${this.formatLabel(key)}:</span>
                    <span class="stat-value">${this.formatValue(value)}</span>
                </div>
            `;
        }
        html += '</div>';
        return html;
    }

    /**
     * Formate un label
     */
    formatLabel(label) {
        return label
            .replace(/_/g, ' ')
            .replace(/\b\w/g, l => l.toUpperCase());
    }

    /**
     * Formate une valeur
     */
    formatValue(value) {
        if (typeof value === 'number') {
            return value.toLocaleString('fr-FR', {
                minimumFractionDigits: 2,
                maximumFractionDigits: 2,
            });
        }
        return value;
    }

    /**
     * Initialise les modules au chargement de la page
     */
    async initializeModules() {
        const modules = await this.loadModuleList();
        console.log(`${modules.total} modules trouvés:`, modules.modules);

        // Initialiser les écouteurs de boutons
        this.initializeButtons();

        // Charger les modules visibles
        modules.modules.forEach(module => {
            const container = document.querySelector(`[data-module="${module.id}"]`);
            if (container && this.isElementInViewport(container)) {
                this.loadModule(module.id, 1);
                this.loadModuleStats(module.id);
            }
        });
    }

    /**
     * Vérifie si un élément est visible
     */
    isElementInViewport(el) {
        const rect = el.getBoundingClientRect();
        return (
            rect.top < window.innerHeight &&
            rect.bottom > 0 &&
            rect.left < window.innerWidth &&
            rect.right > 0
        );
    }

    /**
     * Initialise l'intersection observer pour le lazy loading des modules
     */
    initializeIntersectionObserver(modules) {
        if (!('IntersectionObserver' in window)) {
            console.warn('IntersectionObserver non supporté');
            return;
        }

        const observer = new IntersectionObserver((entries) => {
            entries.forEach(entry => {
                if (entry.isIntersecting) {
                    const moduleName = entry.target.dataset.module;
                    if (moduleName && !this.loadedModules.has(moduleName)) {
                        this.loadModule(moduleName, 1);
                        this.loadModuleStats(moduleName);
                        observer.unobserve(entry.target);
                    }
                }
            });
        }, { threshold: 0.1 });

        modules.modules.forEach(module => {
            const container = document.querySelector(`[data-module="${module.id}"]`);
            if (container) {
                observer.observe(container);
            }
        });
    }
}

// Initialiser le système au chargement du DOM
document.addEventListener('DOMContentLoaded', async () => {
    window.moduleLoader = new ModuleLoaderSystem();
    await window.moduleLoader.initializeModules();

    // Initialiser intersection observer pour un lazy loading avancé
    const modules = await window.moduleLoader.loadModuleList();
    window.moduleLoader.initializeIntersectionObserver(modules);
});
