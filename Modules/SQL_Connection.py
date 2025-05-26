import os
import sys
import winreg
import base64
from sqlalchemy import create_engine

def get_encryption_key():
    key_path = r"C:\ProgramData\ServerManager\encryption.key"
    if not os.path.exists(key_path):
        raise RuntimeError("Encryption key not found at " + key_path)
    with open(key_path, "rb") as f:
        key = f.read()
        # Fernet keys must be 32 bytes base64-encoded (44 bytes)
        if len(key) == 32:
            key = base64.urlsafe_b64encode(key)
        return key

def decrypt_value(enc_value, key):
    try:
        from cryptography.fernet import Fernet
        f = Fernet(key)
        # Registry stores as base64-encoded string, decode first
        if isinstance(enc_value, str):
            enc_value = base64.b64decode(enc_value)
        return f.decrypt(enc_value).decode("utf-8")
    except Exception:
        # fallback: assume plain text if not encrypted
        if isinstance(enc_value, bytes):
            return enc_value.decode("utf-8")
        return enc_value

def get_sql_config_from_registry():
    try:
        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"Software\SkywereIndustries\Servermanager")
        sql_type = winreg.QueryValueEx(key, "SQLType")[0]
        sql_version = winreg.QueryValueEx(key, "SQLVersion")[0]
        sql_location = winreg.QueryValueEx(key, "SQLLocation")[0]
        sql_db_path = winreg.QueryValueEx(key, "SQLDatabasePath")[0]
        # Optional: Encrypted user/pass
        try:
            sql_user = winreg.QueryValueEx(key, "SQLUser")[0]
            sql_pass = winreg.QueryValueEx(key, "SQLPassword")[0]
        except FileNotFoundError:
            sql_user = ""
            sql_pass = ""
        winreg.CloseKey(key)
        return {
            "type": sql_type,
            "version": sql_version,
            "location": sql_location,
            "db_path": sql_db_path,
            "user": sql_user,
            "password": sql_pass
        }
    except Exception as e:
        print(f"Could not read SQL configuration from registry: {e}", file=sys.stderr)
        sys.exit(1)

def build_db_url(sql_conf):
    sql_type = sql_conf["type"].lower()
    key = None
    user = sql_conf.get("user", "")
    password = sql_conf.get("password", "")
    # Decrypt user/pass if present and not empty
    if user and password:
        try:
            key = get_encryption_key()
            user = decrypt_value(user, key)
            password = decrypt_value(password, key)
        except Exception:
            pass
    if sql_type == "sqlite":
        db_path = sql_conf["db_path"]
        if not os.path.isabs(db_path):
            db_path = os.path.abspath(db_path)
        return f"sqlite:///{db_path}"
    elif sql_type.startswith("mssql") or "express" in sql_type:
        instance = sql_conf['type'] if sql_type != "mssql" else "SQLEXPRESS"
        location = sql_conf['location']
        if os.path.isabs(location) or location.startswith("\\"):
            location = f"localhost\\{instance}"
        elif "\\" not in location and instance.lower() != "mssql":
            location = f"{location}\\{instance}"
        # Use Windows Authentication if user/password are empty
        if not user and not password:
            # Use & instead of ; for query parameters
            return f"mssql+pyodbc://@{location}/ServerManager?driver=ODBC+Driver+17+for+SQL+Server&Trusted_Connection=yes"
        else:
            return f"mssql+pyodbc://{user}:{password}@{location}/ServerManager?driver=ODBC+Driver+17+for+SQL+Server"
    elif sql_type == "mysql":
        return f"mysql+pymysql://{user}:{password}@{sql_conf['location']}/servermanager"
    elif sql_type == "mariadb":
        return f"mariadb+pymysql://{user}:{password}@{sql_conf['location']}/servermanager"
    else:
        raise Exception(f"Unsupported SQL type: {sql_conf['type']}")

def get_engine(echo=False):
    sql_conf = get_sql_config_from_registry()
    db_url = build_db_url(sql_conf)
    return create_engine(db_url, echo=echo)
