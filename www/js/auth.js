export async function checkAuth() {
    const token = sessionStorage.getItem('auth_token');
    if (!token) {
        throw new Error('No authentication token');
    }

    const response = await fetch('/api/verify-token', {
        headers: {
            'Authorization': `Bearer ${token}`
        }
    });

    if (!response.ok) {
        throw new Error('Invalid token');
    }

    // Add this to refresh admin status on each auth check
    const data = await response.json();
    if (data.isAdmin !== undefined) {
        sessionStorage.setItem('isAdmin', data.isAdmin);
    }

    return true;
}

export async function isAdmin() {
    // Add console log for debugging
    const adminStatus = sessionStorage.getItem('isAdmin');
    console.log('Admin status:', adminStatus);
    return adminStatus === 'true';
}

export function logout() {
    sessionStorage.clear();
    window.location.replace('login.html');
}