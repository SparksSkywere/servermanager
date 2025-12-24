/**
 * Theme Manager for Server Manager
 * Handles dark/light theme switching with persistence
 */

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
        if (localTheme) return localTheme;
        
        // Default to dark theme
        return 'dark';
    }
    
    /**
     * Apply current theme to document
     */
    apply() {
        document.documentElement.setAttribute('data-theme', this.theme);
        document.body.classList.remove('theme-dark', 'theme-light');
        document.body.classList.add(`theme-${this.theme}`);
        
        // Save to localStorage for instant load on next page
        localStorage.setItem('theme_preference', this.theme);
    }
    
    /**
     * Toggle between dark and light themes
     */
    toggle() {
        this.theme = this.theme === 'dark' ? 'light' : 'dark';
        this.apply();
        return this.theme;
    }
    
    /**
     * Set specific theme
     * @param {string} theme - 'dark' or 'light'
     */
    set(theme) {
        if (theme === 'dark' || theme === 'light') {
            this.theme = theme;
            this.apply();
        }
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
        if (profileTheme && (profileTheme === 'dark' || profileTheme === 'light')) {
            this.theme = profileTheme;
            this.apply();
        }
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

ThemeManager.set = function(theme) {
    themeManager.set(theme);
};

ThemeManager.syncFromProfile = function(profileTheme) {
    themeManager.syncFromProfile(profileTheme);
};

ThemeManager.saveToProfile = async function() {
    return themeManager.saveToProfile();
};

// For non-module usage (most pages)
if (typeof window !== 'undefined') {
    window.ThemeManager = ThemeManager;
    window.themeManager = themeManager;
}
