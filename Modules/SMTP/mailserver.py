# Mail Server Module for Server Manager
# Handles SMTP email sending with support for various providers (Gmail, Outlook, custom SMTP)
# Includes OAuth 2.0 support for Microsoft Exchange with 2FA
import os
import sys
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import logging
from pathlib import Path
import json
import time
import webbrowser
import http.server
import socketserver
from urllib.parse import parse_qs, urlparse
import threading

# Add project root to sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Import standardized logging
try:
    from Modules.server_logging import get_component_logger
    logger = get_component_logger("MailServer")
except Exception:
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger("MailServer")

# Try to import OAuth libraries
try:
    import msal
    import requests_oauthlib
    OAUTH_AVAILABLE = True
except ImportError:
    msal = None
    requests_oauthlib = None
    OAUTH_AVAILABLE = False
    logger.warning("OAuth libraries not available. Microsoft OAuth authentication will be disabled.")

class MailServer:
    """SMTP Mail Server class with support for various email providers and OAuth 2.0"""

    # Predefined SMTP configurations for common providers
    SMTP_CONFIGS = {
        'gmail': {
            'server': 'smtp.gmail.com',
            'port': 587,
            'tls': True,
            'ssl': False
        },
        'outlook': {
            'server': 'smtp-mail.outlook.com',
            'port': 587,
            'tls': True,
            'ssl': False
        },
        'office365': {
            'server': 'smtp.office365.com',
            'port': 587,
            'tls': True,
            'ssl': False
        },
        'yahoo': {
            'server': 'smtp.mail.yahoo.com',
            'port': 587,
            'tls': True,
            'ssl': False
        },
        'custom': {
            'server': '',
            'port': 587,
            'tls': True,
            'ssl': False
        }
    }

    # Microsoft OAuth configuration
    MICROSOFT_OAUTH_CONFIG = {
        'client_id': 'your-client-id-here',  # Will be configured by user
        'client_secret': 'your-client-secret-here',  # Will be configured by user
        'authority': 'https://login.microsoftonline.com/common',
        'scope': ['https://graph.microsoft.com/Mail.Send', 'https://graph.microsoft.com/Mail.ReadWrite'],
        'redirect_uri': 'http://localhost:8080/callback',
        'graph_endpoint': 'https://graph.microsoft.com/v1.0'
    }

    def __init__(self, config=None):
        """Initialize mail server with configuration"""
        self.config = config or self._load_config()
        self.server = None
        self.connected = False
        self.oauth_token = None
        self.token_expires_at = None
        self.msal_app = None

    def _load_config(self):
        """Load mail server configuration from registry"""
        try:
            import winreg
            from Modules.common import REGISTRY_ROOT, REGISTRY_PATH

            key = winreg.OpenKey(REGISTRY_ROOT, REGISTRY_PATH + r"\MailServer")

            config = {
                'provider': winreg.QueryValueEx(key, "Provider")[0],
                'server': winreg.QueryValueEx(key, "Server")[0],
                'port': int(winreg.QueryValueEx(key, "Port")[0]),
                'username': winreg.QueryValueEx(key, "Username")[0],
                'password': winreg.QueryValueEx(key, "Password")[0],
                'from_email': winreg.QueryValueEx(key, "FromEmail")[0],
                'from_name': winreg.QueryValueEx(key, "FromName")[0],
                'use_tls': bool(int(winreg.QueryValueEx(key, "UseTLS")[0])),
                'use_ssl': bool(int(winreg.QueryValueEx(key, "UseSSL")[0])),
                'enabled': bool(int(winreg.QueryValueEx(key, "Enabled")[0])),
                # OAuth settings
                'use_oauth': bool(int(winreg.QueryValueEx(key, "UseOAuth")[0]) if self._reg_value_exists(key, "UseOAuth") else 0),
                'client_id': winreg.QueryValueEx(key, "ClientId")[0] if self._reg_value_exists(key, "ClientId") else '',
                'client_secret': winreg.QueryValueEx(key, "ClientSecret")[0] if self._reg_value_exists(key, "ClientSecret") else '',
                'tenant_id': winreg.QueryValueEx(key, "TenantId")[0] if self._reg_value_exists(key, "TenantId") else '',
                'oauth_token': winreg.QueryValueEx(key, "OAuthToken")[0] if self._reg_value_exists(key, "OAuthToken") else '',
                'token_expires': int(winreg.QueryValueEx(key, "TokenExpires")[0]) if self._reg_value_exists(key, "TokenExpires") else 0
            }

            winreg.CloseKey(key)
            logger.info("Mail server configuration loaded from registry")

            # Load OAuth token if available
            if config.get('oauth_token'):
                try:
                    self.oauth_token = json.loads(config['oauth_token'])
                    self.token_expires_at = config.get('token_expires', 0)
                except Exception as e:
                    logger.warning(f"Failed to load OAuth token: {e}")
                    self.oauth_token = None

            return config

        except Exception as e:
            logger.warning(f"Failed to load mail config from registry: {e}")
            return self._get_default_config()

    def _reg_value_exists(self, key, value_name):
        """Check if registry value exists"""
        try:
            import winreg
            winreg.QueryValueEx(key, value_name)
            return True
        except FileNotFoundError:
            return False

    def _get_default_config(self):
        """Return default mail server configuration"""
        return {
            'provider': 'custom',
            'server': '',
            'port': 587,
            'username': '',
            'password': '',
            'from_email': '',
            'from_name': 'Server Manager',
            'use_tls': True,
            'use_ssl': False,
            'enabled': False,
            # OAuth defaults
            'use_oauth': False,
            'client_id': '',
            'client_secret': '',
            'tenant_id': '',
            'oauth_token': '',
            'token_expires': 0
        }

    def save_config(self, config):
        """Save mail server configuration to registry"""
        try:
            import winreg
            from Modules.common import REGISTRY_ROOT, REGISTRY_PATH

            key_path = REGISTRY_PATH + r"\MailServer"
            key = winreg.CreateKey(REGISTRY_ROOT, key_path)

            winreg.SetValueEx(key, "Provider", 0, winreg.REG_SZ, config.get('provider', 'custom'))
            winreg.SetValueEx(key, "Server", 0, winreg.REG_SZ, config.get('server', ''))
            winreg.SetValueEx(key, "Port", 0, winreg.REG_SZ, str(config.get('port', 587)))
            winreg.SetValueEx(key, "Username", 0, winreg.REG_SZ, config.get('username', ''))
            winreg.SetValueEx(key, "Password", 0, winreg.REG_SZ, config.get('password', ''))
            winreg.SetValueEx(key, "FromEmail", 0, winreg.REG_SZ, config.get('from_email', ''))
            winreg.SetValueEx(key, "FromName", 0, winreg.REG_SZ, config.get('from_name', 'Server Manager'))
            winreg.SetValueEx(key, "UseTLS", 0, winreg.REG_SZ, str(int(config.get('use_tls', True))))
            winreg.SetValueEx(key, "UseSSL", 0, winreg.REG_SZ, str(int(config.get('use_ssl', False))))
            winreg.SetValueEx(key, "Enabled", 0, winreg.REG_SZ, str(int(config.get('enabled', False))))

            # OAuth settings
            winreg.SetValueEx(key, "UseOAuth", 0, winreg.REG_SZ, str(int(config.get('use_oauth', False))))
            winreg.SetValueEx(key, "ClientId", 0, winreg.REG_SZ, config.get('client_id', ''))
            winreg.SetValueEx(key, "ClientSecret", 0, winreg.REG_SZ, config.get('client_secret', ''))
            winreg.SetValueEx(key, "TenantId", 0, winreg.REG_SZ, config.get('tenant_id', ''))

            # Save OAuth token if available
            if hasattr(self, 'oauth_token') and self.oauth_token:
                winreg.SetValueEx(key, "OAuthToken", 0, winreg.REG_SZ, json.dumps(self.oauth_token))
                winreg.SetValueEx(key, "TokenExpires", 0, winreg.REG_SZ, str(int(self.token_expires_at or 0)))
            else:
                winreg.SetValueEx(key, "OAuthToken", 0, winreg.REG_SZ, '')
                winreg.SetValueEx(key, "TokenExpires", 0, winreg.REG_SZ, '0')

            winreg.CloseKey(key)
            logger.info("Mail server configuration saved to registry")
            self.config = config
            return True

        except Exception as e:
            logger.error(f"Failed to save mail config: {e}")
            return False

    def setup_oauth(self, client_id, client_secret, tenant_id=''):
        """Setup OAuth configuration for Microsoft authentication"""
        if not OAUTH_AVAILABLE:
            return False, "OAuth libraries not available"

        self.config['use_oauth'] = True
        self.config['client_id'] = client_id
        self.config['client_secret'] = client_secret
        self.config['tenant_id'] = tenant_id

        # Setup MSAL app - only if msal is available
        if msal:
            authority = f"https://login.microsoftonline.com/{tenant_id}" if tenant_id else self.MICROSOFT_OAUTH_CONFIG['authority']
            self.msal_app = msal.ConfidentialClientApplication(
            client_id=client_id,
            client_credential=client_secret,
            authority=authority
        )

        logger.info("OAuth configuration setup completed")
        return True, "OAuth setup successful"

    def perform_oauth_login(self):
        """Perform interactive OAuth login for Microsoft authentication"""
        if not OAUTH_AVAILABLE or not self.msal_app:
            return False, "OAuth not configured"

        try:
            # Generate authorization URL
            auth_url = self.msal_app.get_authorization_request_url(
                scopes=self.MICROSOFT_OAUTH_CONFIG['scope'],
                redirect_uri=self.MICROSOFT_OAUTH_CONFIG['redirect_uri']
            )

            print(f"Please visit this URL to authenticate: {auth_url}")
            webbrowser.open(auth_url)

            # Start local server to receive callback
            auth_code = self._start_oauth_callback_server()

            if not auth_code:
                return False, "Authentication cancelled or failed"

            # Exchange code for token
            result = self.msal_app.acquire_token_by_authorization_code(
                code=auth_code,
                scopes=self.MICROSOFT_OAUTH_CONFIG['scope'],
                redirect_uri=self.MICROSOFT_OAUTH_CONFIG['redirect_uri']
            )

            if result and isinstance(result, dict) and 'access_token' in result:
                self.oauth_token = result
                expires_in_raw = result.get('expires_in')
                if expires_in_raw is not None:
                    if isinstance(expires_in_raw, str):
                        try:
                            expires_in = int(expires_in_raw)
                        except (ValueError, TypeError):
                            expires_in = 3600
                    elif isinstance(expires_in_raw, (int, float)):
                        expires_in = float(expires_in_raw)
                    else:
                        expires_in = 3600
                else:
                    expires_in = 3600
                self.token_expires_at = time.time() + expires_in
                self._save_oauth_token()
                logger.info("OAuth authentication successful")
                return True, "Authentication successful"
            else:
                if isinstance(result, dict):
                    error = result.get('error_description', 'Unknown error')
                else:
                    error = 'Authentication failed'
                logger.error(f"OAuth authentication failed: {error}")
                return False, f"Authentication failed: {error}"

        except Exception as e:
            logger.error(f"OAuth login failed: {e}")
            return False, str(e)

    def _start_oauth_callback_server(self, port=8080):
        """Start local server to receive OAuth callback"""
        auth_code = []

        class OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()

                query = urlparse(self.path).query
                params = parse_qs(query)

                if 'code' in params:
                    auth_code.append(params['code'][0])
                    self.wfile.write(b'<html><body><h1>Authentication successful!</h1><p>You can close this window.</p></body></html>')
                else:
                    self.wfile.write(b'<html><body><h1>Authentication failed!</h1><p>No authorization code received.</p></body></html>')

                # Signal to stop server
                threading.Thread(target=self.server.shutdown).start()

            def log_message(self, format, *args):
                # Suppress server logs
                pass

        try:
            with socketserver.TCPServer(("", port), OAuthCallbackHandler) as httpd:
                print(f"Waiting for authentication callback on http://localhost:{port}/callback...")
                httpd.timeout = 300  # 5 minute timeout
                httpd.serve_forever()
        except Exception as e:
            logger.error(f"Callback server error: {e}")

        return auth_code[0] if auth_code else None

    def _save_oauth_token(self):
        """Save OAuth token to registry"""
        if self.oauth_token and self.token_expires_at:
            self.config['oauth_token'] = json.dumps(self.oauth_token)
            self.config['token_expires'] = int(self.token_expires_at)
            self.save_config(self.config)

    def _refresh_oauth_token(self):
        """Refresh OAuth token if expired"""
        if not self.oauth_token or not self.msal_app:
            return False

        try:
            if not self.oauth_token or not isinstance(self.oauth_token, dict):
                return False

            result = self.msal_app.acquire_token_silent(
                scopes=self.MICROSOFT_OAUTH_CONFIG['scope'],
                account=self.oauth_token.get('account')
            )

            if result and isinstance(result, dict) and 'access_token' in result:
                self.oauth_token = result
                expires_in_raw = result.get('expires_in')
                if expires_in_raw is not None:
                    if isinstance(expires_in_raw, str):
                        try:
                            expires_in = int(expires_in_raw)
                        except (ValueError, TypeError):
                            expires_in = 3600
                    elif isinstance(expires_in_raw, (int, float)):
                        expires_in = float(expires_in_raw)
                    else:
                        expires_in = 3600
                else:
                    expires_in = 3600
                self.token_expires_at = time.time() + expires_in
                self._save_oauth_token()
                logger.info("OAuth token refreshed successfully")
                return True
            else:
                logger.warning("Failed to refresh OAuth token silently")
                return False

        except Exception as e:
            logger.error(f"Token refresh failed: {e}")
            return False

    def _get_valid_oauth_token(self):
        """Get a valid OAuth token, refreshing if necessary"""
        if not self.oauth_token or not isinstance(self.oauth_token, dict):
            return None

        # Check if token is expired or will expire soon (within 5 minutes)
        if self.token_expires_at and time.time() >= (self.token_expires_at - 300):
            if not self._refresh_oauth_token():
                logger.warning("Token refresh failed, need re-authentication")
                return None

        return self.oauth_token.get('access_token')

    def send_email_oauth(self, to_email, subject, body, html_body=None, attachments=None):
        """Send email using Microsoft Graph API with OAuth"""
        if not OAUTH_AVAILABLE:
            return False, "OAuth libraries not available"

        token = self._get_valid_oauth_token()
        if not token:
            return False, "No valid OAuth token available"

        try:
            import requests

            # Prepare email message
            email_data = {
                "message": {
                    "subject": subject,
                    "body": {
                        "contentType": "HTML" if html_body else "Text",
                        "content": html_body if html_body else body
                    },
                    "toRecipients": [
                        {
                            "emailAddress": {
                                "address": to_email
                            }
                        }
                    ]
                }
            }

            # Add attachments if provided
            if attachments:
                email_data["message"]["attachments"] = []
                for attachment_path in attachments:
                    if os.path.exists(attachment_path):
                        with open(attachment_path, 'rb') as f:
                            content = f.read()
                            filename = os.path.basename(attachment_path)

                            # Properly base64 encode the content
                            import base64
                            encoded_content = base64.b64encode(content).decode('utf-8')

                            attachment = {
                                "@odata.type": "#microsoft.graph.fileAttachment",
                                "name": filename,
                                "contentType": "application/octet-stream",
                                "contentBytes": encoded_content
                            }
                            email_data["message"]["attachments"].append(attachment)

            headers = {
                'Authorization': f'Bearer {token}',
                'Content-Type': 'application/json'
            }

            # Send email via Microsoft Graph API
            graph_endpoint = f"{self.MICROSOFT_OAUTH_CONFIG['graph_endpoint']}/me/sendMail"
            response = requests.post(graph_endpoint, headers=headers, json=email_data)

            if response.status_code == 202:
                logger.info(f"Email sent successfully to: {to_email} via OAuth")
                return True, "Email sent successfully"
            else:
                error_msg = f"Failed to send email: {response.status_code} - {response.text}"
                logger.error(error_msg)
                return False, error_msg

        except Exception as e:
            logger.error(f"OAuth email send failed: {e}")
            return False, str(e)

    def connect(self):
        """Connect to SMTP server"""
        if not self.config.get('enabled', False):
            logger.warning("Mail server is disabled")
            return False

        # If using OAuth, we don't need traditional SMTP connection
        if self.config.get('use_oauth', False):
            logger.info("Using OAuth authentication - no SMTP connection needed")
            self.connected = True
            return True

        try:
            server = self.config['server']
            port = self.config['port']
            use_ssl = self.config.get('use_ssl', False)
            use_tls = self.config.get('use_tls', True)

            if use_ssl:
                self.server = smtplib.SMTP_SSL(server, port)
            else:
                self.server = smtplib.SMTP(server, port)

            if use_tls and not use_ssl:
                self.server.starttls()

            # Login if credentials provided
            if self.config.get('username') and self.config.get('password'):
                self.server.login(self.config['username'], self.config['password'])

            self.connected = True
            logger.info(f"Connected to SMTP server: {server}:{port}")
            return True

        except Exception as e:
            logger.error(f"Failed to connect to SMTP server: {e}")
            self.connected = False
            return False

    def disconnect(self):
        """Disconnect from SMTP server"""
        if self.server and self.connected:
            try:
                self.server.quit()
                self.connected = False
                logger.info("Disconnected from SMTP server")
            except Exception as e:
                logger.error(f"Error disconnecting from SMTP server: {e}")

    def send_email(self, to_email, subject, body, html_body=None, attachments=None):
        """Send email to specified recipient"""
        if not self.config.get('enabled', False):
            logger.warning("Mail server is disabled, cannot send email")
            return False

        # Use OAuth method if configured
        if self.config.get('use_oauth', False):
            return self.send_email_oauth(to_email, subject, body, html_body, attachments)

        if not self.connected:
            if not self.connect():
                return False

        try:
            # Create message
            msg = MIMEMultipart('alternative')
            msg['From'] = f"{self.config.get('from_name', 'Server Manager')} <{self.config['from_email']}>"
            msg['To'] = to_email
            msg['Subject'] = subject

            # Add text body
            if body:
                msg.attach(MIMEText(body, 'plain'))

            # Add HTML body if provided
            if html_body:
                msg.attach(MIMEText(html_body, 'html'))

            # Add attachments if provided
            if attachments:
                for attachment_path in attachments:
                    if os.path.exists(attachment_path):
                        with open(attachment_path, 'rb') as f:
                            part = MIMEBase('application', 'octet-stream')
                            part.set_payload(f.read())
                            encoders.encode_base64(part)
                            filename = os.path.basename(attachment_path)
                            part.add_header('Content-Disposition', f'attachment; filename="{filename}"')
                            msg.attach(part)

            # Send email
            if self.server:
                self.server.sendmail(self.config['from_email'], to_email, msg.as_string())
                logger.info(f"Email sent successfully to: {to_email}")
                return True
            else:
                logger.error("SMTP server connection is not available")
                return False

        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            # Try to reconnect on failure
            self.disconnect()
            return False

    def test_connection(self):
        """Test SMTP connection and authentication"""
        if not self.config.get('enabled', False):
            return False, "Mail server is disabled"

        # Test OAuth connection
        if self.config.get('use_oauth', False):
            if not OAUTH_AVAILABLE:
                return False, "OAuth libraries not available"

            token = self._get_valid_oauth_token()
            if token:
                return True, "OAuth authentication successful"
            else:
                return False, "OAuth authentication failed - token expired or invalid"

        try:
            if self.connect():
                self.disconnect()
                return True, "Connection successful"
            else:
                return False, "Failed to connect to SMTP server"
        except Exception as e:
            return False, f"Connection test failed: {str(e)}"

    def get_oauth_setup_instructions(self):
        """Get instructions for setting up Microsoft OAuth"""
        instructions = """
Microsoft OAuth Setup Instructions for Server Manager:

1. Go to Azure Portal: https://portal.azure.com
2. Navigate to 'Azure Active Directory' > 'App registrations'
3. Click 'New registration'
4. Enter a name (e.g., 'Server Manager Mail')
5. Select 'Accounts in this organizational directory only' or 'Accounts in any organizational directory'
6. For redirect URI, add: http://localhost:8080/callback
7. Click 'Register'

8. In the app registration:
   - Go to 'Certificates & secrets'
   - Click 'New client secret'
   - Copy the secret value (you won't see it again!)

9. Go to 'API permissions'
   - Click 'Add a permission'
   - Select 'Microsoft Graph'
   - Add these delegated permissions:
     * Mail.Send
     * Mail.ReadWrite

10. Copy the following values:
    - Application (client) ID
    - Client secret
    - Directory (tenant) ID (from Overview page)

11. Configure in Server Manager:
    - Provider: office365
    - Client ID: [paste Application ID]
    - Client Secret: [paste Client secret]
    - Tenant ID: [paste Directory ID]
    - From Email: [your Office 365 email address]

12. Click 'Setup OAuth' and follow the authentication flow.

Note: For security, the app should be configured to require admin consent for the Mail permissions.
        """
        return instructions

    def is_oauth_configured(self):
        """Check if OAuth is properly configured"""
        if not OAUTH_AVAILABLE:
            return False

        required_fields = ['client_id', 'client_secret', 'tenant_id']
        for field in required_fields:
            if not self.config.get(field):
                return False

        return self.msal_app is not None

    def get_provider_config(self, provider):
        """Get predefined configuration for a provider"""
        return self.SMTP_CONFIGS.get(provider, self.SMTP_CONFIGS['custom']).copy()

    def is_enabled(self):
        """Check if mail server is enabled"""
        return self.config.get('enabled', False)

    def __del__(self):
        """Cleanup on destruction"""
        self.disconnect()


# Global mail server instance
mail_server = MailServer()
