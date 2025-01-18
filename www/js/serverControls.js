import API from './api.js';
import { showNotification } from './utils.js';

export async function controlServer(action, serverName) {
    try {
        await API.controlServer(action, serverName);
        showNotification(`Server ${serverName} ${action} command sent successfully`, 'success');
        // Trigger a refresh of the dashboard
        window.dispatchEvent(new CustomEvent('serverStateChanged'));
    } catch (error) {
        showNotification(`Failed to ${action} server: ${error.message}`, 'error');
    }
}

export async function executeBulkAction() {
    const action = document.getElementById('bulkAction').value;
    if (!action) {
        showNotification('Please select an action', 'warning');
        return;
    }

    const selectedServers = Array.from(document.querySelectorAll('input[name="serverSelect"]:checked'))
        .map(checkbox => checkbox.value);

    if (selectedServers.length === 0) {
        showNotification('Please select at least one server', 'warning');
        return;
    }

    try {
        await Promise.all(selectedServers.map(server => controlServer(action, server)));
        showNotification(`Bulk ${action} action completed`, 'success');
    } catch (error) {
        showNotification(`Bulk action failed: ${error.message}`, 'error');
    }
}
