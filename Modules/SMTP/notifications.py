# Notifications Module for Server Manager
# Handles different types of email notifications with templates
import os
import sys
from datetime import datetime

# Add project root to sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import standardized logging
try:
    from Modules.server_logging import get_component_logger
    logger = get_component_logger("Notifications")
except Exception:
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger("Notifications")

from .mailserver import mail_server

class NotificationManager:
    # Manages email notifications with templates and automated sending

    def __init__(self):
        self.templates = self._load_templates()
        self.automated_notifications = self._load_automated_settings()

    def _load_templates(self):
        # Load email templates
        return {
            'welcome': {
                'subject': 'Welcome to Server Manager',
                'text_template': """
Welcome {username}!

Your account has been created successfully on Server Manager.

Username: {username}
Email: {email}
Created: {created_at}

Please keep this information safe. You can log in using your username and the password you set.

If you have any questions, please contact your administrator.

Best regards,
Server Manager Team
                """,
                'html_template': """
<html>
<body>
    <h2>Welcome {username}!</h2>
    <p>Your account has been created successfully on Server Manager.</p>
    <div style="background-color: #f5f5f5; padding: 15px; border-radius: 5px; margin: 20px 0;">
        <strong>Account Details:</strong><br>
        Username: {username}<br>
        Email: {email}<br>
        Created: {created_at}
    </div>
    <p>Please keep this information safe. You can log in using your username and the password you set.</p>
    <p>If you have any questions, please contact your administrator.</p>
    <br>
    <p>Best regards,<br>Server Manager Team</p>
</body>
</html>
                """
            },
            'password_reset': {
                'subject': 'Password Reset - Server Manager',
                'text_template': """
Password Reset Request

Hello {username},

A password reset has been requested for your Server Manager account.

If you requested this reset, please use the following temporary password to log in:
Temporary Password: {temp_password}

Please change your password immediately after logging in.

If you did not request this reset, please ignore this email and contact your administrator.

This temporary password will expire in 24 hours.

Best regards,
Server Manager Team
                """,
                'html_template': """
<html>
<body>
    <h2>Password Reset Request</h2>
    <p>Hello {username},</p>
    <p>A password reset has been requested for your Server Manager account.</p>

    <div style="background-color: #fff3cd; border: 1px solid #ffeaa7; padding: 15px; border-radius: 5px; margin: 20px 0;">
        <strong>If you requested this reset, please use the following temporary password to log in:</strong><br>
        <span style="font-family: monospace; font-size: 16px; background-color: #f8f9fa; padding: 5px; border-radius: 3px;">{temp_password}</span>
    </div>

    <p style="color: #dc3545;"><strong>Please change your password immediately after logging in.</strong></p>

    <p>If you did not request this reset, please ignore this email and contact your administrator.</p>

    <p><em>This temporary password will expire in 24 hours.</em></p>

    <br>
    <p>Best regards,<br>Server Manager Team</p>
</body>
</html>
                """
            },
            'account_locked': {
                'subject': 'Account Locked - Server Manager',
                'text_template': """
Account Locked Notice

Hello {username},

Your Server Manager account has been locked due to multiple failed login attempts.

To unlock your account, please contact your administrator or use the password reset feature if available.

If you need immediate assistance, please contact support.

Best regards,
Server Manager Team
                """,
                'html_template': """
<html>
<body>
    <h2>Account Locked Notice</h2>
    <p>Hello {username},</p>
    <p>Your Server Manager account has been locked due to multiple failed login attempts.</p>

    <div style="background-color: #f8d7da; border: 1px solid #f5c6cb; padding: 15px; border-radius: 5px; margin: 20px 0;">
        <strong>To unlock your account:</strong>
        <ul>
            <li>Contact your administrator</li>
            <li>Use the password reset feature if available</li>
        </ul>
    </div>

    <p>If you need immediate assistance, please contact support.</p>

    <br>
    <p>Best regards,<br>Server Manager Team</p>
</body>
</html>
                """
            },
            'server_alert': {
                'subject': 'Server Alert - {server_name}',
                'text_template': """
Server Alert: {server_name}

Status: {status}
Message: {message}

Server: {server_name}
Time: {timestamp}

Please check the server status and take appropriate action if needed.

Best regards,
Server Manager Monitoring
                """,
                'html_template': """
<html>
<body>
    <h2>Server Alert: {server_name}</h2>
    <div style="background-color: {alert_color}; border: 1px solid {border_color}; padding: 15px; border-radius: 5px; margin: 20px 0;">
        <strong>Status:</strong> {status}<br>
        <strong>Message:</strong> {message}<br>
        <strong>Server:</strong> {server_name}<br>
        <strong>Time:</strong> {timestamp}
    </div>
    <p>Please check the server status and take appropriate action if needed.</p>
    <br>
    <p>Best regards,<br>Server Manager Monitoring</p>
</body>
</html>
                """
            },
            'maintenance': {
                'subject': 'Scheduled Maintenance - Server Manager',
                'text_template': """
Scheduled Maintenance Notice

Hello {username},

Server Manager will undergo scheduled maintenance:

Start Time: {start_time}
End Time: {end_time}
Duration: {duration}

During this maintenance window:
- The web interface may be unavailable
- Server management features may be limited
- Automated processes will be paused

We apologize for any inconvenience this may cause.

Best regards,
Server Manager Team
                """,
                'html_template': """
<html>
<body>
    <h2>Scheduled Maintenance Notice</h2>
    <p>Hello {username},</p>
    <p>Server Manager will undergo scheduled maintenance:</p>

    <div style="background-color: #e7f3ff; border: 1px solid #b3d7ff; padding: 15px; border-radius: 5px; margin: 20px 0;">
        <strong>Maintenance Schedule:</strong><br>
        Start Time: {start_time}<br>
        End Time: {end_time}<br>
        Duration: {duration}
    </div>

    <p><strong>During this maintenance window:</strong></p>
    <ul>
        <li>The web interface may be unavailable</li>
        <li>Server management features may be limited</li>
        <li>Automated processes will be paused</li>
    </ul>

    <p>We apologize for any inconvenience this may cause.</p>

    <br>
    <p>Best regards,<br>Server Manager Team</p>
</body>
</html>
                """
            },
            'custom': {
                'subject': '{custom_subject}',
                'text_template': '{custom_message}',
                'html_template': '<html><body><p>{custom_message}</p></body></html>'
            }
        }

    def _load_automated_settings(self):
        # Load automated notification settings from registry
        try:
            import winreg
            from Modules.common import REGISTRY_ROOT, REGISTRY_PATH

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
            from Modules.common import REGISTRY_ROOT, REGISTRY_PATH

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

    def send_password_reset_email(self, user, temp_password):
        # Send password reset email
        if not self.automated_notifications.get('password_reset_email', True):
            return True

        kwargs = {
            'username': user.username,
            'temp_password': temp_password
        }

        return self.send_notification('password_reset', user.email, **kwargs)

    def send_account_locked_email(self, user):
        # Send account locked notification
        if not self.automated_notifications.get('account_locked_email', True):
            return True

        kwargs = {
            'username': user.username
        }

        return self.send_notification('account_locked', user.email, **kwargs)

    def send_server_alert(self, server_name, status, message, recipients=None):
        # Send server alert to administrators or specified recipients
        if not self.automated_notifications.get('server_alerts_email', True):
            return True

        if recipients is None:
            # Get admin users from database
            try:
                from Modules.Database.user_database import get_user_engine
                from Modules.user_management import UserManager

                engine = get_user_engine()
                user_manager = UserManager(engine)
                users = user_manager.list_users()

                recipients = []
                for user in users:
                    email = getattr(user, 'email', None)
                    if email and str(email).strip():
                        if self.automated_notifications.get('admin_only_alerts', False):
                            if getattr(user, 'is_admin', False):
                                recipients.append(email)
                        else:
                            recipients.append(email)

            except Exception as e:
                logger.error(f"Failed to get recipients for server alert: {e}")
                return False

        kwargs = {
            'server_name': server_name,
            'status': status,
            'message': message,
            'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }

        success = True
        for email in recipients:
            if not self.send_notification('server_alert', email, **kwargs):
                success = False

        return success

    def send_maintenance_notification(self, start_time, end_time, duration, recipients=None):
        # Send maintenance notification
        if not self.automated_notifications.get('maintenance_email', True):
            return True

        if recipients is None:
            # Get all users from database
            try:
                from Modules.Database.user_database import get_user_engine
                from Modules.user_management import UserManager

                engine = get_user_engine()
                user_manager = UserManager(engine)
                users = user_manager.list_users()
                recipients = []
                for user in users:
                    email = getattr(user, 'email', None)
                    if email and str(email).strip():
                        recipients.append(email)

            except Exception as e:
                logger.error(f"Failed to get recipients for maintenance notification: {e}")
                return False

        success = True
        for email in recipients:
            kwargs = {
                'username': email.split('@')[0],  # Use part before @ as username
                'start_time': start_time,
                'end_time': end_time,
                'duration': duration
            }

            if not self.send_notification('maintenance', email, **kwargs):
                success = False

        return success

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

    def is_notification_enabled(self, notification_type):
        # Check if a specific notification type is enabled
        return self.automated_notifications.get(notification_type, True)


# Global notification manager instance
notification_manager = NotificationManager()