const CONFIG = {
    API_BASE_URL: window.location.origin + '/api',
    WEBSOCKET_URL: (window.location.protocol === 'https:' ? 'wss://' : 'ws://') + window.location.hostname + ':8081',
    REFRESH_INTERVAL: 30000, // 30 seconds
    DEFAULT_INSTALL_DIR: 'C:\\Games\\Servers',
    COMMON_APP_IDS: {
        'Valheim': '896660',
        'ARK': '376030',
        'Minecraft': '0',
        '7 Days to Die': '294420'
    }
};

export default CONFIG;
