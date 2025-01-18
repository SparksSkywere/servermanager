import API from './api.js';

export async function checkAuth() {
    const token = sessionStorage.getItem('auth_token');
    console.log('Checking auth with token:', token ? 'Present' : 'Missing');

    if (!token) {
        console.log('No token found, authentication failed');
        return false;
    }

    try {
        const response = await fetch(`${API.getBaseUrl()}/verify-token`, {
            method: 'GET',
            headers: {
                'Authorization': `Bearer ${token}`,
                'Content-Type': 'application/json'
            }
        });

        console.log('Token verification response status:', response.status);
        const data = await response.json();
        console.log('Token verification response:', data);

        if (response.ok && data.valid) {
            // Update admin status if included in response
            if (data.isAdmin !== undefined) {
                sessionStorage.setItem('isAdmin', data.isAdmin.toString());
                console.log('Updated admin status:', data.isAdmin);
            }
            return true;
        }
        return false;
    } catch (error) {
        console.error('Auth check failed:', error);
        return false;
    }
}

export async function isAdmin() {
    const token = sessionStorage.getItem('auth_token');
    console.log('Checking admin status with token:', token ? 'Present' : 'Missing');

    try {
        const response = await fetch('/api/verify-admin', {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });

        const data = await response.json();
        console.log('Admin verification response:', data);
        
        const isAdminUser = response.ok && data.isAdmin;
        sessionStorage.setItem('isAdmin', isAdminUser ? 'true' : 'false');
        console.log('Admin status set to:', isAdminUser);
        
        return isAdminUser;
    } catch (error) {
        console.error('Admin verification error:', error);
        sessionStorage.setItem('isAdmin', 'false');
        return false;
    }
}

export function logout() {
    sessionStorage.clear();
    window.location.replace('login.html');
}