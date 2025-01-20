import CONFIG from './config.js';

class API {
    constructor() {
        this.baseUrl = '/api';
        this.webSocket = null;
        this.reconnectAttempts = 0;
        this.maxReconnectAttempts = 5;
    }

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

    async request(endpoint, options = {}) {
        const defaultOptions = {
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${sessionStorage.getItem('auth_token')}`
            }
        };

        try {
            const response = await fetch(
                `${this.baseUrl}${endpoint}`,
                { ...defaultOptions, ...options }
            );

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.message || 'API request failed');
            }

            return await response.json();
        } catch (error) {
            console.error('API request error:', error);
            throw error;
        }
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

    async verifyAdmin() {
        return this.request('/admin/verify');
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

    async getServers() {
        return this.request('/servers');
    }

    async controlServer(serverId, action) {
        return this.request('/server/control', {
            method: 'POST',
            body: JSON.stringify({ serverId, action })
        });
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

    connectWebSocket() {
        if (this.webSocket?.readyState === WebSocket.OPEN) return;

        this.webSocket = new WebSocket(`ws://${window.location.host}/ws`);

        this.webSocket.onopen = () => {
            console.log('WebSocket connected');
            this.reconnectAttempts = 0;
        };

        this.webSocket.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                this.handleWebSocketMessage(data);
            } catch (error) {
                console.error('WebSocket message error:', error);
            }
        };

        this.webSocket.onclose = () => {
            console.log('WebSocket disconnected');
            if (this.reconnectAttempts < this.maxReconnectAttempts) {
                this.reconnectAttempts++;
                setTimeout(() => this.connectWebSocket(), 5000);
            }
        };

        this.webSocket.onerror = (error) => {
            console.error('WebSocket error:', error);
        };
    }

    handleWebSocketMessage(data) {
        switch (data.type) {
            case 'metrics':
                window.dashboard?.updateDashboardMetrics(data);
                break;
            case 'serverUpdate':
                window.dashboard?.updateServerList();
                break;
            case 'log':
                window.dashboard?.addActivityLogEntry(data.message);
                break;
            default:
                console.log('Unknown WebSocket message type:', data.type);
        }
    }

    async getMetrics() {
        return this.request('/metrics');
    }
}

export default new API();
