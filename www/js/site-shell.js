(function() {
    function renderSimpleHeader(options = {}) {
        const header = document.getElementById('appHeader');
        if (!header) {
            return;
        }

        const defaultDisplayName = options.defaultDisplayName || 'User';
        header.innerHTML = `
            <div class="header-brand">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <rect x="2" y="2" width="20" height="8" rx="2"></rect>
                    <rect x="2" y="14" width="20" height="8" rx="2"></rect>
                    <circle cx="6" cy="6" r="1" fill="currentColor"></circle>
                    <circle cx="6" cy="18" r="1" fill="currentColor"></circle>
                </svg>
                <span>Server Manager</span>
            </div>
            <div class="user-menu" onclick="toggleUserDropdown(event)">
                <div class="user-avatar" id="headerAvatar"><span>${defaultDisplayName.charAt(0).toUpperCase()}</span></div>
                <span id="headerDisplayName">${defaultDisplayName}</span>
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M6 9l6 6 6-6"></path></svg>
            </div>
            <div class="user-dropdown" id="userDropdown">
                <a href="dashboard.html">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="7" height="7"></rect><rect x="14" y="3" width="7" height="7"></rect><rect x="14" y="14" width="7" height="7"></rect><rect x="3" y="14" width="7" height="7"></rect></svg>
                    Dashboard
                </a>
                <div class="theme-control">
                    <label class="theme-control-label" for="headerThemeSelect">Theme</label>
                    <select id="headerThemeSelect" class="theme-select" data-theme-select onchange="selectTheme(this.value)">
                        <option value="dark">Dark</option>
                    </select>
                </div>
                <div class="divider"></div>
                <a href="#" class="danger" onclick="logout(); return false;">
                    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"></path><polyline points="16 17 21 12 16 7"></polyline><line x1="21" y1="12" x2="9" y2="12"></line></svg>
                    Logout
                </a>
            </div>
        `;

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

        closeUserDropdown()
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