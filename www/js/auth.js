/**
 * Authentication module for Server Manager
 */

const API_URL = '/api';

/**
 * Authenticate user and get token
 * @param {string} username - Username
 * @param {string} password - Password
 * @returns {Promise<Object>} - Authentication result
 */
export async function login(username, password) {
    try {
        const response = await fetch(`${API_URL}/auth/login`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ username, password })
        });

        if (!response.ok) {
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
            
            let errorMsg = errorData.error || 'Authentication failed';
            
            // Provide more specific error messages based on status code
            if (response.status === 401) {
                errorMsg = 'Invalid username or password. Try using "admin"/"admin" or your Windows credentials.';
            } else if (response.status === 500) {
                errorMsg = 'Server error. Please try again later or contact administrator.';
            } else if (response.status === 400) {
                errorMsg = 'Invalid request. Please check your input.';
            } else if (response.status === 403) {
                errorMsg = 'Access forbidden. You may not have permission to access this resource.';
            } else if (response.status === 404) {
                errorMsg = 'Authentication service not found. Please check server configuration.';
            } else if (response.status >= 500) {
                errorMsg = 'Server error. Please try again later.';
            }
            
            throw new Error(errorMsg);
        }

        const data = await response.json();
        
        // Store authentication data in session storage
        sessionStorage.setItem('auth_token', data.token);
        sessionStorage.setItem('username', data.username);
        sessionStorage.setItem('isAdmin', data.isAdmin ? 'true' : 'false');
        
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

        let data;
        try {
            const responseText = await response.text();
            try {
                data = JSON.parse(responseText);
            } catch (jsonError) {
                console.error('Server returned non-JSON response for auth verify:', responseText);
                return false;
            }
        } catch (parseError) {
            console.error('Failed to read auth verify response:', parseError);
            return false;
        }
        
        if (data.authenticated) {
            // Update session storage with latest user info
            sessionStorage.setItem('username', data.username);
            sessionStorage.setItem('isAdmin', data.isAdmin ? 'true' : 'false');
        }
        return data.authenticated === true;
    } catch (error) {
        console.error('Auth check error:', error);
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