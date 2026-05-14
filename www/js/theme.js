/**
 * Theme Manager for Server Manager
 * Handles multi-theme switching with persistence.
 */

const AVAILABLE_THEMES = [
    'dark',
    'light',
    'blue',
    'green',
    'classic',
    'slate',
    'midnight',
    'amber',
    'steel_blue',
    'forest',
    'sand',
    'high_contrast'
];

const LIGHT_FAMILY_THEMES = new Set([
    'light',
    'blue',
    'green',
    'classic',
    'slate',
    'steel_blue',
    'sand'
]);

const THEME_DISPLAY_NAMES = {
    dark: 'Dark',
    light: 'Light',
    blue: 'Blue',
    green: 'Green',
    classic: 'Classic',
    slate: 'Slate',
    midnight: 'Midnight',
    amber: 'Amber',
    steel_blue: 'Steel Blue',
    forest: 'Forest',
    sand: 'Sand',
    high_contrast: 'High Contrast'
};

const MOON_ICON_PATHS = [
    { tag: 'path', d: 'M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z' }
];
const SUN_ICON_PATHS = [
    { tag: 'circle', cx: '12', cy: '12', r: '5' },
    { tag: 'line', x1: '12', y1: '1', x2: '12', y2: '3' },
    { tag: 'line', x1: '12', y1: '21', x2: '12', y2: '23' },
    { tag: 'line', x1: '4.22', y1: '4.22', x2: '5.64', y2: '5.64' },
    { tag: 'line', x1: '18.36', y1: '18.36', x2: '19.78', y2: '19.78' },
    { tag: 'line', x1: '1', y1: '12', x2: '3', y2: '12' },
    { tag: 'line', x1: '21', y1: '12', x2: '23', y2: '12' },
    { tag: 'line', x1: '4.22', y1: '19.78', x2: '5.64', y2: '18.36' },
    { tag: 'line', x1: '18.36', y1: '5.64', x2: '19.78', y2: '4.22' }
];

class ThemeManager {
    constructor() {
        this.theme = this.getSavedTheme() || 'dark';
        this.apply();
    }
    
    /**
     * Get saved theme from localStorage or user profile
     */
    getSavedTheme() {
        // Check localStorage first (instant load)
        const localTheme = localStorage.getItem('theme_preference');
        if (localTheme) return this.normaliseTheme(localTheme);
        
        // Default to dark theme
        return 'dark';
    }

    normaliseTheme(theme) {
        const value = String(theme || '').trim().toLowerCase();
        return AVAILABLE_THEMES.includes(value) ? value : 'dark';
    }

    isLightFamily(theme = this.theme) {
        return LIGHT_FAMILY_THEMES.has(this.normaliseTheme(theme));
    }

    getDisplayName(theme = this.theme) {
        const normalised = this.normaliseTheme(theme);
        return THEME_DISPLAY_NAMES[normalised] || 'Dark';
    }
    
    /**
     * Apply current theme to document
     */
    apply() {
        this.theme = this.normaliseTheme(this.theme);
        document.documentElement.setAttribute('data-theme', this.theme);

        if (document.body) {
            document.body.classList.remove('theme-dark', 'theme-light', ...AVAILABLE_THEMES.map((theme) => `theme-${theme}`));
            document.body.classList.add(`theme-${this.theme}`);
            document.body.classList.add(this.isLightFamily() ? 'theme-light' : 'theme-dark');
        }
        
        // Save to localStorage for instant load on next page
        localStorage.setItem('theme_preference', this.theme);
        this.updateThemeUI();
        this.syncThemeSelects();
    }

    updateThemeUI() {
        const icon = document.getElementById('themeIcon');
        const text = document.getElementById('themeText');

        if (icon) {
            const paths = this.isLightFamily() ? SUN_ICON_PATHS : MOON_ICON_PATHS;
            const ns = 'http' + '://www.w3.org/2000/svg';
            const elements = [];
            
            paths.forEach((pathData) => {
                const el = document.createElementNS(ns, pathData.tag);
                Object.entries(pathData).forEach(([key, value]) => {
                    if (key !== 'tag') {
                        el.setAttribute(key, String(value));
                    }
                });
                elements.push(el);
            });
            
            icon.replaceChildren(...elements);
        }

        if (text) {
            text.textContent = `Theme: ${this.getDisplayName()}`;
        }
    }
    
    /**
     * Cycle through available themes.
     */
    toggle() {
        const currentIndex = AVAILABLE_THEMES.indexOf(this.theme);
        const nextIndex = currentIndex >= 0 ? (currentIndex + 1) % AVAILABLE_THEMES.length : 0;
        this.theme = AVAILABLE_THEMES[nextIndex];
        this.apply();
        return this.theme;
    }
    
    /**
     * Set specific theme.
     * @param {string} theme - Theme name.
     */
    set(theme) {
        this.theme = this.normaliseTheme(theme);
        this.apply();
        return this.theme;
    }
    
    /**
     * Get current theme
     * @returns {string} Current theme name
     */
    get() {
        return this.theme;
    }
    
    /**
     * Sync theme from user profile (call after loading profile)
     * @param {string} profileTheme - Theme from user profile
     */
    syncFromProfile(profileTheme) {
        if (profileTheme) {
            this.set(profileTheme);
        }
    }

    populateThemeSelect(select) {
        if (!select) {
            return;
        }

        const currentValue = this.normaliseTheme(select.value || this.theme);
        select.textContent = '';

        AVAILABLE_THEMES.forEach((theme) => {
            const option = document.createElement('option');
            option.value = theme;
            option.textContent = this.getDisplayName(theme);
            select.appendChild(option);
        });

        select.value = currentValue;
    }

    populateThemeSelects(root = document) {
        root.querySelectorAll('[data-theme-select], #profileTheme').forEach((select) => {
            this.populateThemeSelect(select);
        });
    }

    syncThemeSelects(root = document) {
        root.querySelectorAll('[data-theme-select], #profileTheme').forEach((select) => {
            if (select.querySelector(`option[value="${this.theme}"]`)) {
                select.value = this.theme;
            }
        });
    }
    
    /**
     * Save theme preference to user profile on the server
     * Call this after toggle() when user is logged in
     */
    async saveToProfile() {
        try {
            const token = sessionStorage.getItem('auth_token');
            if (!token) return;
            
            const response = await fetch('/api/profile', {
                method: 'PUT',
                headers: {
                    'Content-Type': 'application/json',
                    'Authorization': `Bearer ${token}`
                },
                body: JSON.stringify({
                    theme_preference: this.theme
                })
            });
            
            if (!response.ok) {
                console.warn('Failed to save theme preference to profile');
            }
        } catch (error) {
            console.warn('Error saving theme preference:', error);
        }
    }
    
    /**
     * Toggle theme and save to profile
     * Use this on authenticated pages
     */
    async toggleAndSave() {
        this.toggle();
        await this.saveToProfile();
        return this.theme;
    }

    async setAndSave(theme) {
        this.set(theme);
        await this.saveToProfile();
        return this.theme;
    }
}

// Create global instance
const themeManager = new ThemeManager();

// Static methods for easy access
ThemeManager.toggle = function() {
    return themeManager.toggle();
};

ThemeManager.toggleAndSave = async function() {
    return themeManager.toggleAndSave();
};

ThemeManager.get = function() {
    return themeManager.get();
};

ThemeManager.getDisplayName = function(theme) {
    return themeManager.getDisplayName(theme);
};

ThemeManager.getAvailableThemes = function() {
    return [...AVAILABLE_THEMES];
};

ThemeManager.isLightFamily = function(theme) {
    return themeManager.isLightFamily(theme);
};

ThemeManager.set = function(theme) {
    return themeManager.set(theme);
};

ThemeManager.syncFromProfile = function(profileTheme) {
    themeManager.syncFromProfile(profileTheme);
};

ThemeManager.updateThemeUI = function() {
    themeManager.updateThemeUI();
};

ThemeManager.populateThemeSelect = function(select) {
    themeManager.populateThemeSelect(select);
};

ThemeManager.populateThemeSelects = function(root = document) {
    themeManager.populateThemeSelects(root);
};

ThemeManager.saveToProfile = async function() {
    return themeManager.saveToProfile();
};

ThemeManager.setAndSave = async function(theme) {
    return themeManager.setAndSave(theme);
};

ThemeManager.applyCurrentTheme = function() {
    themeManager.apply();
    return themeManager.get();
};

// For non-module usage (most pages)
if (typeof window !== 'undefined') {
    window.ThemeManager = ThemeManager;
    window.themeManager = themeManager;
    window.applyTheme = function(theme) {
        return themeManager.set(theme);
    };
    window.updateThemeUI = function() {
        themeManager.updateThemeUI();
    };
    window.toggleTheme = async function() {
        return themeManager.toggleAndSave();
    };
    window.selectTheme = async function(theme) {
        return themeManager.setAndSave(theme);
    };
    window.previewTheme = function(theme) {
        return themeManager.set(theme);
    };
}
