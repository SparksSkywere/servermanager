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

# Use SQL_Connection module for all DB config and engine
from Modules.SQL_Connection import get_engine

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

class UserManager:
    def __init__(self, engine=None):
        if engine is None:
            engine = get_engine()
        self.engine = engine
        self.Session = sessionmaker(bind=engine)
        
        # Create tables if they don't exist
        Base.metadata.create_all(engine)
        
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
                    user.password = hashlib.sha256(password.encode()).hexdigest()
                if email is not None:
                    user.email = email
                if is_admin is not None:
                    user.is_admin = is_admin
                
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

    def verify_2fa(self, username, token, admin_override=False):
        """Verify 2FA token for user"""
        try:
            session = self.Session()
            user = session.query(User).filter_by(username=username).first()
            session.close()
            
            if not user or not user.two_factor_enabled:
                return True  # 2FA not enabled
            if admin_override:
                return True  # Admin override
            if not user.two_factor_secret:
                return False
                
            totp = pyotp.TOTP(user.two_factor_secret)
            return totp.verify(token)
        except Exception as e:
            logger.error(f"Error verifying 2FA for {username}: {e}")
            return False