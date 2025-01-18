import CONFIG from './config.js';

class API {
    static getBaseUrl() {
        return CONFIG.API_BASE_URL;
    }

    static async handleResponse(response) {
        const contentType = response.headers.get('content-type');
        const isJson = contentType && contentType.includes('application/json');
        
        if (!response.ok) {
            console.error('API Error:', response.status, response.statusText);
            const error = isJson ? await response.json() : { message: response.statusText };
            throw new Error(error.message || 'API request failed');
        }
        
        return isJson ? response.json() : response;
    }

    static async getAuthMethods() {
        const response = await fetch('/api/auth/methods');
        if (!response.ok) throw new Error('Failed to get auth methods');
        return response;
    }

    static async login(credentials) {
        const response = await fetch('/api/auth', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(credentials)
        });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.error || 'Authentication failed');
        }
        
        return response;
    }

    static async verifyAdmin() {
        const response = await fetch(`${this.getBaseUrl()}/verify-admin`, {
            headers: {
                'Authorization': `Bearer ${sessionStorage.getItem('auth_token')}`,
                'Content-Type': 'application/json'
            }
        });
        return this.handleResponse(response);
    }

    static async getUsers() {
        const response = await fetch('/api/users', {
            headers: {
                'Authorization': `Bearer ${sessionStorage.getItem('auth_token')}`
            }
        });
        if (!response.ok) {
            throw new Error('Failed to fetch users');
        }
        return await response.json();
    }

    static async getSystemStats() {
        const response = await fetch('/api/stats', {
            headers: { 
                'Authorization': `Bearer ${sessionStorage.getItem('auth_token')}`,
                'Content-Type': 'application/json'
            }
        });
        return this.handleResponse(response);
    }

    static async getServers() {
        const response = await fetch('/api/servers', {
            headers: { 'Authorization': `Bearer ${sessionStorage.getItem('auth_token')}` }
        });
        if (!response.ok) throw new Error('Failed to fetch servers');
        return await response.json();
    }

    static async controlServer(action, serverName) {
        const response = await fetch(`/api/servers/${serverName}/${action}`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${sessionStorage.getItem('auth_token')}` }
        });
        if (!response.ok) throw new Error(`Failed to ${action} server`);
        return await response.json();
    }

    static async createServer(serverData) {
        const response = await fetch('/api/servers', {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${sessionStorage.getItem('auth_token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(serverData)
        });
        if (!response.ok) throw new Error('Failed to create server');
        return await response.json();
    }

    static async deleteServer(serverName) {
        const response = await fetch(`/api/servers/${serverName}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${sessionStorage.getItem('auth_token')}` }
        });
        if (!response.ok) throw new Error('Failed to delete server');
        return await response.json();
    }
}

export default API;
