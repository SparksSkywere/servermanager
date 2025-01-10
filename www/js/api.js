import CONFIG from './config.js';

class ApiService {
    static async fetchWithAuth(endpoint, options = {}) {
        const token = sessionStorage.getItem('auth_token');
        const defaultOptions = {
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`
            },
        };

        try {
            const response = await fetch(`${CONFIG.API_BASE_URL}${endpoint}`, {
                ...defaultOptions,
                ...options,
                headers: { ...defaultOptions.headers, ...options.headers }
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.message || 'Network response was not ok');
            }

            return response;
        } catch (error) {
            if (error.message === 'Failed to fetch') {
                throw new Error('Unable to connect to the server. Please check if the server is running.');
            }
            throw error;
        }
    }

    static async login(credentials) {
        return this.fetchWithAuth('/auth', {
            method: 'POST',
            body: JSON.stringify(credentials)
        });
    }

    static async getAuthMethods() {
        return this.fetchWithAuth('/auth/methods');
    }

    static async getServers() {
        return this.fetchWithAuth('/servers').then(res => res.json());
    }

    // Add other API methods as needed
}

window.API = ApiService;
export default ApiService;
