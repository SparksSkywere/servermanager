# User management
import os
import sys
import time
from datetime import datetime
import hashlib

# Setup module path first before any imports
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..')))

from Modules.core.common import setup_module_path
setup_module_path()

try:
    import pyotp as _pyotp
    PYOTP_AVAILABLE = True
except ImportError:
    _pyotp = None  # type: ignore
    PYOTP_AVAILABLE = False

def create_totp(secret: str):
    # TOTP wrapper-raises if pyotp missing
    if not PYOTP_AVAILABLE or _pyotp is None:
        raise ImportError("pyotp not available")
    return _pyotp.TOTP(str(secret))

def generate_secret():
    # Generate TOTP secret
    if not PYOTP_AVAILABLE or _pyotp is None:
        raise ImportError("pyotp not available")
    return _pyotp.random_base32()

def create_provisioning_uri(secret: str, username: str, issuer: str):
    # QR code URI for authenticator apps
    if not PYOTP_AVAILABLE or _pyotp is None:
        raise ImportError("pyotp not available")
    return _pyotp.totp.TOTP(secret).provisioning_uri(
        name=username,
        issuer_name=issuer
    )

from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Use the new user_database module for all DB config and engine
from Modules.Database.user_database import get_user_engine

# Import standardized logging
from Modules.core.server_logging import get_component_logger
logger = get_component_logger("UserManagement")
Base = declarative_base()

# User model
class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    username = Column(String(50), unique=True, nullable=False)
    password = Column(String(255), nullable=False)
    email = Column(String(100))
    is_admin = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login = Column(DateTime)
    # Add 2FA fields
    two_factor_enabled = Column(Boolean, default=False)
    two_factor_secret = Column(String(64), nullable=True)
    # Profile fields
    first_name = Column(String(50), nullable=True)
    last_name = Column(String(50), nullable=True)
    display_name = Column(String(100), nullable=True)
    # Avatar - stored as base64 or URL
    avatar = Column(String(500), nullable=True)
    # Additional profile data
    bio = Column(String(500), nullable=True)
    timezone = Column(String(50), nullable=True)
    theme_preference = Column(String(20), default='dark')

# User manager
class UserManager:
    def __init__(self, engine=None):
        if engine is None:
            engine = get_user_engine()
        self.engine = engine
        self.Session = sessionmaker(bind=engine)

        # Create tables if they don't exist
        Base.metadata.create_all(engine)

        # Ensure root admin user exists
        from Modules.Database.user_database import ensure_root_admin
        ensure_root_admin(engine)

        # Migrate existing database schema
        self._migrate_database_schema()

    def get_user(self, username):
        # Get user by username
        try:
            session = self.Session()
            user = session.query(User).filter(User.username == username).first()
            session.close()
            return user
        except Exception as e:
            logger.error(f"Error getting user {username}: {e}")
            return None

    def list_users(self):
        # Get all users
        try:
            session = self.Session()
            users = session.query(User).all()
            session.close()
            return users
        except Exception as e:
            logger.error(f"Error listing users: {e}")
            return []

    def add_user(self, username, password, email="", is_admin=False):
        # Add a new user
        try:
            session = self.Session()

            # Hash password with bcrypt
            import bcrypt
            hashed_password = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

            user = User(
                username=username,
                password=hashed_password,
                email=email,
                is_admin=is_admin
            )

            session.add(user)
            session.commit()

            # Send welcome email if email is provided
            if email and email.strip():
                try:
                    from Modules.SMTP.notifications import notification_manager
                    user_obj = session.query(User).filter(User.username == username).first()
                    notification_manager.send_welcome_email(user_obj)
                except Exception as email_error:
                    logger.warning(f"Failed to send welcome email to {username}: {email_error}")

            session.close()

            logger.info(f"Added user: {username}")
            return True

        except Exception as e:
            logger.error(f"Error adding user {username}: {e}")
            return False

    def delete_user(self, username):
        # Delete a user
        try:
            session = self.Session()
            user = session.query(User).filter(User.username == username).first()

            if user:
                session.delete(user)
                session.commit()
                logger.info(f"Deleted user: {username}")
                result = True
            else:
                logger.warning(f"User not found: {username}")
                result = False

            session.close()
            return result

        except Exception as e:
            logger.error(f"Error deleting user {username}: {e}")
            return False

    def update_user(self, username, password=None, email=None, is_admin=None, **kwargs):
        # Update user information
        try:
            session = self.Session()
            user = session.query(User).filter(User.username == username).first()

            if user:
                if password is not None:
                    import bcrypt
                    hashed_password = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
                    setattr(user, 'password', hashed_password)
                if email is not None:
                    setattr(user, 'email', email)
                if is_admin is not None:
                    setattr(user, 'is_admin', is_admin)

                # Handle additional kwargs
                for key, value in kwargs.items():
                    if hasattr(user, key):
                        setattr(user, key, value)

                session.commit()
                logger.info(f"Updated user: {username}")
                result = True
            else:
                logger.warning(f"User not found: {username}")
                result = False

            session.close()
            return result

        except Exception as e:
            logger.error(f"Error updating user {username}: {e}")
            return False

    def authenticate_user(self, username, password):
        # Authenticate a user with username and password
        max_retries = 3
        for attempt in range(max_retries):
            try:
                user = self.get_user(username)
                if not user:
                    logger.warning(f"User not found: {username}")
                    return None

                # Check if user is active
                if not getattr(user, 'is_active', True):
                    logger.warning(f"Inactive user attempted login: {username}")
                    return None

                # Verify password - try bcrypt first, fallback to SHA256
                stored_password = getattr(user, 'password', None)
                if not stored_password:
                    logger.warning(f"No password stored for user: {username}")
                    return None

                authenticated = False

                # Try bcrypt first
                try:
                    import bcrypt
                    if bcrypt.checkpw(password.encode(), stored_password.encode()):
                        authenticated = True
                except Exception:
                    # If bcrypt fails, try SHA256 hash check
                    hashed_password = hashlib.sha256(password.encode()).hexdigest()
                    if stored_password == hashed_password:
                        authenticated = True
                        # Optionally update to bcrypt on successful login
                        try:
                            self.update_user(username, password=password)
                            logger.info(f"Updated password hash to bcrypt for user: {username}")
                        except Exception as e:
                            logger.warning(f"Failed to update password hash: {e}")

                if not authenticated:
                    logger.warning(f"Invalid password for user: {username}")
                    return None

                # Update last login time
                try:
                    self.update_user(username, last_login=datetime.now())
                except Exception as e:
                    logger.warning(f"Failed to update last login time: {e}")

                logger.info(f"Successfully authenticated user: {username}")
                return user

            except Exception as e:
                error_msg = str(e).lower()
                if "database is locked" in error_msg or "database locked" in error_msg:
                    if attempt < max_retries - 1:
                        logger.warning(f"Database locked, retrying authentication (attempt {attempt + 1}/{max_retries})")
                        time.sleep(0.5)  # Wait before retry
                        continue
                    else:
                        logger.error(f"Database still locked after {max_retries} attempts")
                logger.error(f"Error authenticating user {username}: {e}")
                return None

    def verify_2fa(self, username, token, admin_override=False):
        # Verify 2FA token for user
        if not PYOTP_AVAILABLE:
            logger.warning("pyotp library not available, cannot verify 2FA")
            return False

        try:
            session = self.Session()
            user = session.query(User).filter_by(username=username).first()
            session.close()

            if not user:
                return False

            # Check if 2FA is enabled - explicitly check the boolean value
            two_factor_enabled = getattr(user, 'two_factor_enabled', False)
            if not two_factor_enabled:
                return True  # 2FA not enabled

            if admin_override:
                return True  # Admin override

            # Check if user has 2FA secret - explicitly get the string value
            two_factor_secret = getattr(user, 'two_factor_secret', None)
            if not two_factor_secret:
                return False

            # Check if pyotp is available
            if not PYOTP_AVAILABLE:
                logger.error("pyotp library not available for 2FA verification")
                return False

            totp = create_totp(str(two_factor_secret))
            return totp.verify(token)
        except Exception as e:
            logger.error(f"Error verifying 2FA for {username}: {e}")
            return False

    def _migrate_database_schema(self):
        # Migrate database schema to add missing columns
        try:
            with self.engine.connect() as conn:
                # Check which columns exist and add missing ones
                # This is a simple migration approach - in production you'd want proper migrations

                # Get current table info
                from sqlalchemy import text

                # For SQLite, we need to check column existence differently
                result = conn.execute(text("PRAGMA table_info(users)"))
                existing_columns = {row[1] for row in result.fetchall()}

                # Define required columns with their SQL definitions
                required_columns = {
                    'email': 'TEXT',
                    'is_active': 'BOOLEAN DEFAULT 1',
                    'created_at': 'DATETIME',
                    'last_login': 'DATETIME',
                    'two_factor_enabled': 'BOOLEAN DEFAULT 0',
                    'two_factor_secret': 'TEXT',
                    'first_name': 'TEXT',
                    'last_name': 'TEXT',
                    'display_name': 'TEXT',
                    'avatar': 'TEXT',
                    'bio': 'TEXT',
                    'timezone': 'TEXT',
                    'theme_preference': "TEXT DEFAULT 'dark'"
                }

                # Add missing columns
                for column, definition in required_columns.items():
                    if column not in existing_columns:
                        try:
                            alter_sql = f"ALTER TABLE users ADD COLUMN {column} {definition}"
                            conn.execute(text(alter_sql))
                            logger.info(f"Added column {column} to users table")
                        except Exception as e:
                            logger.warning(f"Failed to add column {column}: {e}")

                conn.commit()

        except Exception as e:
            logger.error(f"Error migrating database schema: {e}")
            # Continue execution even if migration fails

    def setup_2fa(self, username):
        # Setup 2FA for a user and return the secret and QR code URL
        if not PYOTP_AVAILABLE:
            return False, "pyotp library not available"

        try:
            user = self.get_user(username)
            if not user:
                return False, "User not found"

            # Generate new secret
            secret = generate_secret()

            # Update user with 2FA secret
            session = self.Session()
            db_user = session.query(User).filter(User.username == username).first()
            if db_user:
                setattr(db_user, 'two_factor_secret', secret)
                setattr(db_user, 'two_factor_enabled', False)  # Will be enabled after verification
                session.commit()
                session.close()

                # Generate provisioning URI for QR code
                provisioning_uri = create_provisioning_uri(secret, username, "Server Manager")

                return True, {
                    'secret': secret,
                    'provisioning_uri': provisioning_uri
                }
            else:
                session.close()
                return False, "User not found"

        except Exception as e:
            logger.error(f"Error setting up 2FA for {username}: {e}")
            return False, str(e)

    def enable_2fa(self, username, token):
        # Enable 2FA for a user after verifying the token
        if not PYOTP_AVAILABLE:
            return False, "pyotp library not available"

        try:
            user = self.get_user(username)
            if not user:
                return False, "User not found"

            two_factor_secret = getattr(user, 'two_factor_secret', None)
            if not two_factor_secret:
                return False, "2FA not set up for this user"

            # Verify the token
            totp = create_totp(str(two_factor_secret))
            if not totp.verify(token):
                return False, "Invalid token"

            # Enable 2FA
            session = self.Session()
            db_user = session.query(User).filter(User.username == username).first()
            if db_user:
                setattr(db_user, 'two_factor_enabled', True)
                session.commit()
                session.close()
                return True, "2FA enabled successfully"
            else:
                session.close()
                return False, "User not found"

        except Exception as e:
            logger.error(f"Error enabling 2FA for {username}: {e}")
            return False, str(e)

    def disable_2fa(self, username):
        # Disable 2FA for a user
        try:
            session = self.Session()
            db_user = session.query(User).filter(User.username == username).first()
            if db_user:
                setattr(db_user, 'two_factor_enabled', False)
                setattr(db_user, 'two_factor_secret', None)
                session.commit()
                session.close()
                return True, "2FA disabled successfully"
            else:
                session.close()
                return False, "User not found"

        except Exception as e:
            logger.error(f"Error disabling 2FA for {username}: {e}")
            return False, str(e)


