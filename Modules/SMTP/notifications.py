# Notifications module
# - Email notifications with templates
import os
import sys
import re
from datetime import datetime

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from Modules.core.common import setup_module_path
setup_module_path()

from Modules.core.server_logging import get_component_logger
logger = get_component_logger("Notifications")

from .mailserver import mail_server

class NotificationManager:
    # Email notifications with templates
    def __init__(self):
        self.templates = self._load_templates()
        self.automated_notifications = self._load_automated_settings()
        self.css_content = self._load_css()

    def _load_css(self):
        # Load CSS for HTML emails
        css_file = os.path.join(os.path.dirname(__file__), 'Mail-Templates', 'mail-template.css')
        try:
            with open(css_file, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            logger.warning(f"CSS load failed: {e}")
            return ""

    def _embed_css_in_html(self, html_content):
        # Replace CSS link with embedded styles
        css_link_pattern = r'<link[^>]*href="mail-template\.css"[^>]*>'
        css_embed = f'<style>\n{self.css_content}\n</style>'
        html_content = re.sub(css_link_pattern, css_embed, html_content, flags=re.IGNORECASE)
        return html_content

    def _load_templates(self):
        # Load email templates
        template_dir = os.path.join(os.path.dirname(__file__), 'Mail-Templates')
        templates = {}

        template_types = ['welcome', 'password_reset', 'account_locked', 'server_alert', 'maintenance', 'custom']

        for template_type in template_types:
            try:
                subject_file = os.path.join(template_dir, f'{template_type}_subject.txt')
                text_file = os.path.join(template_dir, f'{template_type}_text.txt')
                html_file = os.path.join(template_dir, f'{template_type}_html.html')

                with open(subject_file, 'r', encoding='utf-8') as f:
                    subject = f.read().strip()

                with open(text_file, 'r', encoding='utf-8') as f:
                    text_template = f.read()

                with open(html_file, 'r', encoding='utf-8') as f:
                    html_template = f.read()

                templates[template_type] = {
                    'subject': subject,
                    'text_template': text_template,
                    'html_template': html_template
                }

            except FileNotFoundError as e:
                logger.error(f"Template file not found for {template_type}: {e}")
                # Fall back to default templates if files are missing
                templates[template_type] = self._get_default_template(template_type)
            except Exception as e:
                logger.error(f"Error loading template {template_type}: {e}")
                templates[template_type] = self._get_default_template(template_type)

        return templates

    def _get_default_template(self, template_type):
        # Fallback default templates in case files are missing
        defaults = {
            'welcome': {
                'subject': 'Welcome to Server Manager',
                'text_template': 'Welcome {username}! Your account has been created.',
                'html_template': '<html><body><h2>Welcome {username}!</h2></body></html>'
            },
            'password_reset': {
                'subject': 'Password Reset - Server Manager',
                'text_template': 'Password reset for {username}. Temp password: {temp_password}',
                'html_template': '<html><body><h2>Password Reset</h2><p>Temp password: {temp_password}</p></body></html>'
            },
            'account_locked': {
                'subject': 'Account Locked - Server Manager',
                'text_template': 'Account locked for {username}.',
                'html_template': '<html><body><h2>Account Locked</h2></body></html>'
            },
            'server_alert': {
                'subject': 'Server Alert - {server_name}',
                'text_template': 'Server alert for {server_name}: {status} - {message}',
                'html_template': '<html><body><h2>Server Alert</h2><p>{status}: {message}</p></body></html>'
            },
            'maintenance': {
                'subject': 'Scheduled Maintenance - Server Manager',
                'text_template': 'Maintenance from {start_time} to {end_time}.',
                'html_template': '<html><body><h2>Maintenance</h2><p>{start_time} to {end_time}</p></body></html>'
            },
            'custom': {
                'subject': '{custom_subject}',
                'text_template': '{custom_message}',
                'html_template': '<html><body><p>{custom_message}</p></body></html>'
            }
        }
        return defaults.get(template_type, defaults['custom'])

    def _load_automated_settings(self):
        # Load automated notification settings from registry
        try:
            import winreg
            from Modules.core.common import REGISTRY_ROOT, REGISTRY_PATH

            key_path = REGISTRY_PATH + r"\Notifications"
            key = winreg.OpenKey(REGISTRY_ROOT, key_path)

            settings = {
                'welcome_email': bool(int(winreg.QueryValueEx(key, "WelcomeEmail")[0])),
                'password_reset_email': bool(int(winreg.QueryValueEx(key, "PasswordResetEmail")[0])),
                'account_locked_email': bool(int(winreg.QueryValueEx(key, "AccountLockedEmail")[0])),
                'server_alerts_email': bool(int(winreg.QueryValueEx(key, "ServerAlertsEmail")[0])),
                'maintenance_email': bool(int(winreg.QueryValueEx(key, "MaintenanceEmail")[0])),
                'admin_only_alerts': bool(int(winreg.QueryValueEx(key, "AdminOnlyAlerts")[0]))
            }

            winreg.CloseKey(key)
            logger.info("Automated notification settings loaded from registry")
            return settings

        except Exception as e:
            logger.warning(f"Failed to load automated settings: {e}")
            return self._get_default_automated_settings()

    def _get_default_automated_settings(self):
        # Return default automated notification settings
        return {
            'welcome_email': True,
            'password_reset_email': True,
            'account_locked_email': True,
            'server_alerts_email': True,
            'maintenance_email': True,
            'admin_only_alerts': False
        }

    def save_automated_settings(self, settings):
        # Save automated notification settings to registry
        try:
            import winreg
            from Modules.core.common import REGISTRY_ROOT, REGISTRY_PATH

            key_path = REGISTRY_PATH + r"\Notifications"
            key = winreg.CreateKey(REGISTRY_ROOT, key_path)

            winreg.SetValueEx(key, "WelcomeEmail", 0, winreg.REG_SZ, str(int(settings.get('welcome_email', True))))
            winreg.SetValueEx(key, "PasswordResetEmail", 0, winreg.REG_SZ, str(int(settings.get('password_reset_email', True))))
            winreg.SetValueEx(key, "AccountLockedEmail", 0, winreg.REG_SZ, str(int(settings.get('account_locked_email', True))))
            winreg.SetValueEx(key, "ServerAlertsEmail", 0, winreg.REG_SZ, str(int(settings.get('server_alerts_email', True))))
            winreg.SetValueEx(key, "MaintenanceEmail", 0, winreg.REG_SZ, str(int(settings.get('maintenance_email', True))))
            winreg.SetValueEx(key, "AdminOnlyAlerts", 0, winreg.REG_SZ, str(int(settings.get('admin_only_alerts', False))))

            winreg.CloseKey(key)
            logger.info("Automated notification settings saved to registry")
            self.automated_notifications = settings
            return True

        except Exception as e:
            logger.error(f"Failed to save automated settings: {e}")
            return False

    def send_notification(self, notification_type, recipient_email, **kwargs):
        # Send a notification email
        if not mail_server.is_enabled():
            logger.warning("Mail server is disabled, cannot send notification")
            return False

        if notification_type not in self.templates:
            logger.error(f"Unknown notification type: {notification_type}")
            return False

        template = self.templates[notification_type]

        # Format subject and body
        subject = template['subject'].format(**kwargs)
        text_body = template['text_template'].format(**kwargs)

        # Handle HTML template with special formatting for server alerts
        if notification_type == 'server_alert':
            alert_color = '#fff3cd' if 'warning' in kwargs.get('status', '').lower() else '#f8d7da'
            border_color = '#ffeaa7' if 'warning' in kwargs.get('status', '').lower() else '#f5c6cb'
            kwargs['alert_color'] = alert_color
            kwargs['border_color'] = border_color

        html_body = template['html_template'].format(**kwargs)

        # Embed CSS in HTML for email compatibility
        html_body = self._embed_css_in_html(html_body)

        # Send email
        return mail_server.send_email(recipient_email, subject, text_body, html_body)

    def send_welcome_email(self, user):
        # Send welcome email to new user
        if not self.automated_notifications.get('welcome_email', True):
            return True

        kwargs = {
            'username': user.username,
            'email': user.email or '',
            'created_at': user.created_at.strftime('%Y-%m-%d %H:%M:%S') if user.created_at else datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

        return self.send_notification('welcome', user.email, **kwargs)

    def send_custom_notification(self, recipient_email, subject, message):
        # Send custom notification
        kwargs = {
            'custom_subject': subject,
            'custom_message': message
        }

        return self.send_notification('custom', recipient_email, **kwargs)

    def get_automated_settings(self):
        # Get current automated notification settings
        return self.automated_notifications.copy()

# Global notification manager instance
notification_manager = NotificationManager()
