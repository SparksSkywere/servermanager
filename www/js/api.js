import CONFIG from './config.js';

const API = {
    async getAuthMethods() {
        const response = await fetch('/api/auth/methods');
        if (!response.ok) throw new Error('Failed to get auth methods');
        return response;
    },

    async login(credentials) {
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
};

export default API;
