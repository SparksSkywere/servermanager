(function() {
    function createSvgIcon(width, height, viewBox, paths) {
        const ns = 'http' + '://www.w3.org/2000/svg';
        const svg = document.createElementNS(ns, 'svg');
        svg.setAttribute('width', String(width));
        svg.setAttribute('height', String(height));
        svg.setAttribute('viewBox', viewBox);
        svg.setAttribute('fill', 'none');
        svg.setAttribute('stroke', 'currentColor');
        svg.setAttribute('stroke-width', '2');

        paths.forEach(({ tag, attrs }) => {
            const el = document.createElementNS(ns, tag);
            Object.entries(attrs).forEach(([key, value]) => {
                el.setAttribute(key, String(value));
            });
            svg.appendChild(el);
        });

        return svg;
    }

    function renderSimpleHeader(options = {}) {
        const header = document.getElementById('appHeader');
        if (!header) {
            return;
        }

        const defaultDisplayName = options.defaultDisplayName || 'User';
        const safeDisplayName = String(defaultDisplayName || 'User');
        const initial = safeDisplayName.charAt(0).toUpperCase() || 'U';

        const brand = document.createElement('div');
        brand.className = 'header-brand';
        brand.appendChild(createSvgIcon(24, 24, '0 0 24 24', [
            { tag: 'rect', attrs: { x: 2, y: 2, width: 20, height: 8, rx: 2 } },
            { tag: 'rect', attrs: { x: 2, y: 14, width: 20, height: 8, rx: 2 } },
            { tag: 'circle', attrs: { cx: 6, cy: 6, r: 1, fill: 'currentColor' } },
            { tag: 'circle', attrs: { cx: 6, cy: 18, r: 1, fill: 'currentColor' } },
        ]));
        const brandText = document.createElement('span');
        brandText.textContent = 'Server Manager';
        brand.appendChild(brandText);

        const userMenu = document.createElement('div');
        userMenu.className = 'user-menu';
        userMenu.addEventListener('click', toggleUserDropdown);

        const avatar = document.createElement('div');
        avatar.className = 'user-avatar';
        avatar.id = 'headerAvatar';
        const avatarSpan = document.createElement('span');
        avatarSpan.textContent = initial;
        avatar.appendChild(avatarSpan);

        const displayName = document.createElement('span');
        displayName.id = 'headerDisplayName';
        displayName.textContent = safeDisplayName;

        userMenu.appendChild(avatar);
        userMenu.appendChild(displayName);
        userMenu.appendChild(createSvgIcon(14, 14, '0 0 24 24', [
            { tag: 'path', attrs: { d: 'M6 9l6 6 6-6' } },
        ]));

        const userDropdown = document.createElement('div');
        userDropdown.className = 'user-dropdown';
        userDropdown.id = 'userDropdown';

        const dashboardLink = document.createElement('a');
        dashboardLink.href = 'dashboard.html';
        dashboardLink.appendChild(createSvgIcon(18, 18, '0 0 24 24', [
            { tag: 'rect', attrs: { x: 3, y: 3, width: 7, height: 7 } },
            { tag: 'rect', attrs: { x: 14, y: 3, width: 7, height: 7 } },
            { tag: 'rect', attrs: { x: 14, y: 14, width: 7, height: 7 } },
            { tag: 'rect', attrs: { x: 3, y: 14, width: 7, height: 7 } },
        ]));
        dashboardLink.appendChild(document.createTextNode(' Dashboard'));

        const themeControl = document.createElement('div');
        themeControl.className = 'theme-control';
        const themeLabel = document.createElement('label');
        themeLabel.className = 'theme-control-label';
        themeLabel.setAttribute('for', 'headerThemeSelect');
        themeLabel.textContent = 'Theme';
        const themeSelect = document.createElement('select');
        themeSelect.id = 'headerThemeSelect';
        themeSelect.className = 'theme-select';
        themeSelect.setAttribute('data-theme-select', '');
        themeSelect.addEventListener('change', function onThemeChange() {
            if (typeof window.selectTheme === 'function') {
                window.selectTheme(this.value);
            }
        });
        const defaultOption = document.createElement('option');
        defaultOption.value = 'dark';
        defaultOption.textContent = 'Dark';
        themeSelect.appendChild(defaultOption);
        themeControl.appendChild(themeLabel);
        themeControl.appendChild(themeSelect);

        const divider = document.createElement('div');
        divider.className = 'divider';

        const logoutLink = document.createElement('a');
        logoutLink.href = '#';
        logoutLink.className = 'danger';
        logoutLink.addEventListener('click', function onLogoutClick(event) {
            event.preventDefault();
            logout();
        });
        logoutLink.appendChild(createSvgIcon(18, 18, '0 0 24 24', [
            { tag: 'path', attrs: { d: 'M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4' } },
            { tag: 'polyline', attrs: { points: '16 17 21 12 16 7' } },
            { tag: 'line', attrs: { x1: 21, y1: 12, x2: 9, y2: 12 } },
        ]));
        logoutLink.appendChild(document.createTextNode(' Logout'));

        userDropdown.appendChild(dashboardLink);
        userDropdown.appendChild(themeControl);
        userDropdown.appendChild(divider);
        userDropdown.appendChild(logoutLink);

        header.replaceChildren(brand, userMenu, userDropdown);

        if (window.ThemeManager) {
            if (typeof window.ThemeManager.populateThemeSelects === 'function') {
                window.ThemeManager.populateThemeSelects(header);
            }
            if (typeof window.ThemeManager.updateThemeUI === 'function') {
                window.ThemeManager.updateThemeUI();
            }
        }
    }

    function applySimpleProfile(profile, fallbackDisplayName = 'User') {
        const name = profile.display_name || profile.username || fallbackDisplayName;
        const headerDisplayName = document.getElementById('headerDisplayName');
        const avatarEl = document.getElementById('headerAvatar');

        if (headerDisplayName) {
            headerDisplayName.textContent = name;
        }

        if (avatarEl) {
            avatarEl.textContent = '';
            if (profile.avatar) {
                const img = document.createElement('img');
                img.src = profile.avatar;
                img.alt = '';
                avatarEl.appendChild(img);
            } else {
                const span = document.createElement('span');
                span.textContent = name.charAt(0).toUpperCase();
                avatarEl.appendChild(span);
            }
        }
    }

    function toggleUserDropdown(event) {
        if (event) {
            event.stopPropagation();
        }

        document.getElementById('userDropdown')?.classList.toggle('show');
    }

    function closeUserDropdown() {
        document.getElementById('userDropdown')?.classList.remove('show');
    }

    function handleDocumentClick(event) {
        if (event.target.closest('.user-menu') || event.target.closest('.user-dropdown')) {
            return;
        }

        closeUserDropdown();
    }

    function bindShellEvents() {
        if (document.body?.dataset.shellEventsBound === 'true') {
            return;
        }

        document.addEventListener('click', handleDocumentClick);

        if (document.body) {
            document.body.dataset.shellEventsBound = 'true';
        }
    }

    function showNotification(message, type = 'info', duration = 4000) {
        const el = document.getElementById('notification');
        if (!el) {
            return;
        }

        el.textContent = message;
        el.className = `notification show ${type}`;
        window.setTimeout(() => el.classList.remove('show'), duration);
    }

    function logout() {
        sessionStorage.clear();
        window.location.href = 'login.html';
    }

    bindShellEvents();

    window.ServerManagerWeb = {
        renderSimpleHeader,
        applySimpleProfile,
        showNotification,
        toggleUserDropdown,
        closeUserDropdown,
        logout
    };

    window.showNotification = showNotification;
    window.toggleUserDropdown = toggleUserDropdown;
    window.logout = logout;
})();
