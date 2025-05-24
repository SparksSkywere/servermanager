import API from './api.js';
import { showNotification } from './utils.js';

export async function controlServer(serverId, action) {
    try {
        const response = await fetch('/api/server/control', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${sessionStorage.getItem('auth_token')}`
            },
            body: JSON.stringify({ serverId, action })
        });

        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.message || 'Server control action failed');
        }

        const result = await response.json();
        showNotification(`Server ${action} command sent successfully`, 'success');
        
        // Trigger dashboard update
        window.dashboard?.refreshData();
        
        return result;
    } catch (error) {
        console.error('Server control error:', error);
        showNotification(`Failed to ${action} server: ${error.message}`, 'error');
        throw error;
    }
}

export async function executeBulkAction() {
    const bulkAction = document.getElementById('bulkAction').value;
    if (!bulkAction) {
        showNotification('Please select an action to perform', 'warning');
        return;
    }

    const selectedServers = Array.from(document.querySelectorAll('.server-select:checked'))
        .map(checkbox => checkbox.closest('.server-item'))
        .map(item => ({
            id: item.dataset.serverId,
            name: item.querySelector('.server-name').textContent
        }));

    if (selectedServers.length === 0) {
        showNotification('Please select at least one server', 'warning');
        return;
    }

    try {
        const results = await Promise.all(selectedServers.map(server => 
            controlServer(server.id, bulkAction)
        ));

        const successCount = results.filter(r => r.success).length;
        showNotification(
            `Bulk ${bulkAction} completed: ${successCount}/${selectedServers.length} successful`,
            successCount === selectedServers.length ? 'success' : 'warning'
        );
    } catch (error) {
        console.error('Bulk action error:', error);
        showNotification(`Bulk action failed: ${error.message}`, 'error');
    }
}

function showNotification(message, type = 'info') {
    const notification = document.getElementById('notification');
    notification.textContent = message;
    notification.className = `notification ${type}`;
    notification.style.display = 'block';

    setTimeout(() => {
        notification.style.display = 'none';
    }, 5000);
}
