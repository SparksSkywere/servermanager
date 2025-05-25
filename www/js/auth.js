/**
 * Authentication module for Server Manager
 */

const API_URL = '/api';

/**
 * Authenticate user and get token
 * @param {string} username - Username
 * @param {string} password - Password
 * @param {string} authType - Authentication type ('Local' or 'Database')
 * @returns {Promise<Object>} - Authentication result
 */
export async function login(username, password, authType = 'Local') {
    try {
        const response = await fetch(`${API_URL}/auth/login`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ username, password, authType })
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error || 'Authentication failed');
        }

        const data = await response.json();
        
        // Store authentication data in session storage
        sessionStorage.setItem('auth_token', data.token);
        sessionStorage.setItem('username', data.username);
        sessionStorage.setItem('isAdmin', data.isAdmin);
        
        return data;
    } catch (error) {
        console.error('Login error:', error);
        throw error;
    }
}

/**
 * Check if user is authenticated
 * @returns {Promise<boolean>} - True if authenticated
 */
export async function checkAuth() {
    try {
        const token = sessionStorage.getItem('auth_token');
        if (!token) {
            return false;
        }

        const response = await fetch(`${API_URL}/auth/verify`, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });

        if (!response.ok) {
            return false;
        }

        const data = await response.json();
        return data.authenticated === true;
    } catch (error) {
        console.error('Auth check error:', error);
        return false;
    }
}

/**
 * Check if current user is an admin
 * @returns {Promise<boolean>} - True if user is admin
 */
export async function isAdmin() {
    try {
        // First check session storage
        const isAdminInSession = sessionStorage.getItem('isAdmin');
        if (isAdminInSession === 'true') {
            return true;
        }
        
        // If not in session or false, verify with server
        const token = sessionStorage.getItem('auth_token');
        if (!token) {
            return false;
        }

        const response = await fetch(`${API_URL}/verify-admin`, {
            headers: {
                'Authorization': `Bearer ${token}`
            }
        });

        if (!response.ok) {
            return false;
        }

        const data = await response.json();
        return data.isAdmin === true;
    } catch (error) {
        console.error('Admin check error:', error);
        return false;
    }
}

/**
 * Logout user
 */
export function logout() {
    // Clear session storage
    sessionStorage.clear();
    
    // Redirect to login page
    window.location.replace('login.html');
}