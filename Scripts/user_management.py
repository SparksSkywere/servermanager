import os
import sys
# Add project root to sys.path for module resolution
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import winreg
from sqlalchemy import create_engine, Column, Integer, String, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import pyotp  # pip install pyotp

# Use SQL_Connection module for all DB config and engine
from Modules.SQL_Connection import get_engine

Base = declarative_base()

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, nullable=False)
    password = Column(String(256), nullable=False)  # Store hashed passwords!
    email = Column(String(128), unique=True)
    is_admin = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    # Add 2FA fields
    two_factor_enabled = Column(Boolean, default=False)
    two_factor_secret = Column(String(64), nullable=True)

class UserManager:
    def __init__(self, engine=None):
        if engine is None:
            engine = get_engine()
        self.engine = engine
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(bind=self.engine)

    def add_user(self, username, password, email, is_admin=False):
        session = self.Session()
        user = User(username=username, password=password, email=email, is_admin=is_admin)
        session.add(user)
        session.commit()
        session.close()

    def get_user(self, username):
        session = self.Session()
        user = session.query(User).filter_by(username=username).first()
        session.close()
        return user

    def list_users(self):
        session = self.Session()
        users = session.query(User).all()
        session.close()
        return users

    def update_user(self, username, **kwargs):
        session = self.Session()
        user = session.query(User).filter_by(username=username).first()
        if user:
            for k, v in kwargs.items():
                setattr(user, k, v)
            session.commit()
        session.close()

    def delete_user(self, username):
        session = self.Session()
        user = session.query(User).filter_by(username=username).first()
        if user:
            session.delete(user)
            session.commit()
        session.close()

    def verify_2fa(self, username, token, admin_override=False):
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