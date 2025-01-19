import API from './api.js';

export async function checkAuth() {
    const token = sessionStorage.getItem('auth_token');
    console.log('CheckAuth - Token present:', !!token);
    
    if (!token) return false;

    try {
        const response = await fetch('/api/auth/verify', {
            method: 'GET',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            },
            credentials: 'include'  // Changed to include
        });

        console.log('CheckAuth - Response status:', response.status);
        
        if (!response.ok) {
            console.error('Auth check failed:', response.status);
            sessionStorage.clear();  // Clear invalid session
            return false;
        }

        const data = await response.json();
        console.log('CheckAuth - Response data:', data);  // Added logging
        return true;  // If we get here, the token is valid
    } catch (error) {
        console.error('Auth check error:', error);
        sessionStorage.clear();  // Clear on error
        return false;
    }
}

export async function login(username, password) {
    console.log('Login attempt for:', username);
    
    try {
        const response = await fetch('/api/auth', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            credentials: 'same-origin',
            body: JSON.stringify({
                username,
                password,
                authType: 'Local'
            })
        });

        const data = await response.json();
        console.log('Login response status:', response.status);

        if (!response.ok) throw new Error(data.message || 'Login failed');
        if (!data.token) throw new Error('No token received');

        // Clear any existing session first
        sessionStorage.clear();

        // Set new session data
        sessionStorage.setItem('auth_token', data.token);
        sessionStorage.setItem('username', data.username);
        sessionStorage.setItem('isAdmin', data.isAdmin ? 'true' : 'false');

        console.log('Login successful - Token stored');
        return data;
    } catch (error) {
        console.error('Login error:', error);
        sessionStorage.clear();
        throw error;
    }
}

export function logout() {
    console.log('Logging out...');
    sessionStorage.clear();
    
    // Clear browser history and prevent back navigation
    window.history.pushState(null, '', 'login.html');
    window.onpopstate = function () {
        window.history.pushState(null, '', 'login.html');
    };
    
    // Force reload of login page to clear any cached states
    window.location.replace('login.html');
}

export async function isAdmin() {
    return sessionStorage.getItem('isAdmin') === 'true';
}