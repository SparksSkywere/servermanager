/**
 * Server control functions for Server Manager dashboard
 */

import API from './api.js';
import { showNotification } from './utils.js';

/**
 * Control a server (start, stop, restart)
 * @param {string} serverId - Server ID
 * @param {string} action - Action to perform (start, stop, restart)
 */
export async function controlServer(serverId, action) {
    try {
        let result;
        
        switch (action) {
            case 'start':
                result = await API.startServer(serverId);
                break;
            case 'stop':
                result = await API.stopServer(serverId);
                break;
            case 'restart':
                result = await API.restartServer(serverId);
                break;
            default:
                throw new Error(`Unknown action: ${action}`);
        }
        
        showNotification(result.message || `Server ${action} request successful`, 'success');
        
        // Refresh the page after a short delay
        setTimeout(() => window.location.reload(), 1500);
        
    } catch (error) {
        console.error(`Server control error (${action}):`, error);
        showNotification(`Failed to ${action} server: ${error.message}`, 'error');
    }
}

/**
 * Execute bulk action on selected servers
 */
export async function executeBulkAction() {
    const action = document.getElementById('bulkAction').value;
    if (!action) {
        showNotification('Please select an action', 'warning');
        return;
    }
    
    // Get all selected servers
    const selectedServers = [];
    document.querySelectorAll('.server-select:checked').forEach(checkbox => {
        const serverId = checkbox.closest('.server-item').dataset.serverId;
        if (serverId) {
            selectedServers.push(serverId);
        }
    });
    
    if (selectedServers.length === 0) {
        showNotification('No servers selected', 'warning');
        return;
    }
    
    try {
        // Confirm action
        if (!confirm(`Are you sure you want to ${action} ${selectedServers.length} servers?`)) {
            return;
        }
        
        // Show processing notification
        showNotification(`Processing ${action} for ${selectedServers.length} servers...`, 'info');
        
        // Execute action for each server
        const promises = selectedServers.map(serverId => controlServer(serverId, action));
        await Promise.all(promises);
        
        // Refresh the page after all actions complete
        setTimeout(() => window.location.reload(), 1500);
        
    } catch (error) {
        console.error(`Bulk action error (${action}):`, error);
        showNotification(`Failed to execute bulk action: ${error.message}`, 'error');
    }
}
