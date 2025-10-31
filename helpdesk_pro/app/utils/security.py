import base64, os, sys, re
from typing import List, Tuple
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


def validate_password_strength(password: str) -> Tuple[bool, List[str]]:
    """
    Validate password strength. Returns (is_valid, [error messages]).
    Requirements:
      - minimum length 12
      - contains uppercase, lowercase, digit, and symbol
      - contains no whitespace
    """

    errors: List[str] = []
    if password is None:
        password = ""
    if len(password) < 12:
        errors.append("Password must be at least 12 characters long.")
    if not re.search(r"[A-Z]", password):
        errors.append("Password must include at least one uppercase letter.")
    if not re.search(r"[a-z]", password):
        errors.append("Password must include at least one lowercase letter.")
    if not re.search(r"[0-9]", password):
        errors.append("Password must include at least one number.")
    if not re.search(r"[^A-Za-z0-9]", password):
        errors.append("Password must include at least one symbol.")
    if re.search(r"\s", password):
        errors.append("Password cannot contain whitespace characters.")
    return len(errors) == 0, errors
