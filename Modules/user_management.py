import os
import sys
import logging
from datetime import datetime
import hashlib
import pyotp

# Add project root to sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from sqlalchemy import Column, Integer, String, Boolean, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Use the new user_database module for all DB config and engine
from Modules.Database.user_database import get_user_engine

# Import standardized logging
try:
    from Modules.server_logging import get_component_logger
    logger = get_component_logger("UserManagement")
except Exception:
    import logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    logger = logging.getLogger("UserManagement")
Base = declarative_base()

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
    # Add additional profile fields
    first_name = Column(String(50), nullable=True)
    last_name = Column(String(50), nullable=True)
    display_name = Column(String(100), nullable=True)

class UserManager:
    def __init__(self, engine=None):
        if engine is None:
            engine = get_user_engine()
        self.engine = engine
        self.Session = sessionmaker(bind=engine)
        
        # Create tables if they don't exist
        Base.metadata.create_all(engine)
        
        # Migrate existing database schema
        self._migrate_database_schema()
        
    def get_user(self, username):
        """Get user by username"""
        try:
            session = self.Session()
            user = session.query(User).filter(User.username == username).first()
            session.close()
            return user
        except Exception as e:
            logger.error(f"Error getting user {username}: {e}")
            return None
    
    def list_users(self):
        """Get all users"""
        try:
            session = self.Session()
            users = session.query(User).all()
            session.close()
            return users
        except Exception as e:
            logger.error(f"Error listing users: {e}")
            return []
    
    def add_user(self, username, password, email="", is_admin=False):
        """Add a new user"""
        try:
            session = self.Session()
            
            # Hash password
            hashed_password = hashlib.sha256(password.encode()).hexdigest()
            
            user = User(
                username=username,
                password=hashed_password,
                email=email,
                is_admin=is_admin
            )
            
            session.add(user)
            session.commit()
            session.close()
            
            logger.info(f"Added user: {username}")
            return True
            
        except Exception as e:
            logger.error(f"Error adding user {username}: {e}")
            return False
    
    def delete_user(self, username):
        """Delete a user"""
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
        """Update user information"""
        try:
            session = self.Session()
            user = session.query(User).filter(User.username == username).first()
            
            if user:
                if password is not None:
                    hashed_password = hashlib.sha256(password.encode()).hexdigest()
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
        """Authenticate a user with username and password"""
        try:
            user = self.get_user(username)
            if not user:
                logger.warning(f"User not found: {username}")
                return False
            
            # Check if user is active
            if not getattr(user, 'is_active', True):
                logger.warning(f"Inactive user attempted login: {username}")
                return False
            
            # Verify password
            hashed_password = hashlib.sha256(password.encode()).hexdigest()
            stored_password = getattr(user, 'password', None)
            if not stored_password or stored_password != hashed_password:
                logger.warning(f"Invalid password for user: {username}")
                return False
            
            # Update last login time
            try:
                self.update_user(username, last_login=datetime.now())
            except Exception as e:
                logger.warning(f"Failed to update last login time: {e}")
            
            logger.info(f"Successfully authenticated user: {username}")
            return True
            
        except Exception as e:
            logger.error(f"Error authenticating user {username}: {e}")
            return False

    def verify_2fa(self, username, token, admin_override=False):
        """Verify 2FA token for user"""
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
                
            totp = pyotp.TOTP(str(two_factor_secret))
            return totp.verify(token)
        except Exception as e:
            logger.error(f"Error verifying 2FA for {username}: {e}")
            return False

    def _migrate_database_schema(self):
        """Migrate database schema to add missing columns"""
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
                    'display_name': 'TEXT'
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