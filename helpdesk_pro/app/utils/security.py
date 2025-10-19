import base64, os, sys
from cryptography.fernet import Fernet
if sys.platform.startswith('win'):
    import win32crypt

def encrypt_secret(secret: str) -> str:
    if sys.platform.startswith('win'):
        data = win32crypt.CryptProtectData(secret.encode(), None, None, None, None, 0)
        return base64.b64encode(data[1]).decode()
    else:
        key = os.environ.get('FERNET_KEY') or Fernet.generate_key()
        f = Fernet(key)
        return 'fernet:' + key.decode() + ':' + f.encrypt(secret.encode()).decode()

def decrypt_secret(token: str) -> str:
    if token.startswith('fernet:'):
        _, key, enc = token.split(':', 2)
        f = Fernet(key.encode())
        return f.decrypt(enc.encode()).decode()
    if sys.platform.startswith('win'):
        data = base64.b64decode(token)
        return win32crypt.CryptUnprotectData(data, None, None, None, 0)[1].decode()
    return token
