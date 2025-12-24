import CONFIG from './config.js';

/**
 * API client for Server Manager
 */

const API_URL = '/api';

class API {
    /**
     * Get authentication token from session storage
     * @returns {string|null} Auth token or null if not authenticated
     */
    static getToken() {
        return sessionStorage.getItem('auth_token');
    }

    /**
     * Make authenticated API request
     * @param {string} endpoint - API endpoint
     * @param {Object} options - Fetch options
     * @returns {Promise<Object>} - API response
     */
    static async request(endpoint, options = {}) {
        const token = this.getToken();
        if (!token) {
            throw new Error('Not authenticated');
        }

        const url = `${API_URL}${endpoint}`;
        const headers = {
            'Authorization': `Bearer ${token}`,
            'Content-Type': 'application/json',
            ...options.headers
        };

        try {
            const response = await fetch(url, {
                ...options,
                headers
            });

            if (!response.ok) {
                if (response.status === 401) {
                    // Token expired or invalid
                    sessionStorage.clear();
                    window.location.replace('login.html');
                    throw new Error('Authentication expired');
                }

                let errorData;
                try {
                    const responseText = await response.text();
                    try {
                        errorData = JSON.parse(responseText);
                    } catch (jsonError) {
                        errorData = { error: 'Server returned invalid response format' };
                    }
                } catch (parseError) {
                    errorData = { error: 'Failed to read server response' };
                }
                throw new Error(errorData.error || 'API request failed');
            }

            return await response.json();
        } catch (error) {
            console.error(`API error (${endpoint}):`, error);
            throw error;
        }
    }

    /**
     * Get all servers
     * @returns {Promise<Array>} List of servers
     */
    static async getServers() {
        return this.request('/servers');
    }

    /**
     * Start a server
     * @param {string} serverId - Server ID
     * @returns {Promise<Object>} Operation result
     */
    static async startServer(serverId) {
        return this.request(`/servers/${serverId}/start`, {
            method: 'POST'
        });
    }

    /**
     * Stop a server
     * @param {string} serverId - Server ID
     * @param {boolean} force - Force stop
     * @returns {Promise<Object>} Operation result
     */
    static async stopServer(serverId, force = false) {
        return this.request(`/servers/${serverId}/stop`, {
            method: 'POST',
            body: JSON.stringify({ force })
        });
    }

    /**
     * Restart a server
     * @param {string} serverId - Server ID
     * @returns {Promise<Object>} Operation result
     */
    static async restartServer(serverId) {
        return this.request(`/servers/${serverId}/restart`, {
            method: 'POST'
        });
    }

    /**
     * Get all users (admin only)
     * @returns {Promise<Array>} List of users
     */
    static async getUsers() {
        return this.request('/users');
    }

    /**
     * Create a new user (admin only)
     * @param {Object} userData - User data
     * @returns {Promise<Object>} Operation result
     */
    static async createUser(userData) {
        return this.request('/users', {
            method: 'POST',
            body: JSON.stringify(userData)
        });
    }

    /**
     * Delete a user (admin only)
     * @param {string} username - Username to delete
     * @returns {Promise<Object>} Operation result
     */
    static async deleteUser(username) {
        return this.request(`/users/${username}`, {
            method: 'DELETE'
        });
    }

    /**
     * Reset user password (admin only)
     * @param {string} username - Username
     * @param {string} newPassword - New password
     * @returns {Promise<Object>} Operation result
     */
    static async resetUserPassword(username, newPassword) {
        return this.request(`/users/${username}/password`, {
            method: 'PUT',
            body: JSON.stringify({ password: newPassword })
        });
    }

    /**
     * Get system settings
     * @returns {Promise<Object>} System settings
     */
    static async getSystemSettings() {
        return this.request('/settings');
    }

    /**
     * Create a new server
     * @param {Object} serverData - Server data
     * @returns {Promise<Object>} Operation result
     */
    static async createServer(serverData) {
        return this.request('/servers', {
            method: 'POST',
            body: JSON.stringify(serverData)
        });
    }

    /**
     * Get console output for a server
     * @param {string} serverId - Server ID
     * @param {number} lines - Number of lines to fetch
     * @returns {Promise<Object>} Console output
     */
    static async getConsoleOutput(serverId, lines = 100) {
        return this.request(`/servers/${encodeURIComponent(serverId)}/console?lines=${lines}`);
    }

    /**
     * Send command to server console
     * @param {string} serverId - Server ID
     * @param {string} command - Command to send
     * @returns {Promise<Object>} Operation result
     */
    static async sendConsoleCommand(serverId, command) {
        return this.request(`/servers/${encodeURIComponent(serverId)}/console`, {
            method: 'POST',
            body: JSON.stringify({ command })
        });
    }

    // ==================== Profile Methods ====================

    /**
     * Get current user's profile
     * @returns {Promise<Object>} User profile data
     */
    static async getProfile() {
        return this.request('/profile');
    }

    /**
     * Update current user's profile
     * @param {Object} profileData - Profile fields to update
     * @returns {Promise<Object>} Operation result
     */
    static async updateProfile(profileData) {
        return this.request('/profile', {
            method: 'PUT',
            body: JSON.stringify(profileData)
        });
    }

    /**
     * Change current user's password
     * @param {string} currentPassword - Current password for verification
     * @param {string} newPassword - New password to set
     * @returns {Promise<Object>} Operation result
     */
    static async changePassword(currentPassword, newPassword) {
        return this.request('/profile/password', {
            method: 'PUT',
            body: JSON.stringify({
                current_password: currentPassword,
                new_password: newPassword
            })
        });
    }

    /**
     * Upload a new avatar
     * @param {string} avatarBase64 - Base64 encoded avatar image
     * @returns {Promise<Object>} Operation result
     */
    static async uploadAvatar(avatarBase64) {
        return this.request('/profile/avatar', {
            method: 'POST',
            body: JSON.stringify({ avatar: avatarBase64 })
        });
    }
}

export default API;
