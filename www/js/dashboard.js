/**
 * Dashboard management for Server Manager
 */

import API from './api.js';
import { showNotification, getRandomColor } from './utils.js';

export class Dashboard {
    constructor() {
        this.servers = [];
        this.charts = {};
        this.refreshInterval = null;
        this.refreshRate = 10; // Default refresh rate in seconds
        
        // Initialise dashboard
        this.initializeGridStack();
        this.setupEventListeners();
        this.refreshData();
        
        // Start automatic refresh
        this.startAutoRefresh();
    }
    
    initializeGridStack() {
        // Initialise GridStack for draggable panels
        this.grid = GridStack.init({
            cellHeight: 80,
            minRow: 1,
            margin: 10,
            disableOneColumnMode: true,
            float: false,
            handleClass: 'panel-header',
            draggable: {
                handle: '.panel-header'
            }
        });
        
        // Disable dragging initially
        this.grid.enableMove(false);
    }
    
    setupEventListeners() {
        // Set up event listeners for dashboard controls
        const refreshRateSelect = document.getElementById('refreshRate');
        if (refreshRateSelect) {
            refreshRateSelect.addEventListener('change', () => {
                this.refreshRate = parseInt(refreshRateSelect.value);
                this.startAutoRefresh();
            });
        }
        
        // Server search
        const serverSearch = document.getElementById('serverSearch');
        if (serverSearch) {
            serverSearch.addEventListener('input', () => this.filterServers());
        }
        
        // Status filter
        const statusFilter = document.getElementById('statusFilter');
        if (statusFilter) {
            statusFilter.addEventListener('change', () => this.filterServers());
        }
        
        // Edit dashboard button
        const editDashboardBtn = document.querySelector('.edit-dashboard-btn');
        if (editDashboardBtn) {
            editDashboardBtn.addEventListener('click', () => this.toggleEditMode());
        }
    }
    
    async refreshData() {
        try {
            // Fetch servers
            this.servers = await API.getServers();
            
            // Update dashboard components
            this.updateServerList();
            this.updateSystemOverview();
            this.updateCharts();
            this.updateActivityLog();
            
        } catch (error) {
            console.error('Dashboard refresh error:', error);
            showNotification('Failed to refresh dashboard data', 'error');
        }
    }
    
    startAutoRefresh() {
        // Clear existing interval
        if (this.refreshInterval) {
            clearInterval(this.refreshInterval);
        }
        
        // Start new interval
        this.refreshInterval = setInterval(() => {
            this.refreshData();
        }, this.refreshRate * 1000);
    }
    
    updateServerList() {
        const serverList = document.getElementById('serverList');
        if (!serverList) return;
        
        // Don't update if there's a table inside (used by inline HTML implementation)
        if (serverList.querySelector('table')) {
            return;
        }
        
        // Clear existing list
        serverList.innerHTML = '';
        
        // Create new list items
        const template = document.getElementById('serverItemTemplate');
        
        this.servers.forEach(server => {
            // Clone template
            const serverItem = template.content.cloneNode(true);
            
            // Set server name
            serverItem.querySelector('.server-name').textContent = server.name;
            
            // Set status with appropriate class
            const statusElement = serverItem.querySelector('.server-status');
            statusElement.textContent = server.status;
            statusElement.classList.add(server.status);
            
            // Set metrics
            serverItem.querySelector('.cpu-usage').textContent = `CPU: ${server.cpu}%`;
            serverItem.querySelector('.memory-usage').textContent = `Memory: ${server.memory}%`;
            serverItem.querySelector('.disk-usage').textContent = `Disk: ${server.disk}%`;
            
            // Set up buttons
            const startBtn = serverItem.querySelector('.start-btn');
            const stopBtn = serverItem.querySelector('.stop-btn');
            const restartBtn = serverItem.querySelector('.restart-btn');
            
            // Update button states based on server status
            if (server.status === 'running') {
                startBtn.disabled = true;
                stopBtn.disabled = false;
                restartBtn.disabled = false;
            } else if (server.status === 'stopped') {
                startBtn.disabled = false;
                stopBtn.disabled = true;
                restartBtn.disabled = true;
            }
            
            // Set data attribute for server ID
            const serverElement = serverItem.querySelector('.server-item');
            serverElement.dataset.serverId = server.id;
            
            // Add event listeners to buttons
            startBtn.addEventListener('click', () => this.controlServer(server.id, 'start'));
            stopBtn.addEventListener('click', () => this.controlServer(server.id, 'stop'));
            restartBtn.addEventListener('click', () => this.controlServer(server.id, 'restart'));
            
            // Add to server list
            serverList.appendChild(serverItem);
        });
    }
    
    updateSystemOverview() {
        // Update system overview stats
        document.getElementById('totalServers').textContent = this.servers.length;
        
        const runningServers = this.servers.filter(server => server.status === 'running').length;
        document.getElementById('runningServers').textContent = runningServers;
        
        // Calculate average CPU and memory usage
        const cpuTotal = this.servers.reduce((sum, server) => sum + server.cpu, 0);
        const memoryTotal = this.servers.reduce((sum, server) => sum + server.memory, 0);
        
        const cpuAvg = this.servers.length ? Math.round(cpuTotal / this.servers.length) : 0;
        const memoryAvg = this.servers.length ? Math.round(memoryTotal / this.servers.length) : 0;
        
        document.getElementById('cpuUsage').textContent = `${cpuAvg}%`;
        document.getElementById('memoryUsage').textContent = `${memoryAvg}%`;
    }
    
    updateCharts() {
        this.updateCpuChart();
        this.updateMemoryChart();
        this.updateStatusChart();
        this.updateNetworkChart();
        this.updateDiskChart();
    }
    
    updateCpuChart() {
        const ctx = document.getElementById('cpuChart');
        if (!ctx) return;
        
        const serverNames = this.servers.map(server => server.name);
        const cpuValues = this.servers.map(server => server.cpu);
        const backgroundColors = this.servers.map(() => getRandomColor());
        
        if (this.charts.cpu) {
            // Update existing chart
            this.charts.cpu.data.labels = serverNames;
            this.charts.cpu.data.datasets[0].data = cpuValues;
            this.charts.cpu.update();
        } else {
            // Create new chart
            this.charts.cpu = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: serverNames,
                    datasets: [{
                        label: 'CPU Usage (%)',
                        data: cpuValues,
                        backgroundColor: backgroundColors
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            beginAtZero: true,
                            max: 100
                        }
                    }
                }
            });
        }
    }
    
    updateMemoryChart() {
        const ctx = document.getElementById('memoryChart');
        if (!ctx) return;
        
        const serverNames = this.servers.map(server => server.name);
        const memoryValues = this.servers.map(server => server.memory);
        const backgroundColors = this.servers.map(() => getRandomColor());
        
        if (this.charts.memory) {
            // Update existing chart
            this.charts.memory.data.labels = serverNames;
            this.charts.memory.data.datasets[0].data = memoryValues;
            this.charts.memory.update();
        } else {
            // Create new chart
            this.charts.memory = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: serverNames,
                    datasets: [{
                        label: 'Memory Usage (%)',
                        data: memoryValues,
                        backgroundColor: backgroundColors
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            beginAtZero: true,
                            max: 100
                        }
                    }
                }
            });
        }
    }
    
    updateStatusChart() {
        const ctx = document.getElementById('statusChart');
        if (!ctx) return;
        
        // Count servers by status
        const statusCounts = {
            running: 0,
            stopped: 0,
            error: 0,
            suspended: 0
        };
        
        this.servers.forEach(server => {
            statusCounts[server.status] = (statusCounts[server.status] || 0) + 1;
        });
        
        const labels = Object.keys(statusCounts);
        const data = Object.values(statusCounts);
        const colors = {
            running: '#4CAF50',
            stopped: '#F44336',
            error: '#FF9800',
            suspended: '#9C27B0'
        };
        
        const backgroundColors = labels.map(status => colors[status] || getRandomColor());
        
        if (this.charts.status) {
            // Update existing chart
            this.charts.status.data.labels = labels;
            this.charts.status.data.datasets[0].data = data;
            this.charts.status.data.datasets[0].backgroundColor = backgroundColors;
            this.charts.status.update();
        } else {
            // Create new chart
            this.charts.status = new Chart(ctx, {
                type: 'pie',
                data: {
                    labels: labels,
                    datasets: [{
                        data: data,
                        backgroundColor: backgroundColors
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    plugins: {
                        legend: {
                            position: 'right'
                        }
                    }
                }
            });
        }
    }
    
    updateNetworkChart() {
        const ctx = document.getElementById('networkChart');
        if (!ctx) return;
        
        // Simulate network data
        const labels = ['RX', 'TX'];
        const data = [150, 75]; // MB/s
        
        if (this.charts.network) {
            // Update existing chart
            this.charts.network.data.datasets[0].data = data;
            this.charts.network.update();
        } else {
            // Create new chart
            this.charts.network = new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: labels,
                    datasets: [{
                        label: 'Network (MB/s)',
                        data: data,
                        backgroundColor: ['#42A5F5', '#26C6DA']
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    indexAxis: 'y'
                }
            });
        }
    }
    
    updateDiskChart() {
        const ctx = document.getElementById('diskChart');
        if (!ctx) return;
        
        // Simulate disk data
        const labels = ['Used', 'Free'];
        const data = [350, 650]; // GB
        
        if (this.charts.disk) {
            // Update existing chart
            this.charts.disk.data.datasets[0].data = data;
            this.charts.disk.update();
        } else {
            // Create new chart
            this.charts.disk = new Chart(ctx, {
                type: 'doughnut',
                data: {
                    labels: labels,
                    datasets: [{
                        data: data,
                        backgroundColor: ['#F44336', '#4CAF50']
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false
                }
            });
        }
    }
    
    updateActivityLog() {
        const activityLog = document.getElementById('activityLog');
        if (!activityLog) return;
        
        // Simulate activity log entries
        const activities = [
            { time: new Date(), message: 'Dashboard refreshed', type: 'info' },
            { time: new Date(Date.now() - 5 * 60000), message: 'Server "Production Server" started', type: 'success' },
            { time: new Date(Date.now() - 15 * 60000), message: 'Backup completed', type: 'success' },
            { time: new Date(Date.now() - 30 * 60000), message: 'Server "Test Server" stopped', type: 'warning' }
        ];
        
        activityLog.textContent = '';
        activities.forEach(activity => {
            const entry = document.createElement('div');
            entry.className = 'log-entry ' + activity.type;
            const timestamp = document.createElement('span');
            timestamp.className = 'timestamp';
            timestamp.textContent = activity.time.toLocaleTimeString();
            const message = document.createElement('span');
            message.className = 'message';
            message.textContent = activity.message;
            entry.appendChild(timestamp);
            entry.appendChild(message);
            activityLog.appendChild(entry);
        });
    }
    
    filterServers() {
        const searchTerm = document.getElementById('serverSearch').value.toLowerCase();
        const statusFilter = document.getElementById('statusFilter').value;
        
        const serverItems = document.querySelectorAll('.server-item');
        
        serverItems.forEach(item => {
            const serverName = item.querySelector('.server-name').textContent.toLowerCase();
            const serverStatus = item.querySelector('.server-status').textContent.toLowerCase();
            
            const matchesSearch = serverName.includes(searchTerm);
            const matchesStatus = statusFilter === 'all' || serverStatus === statusFilter;
            
            item.style.display = (matchesSearch && matchesStatus) ? 'flex' : 'none';
        });
    }
    
    toggleEditMode() {
        const editBtn = document.querySelector('.edit-dashboard-btn');
        const isEditing = this.grid.opts.staticGrid;
        
        if (isEditing) {
            // Disable edit mode
            this.grid.enableMove(false);
            editBtn.textContent = 'Edit Dashboard';
            showNotification('Dashboard edit mode disabled', 'info');
        } else {
            // Enable edit mode
            this.grid.enableMove(true);
            editBtn.textContent = 'Save Dashboard';
            showNotification('Dashboard edit mode enabled', 'info');
        }
    }
    
    async controlServer(serverId, action) {
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
            
            showNotification(result.message, 'success');
            
            // Refresh data after a short delay
            setTimeout(() => this.refreshData(), 1000);
            
        } catch (error) {
            console.error(`Server control error (${action}):`, error);
            showNotification(`Failed to ${action} server: ${error.message}`, 'error');
        }
    }

    async testCommand(serverId, commandType, minutes = 5) {
        try {
            let result;
            
            switch (commandType) {
                case 'motd':
                    result = await API.testMOTD(serverId);
                    break;
                case 'save':
                    result = await API.testSave(serverId);
                    break;
                case 'warning':
                    result = await API.testWarning(serverId, minutes);
                    break;
                default:
                    throw new Error(`Unknown test command: ${commandType}`);
            }
            
            showNotification(result.message, 'success');
            
        } catch (error) {
            console.error(`Test command error (${commandType}):`, error);
            showNotification(`Failed to test ${commandType}: ${error.message}`, 'error');
        }
    }
}

// Global functions for HTML onclick handlers
function controlServer(serverId, action) {
    if (window.dashboard) {
        window.dashboard.controlServer(serverId, action);
    }
}

function testCommand(serverId, commandType, minutes = 5) {
    if (window.dashboard) {
        window.dashboard.testCommand(serverId, commandType, minutes);
    }
}

function toggleTestDropdown(serverId) {
    const dropdownId = `test-dropdown-${serverId.replace(/[^a-zA-Z0-9]/g, '-')}`;
    const dropdown = document.getElementById(dropdownId);
    
    if (dropdown) {
        // Close all other dropdowns first
        document.querySelectorAll('.dropdown-menu').forEach(menu => {
            if (menu.id !== dropdownId) {
                menu.style.display = 'none';
            }
        });
        
        // Toggle this dropdown
        dropdown.style.display = dropdown.style.display === 'none' ? 'block' : 'none';
    }
}

// Close dropdowns when clicking outside
document.addEventListener('click', function(event) {
    if (!event.target.closest('.dropdown')) {
        document.querySelectorAll('.dropdown-menu').forEach(menu => {
            menu.style.display = 'none';
        });
    }
});
