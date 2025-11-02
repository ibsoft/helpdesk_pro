import base64, os, sys, re, hashlib
from typing import List, Tuple, Optional
from cryptography.fernet import Fernet
from flask import current_app, has_app_context
if sys.platform.startswith('win'):
    import win32crypt

_FERNET_INSTANCE: Optional[Fernet] = None


def _get_fernet() -> Fernet:
    global _FERNET_INSTANCE
    if _FERNET_INSTANCE is not None:
        return _FERNET_INSTANCE
    key = os.environ.get('FERNET_KEY')
    has_ctx = has_app_context()
    if not key and has_ctx:
        key = current_app.config.get('FERNET_KEY')
    if not key:
        seed = os.environ.get('SECRET_KEY')
        if not seed and has_ctx:
            seed = current_app.config.get('SECRET_KEY')
        if seed:
            digest = hashlib.sha256(seed.encode()).digest()
            key = base64.urlsafe_b64encode(digest).decode()
    if not key:
        raise RuntimeError(
            "FERNET_KEY is not configured and no SECRET_KEY available to derive one."
        )
    if has_ctx and key and not current_app.config.get('FERNET_KEY'):
        current_app.config['FERNET_KEY'] = key.decode() if isinstance(key, bytes) else key
    key_bytes = key.encode() if isinstance(key, str) else key
    _FERNET_INSTANCE = Fernet(key_bytes)
    return _FERNET_INSTANCE


def encrypt_secret(secret: str) -> str:
    if sys.platform.startswith('win'):
        data = win32crypt.CryptProtectData(secret.encode(), None, None, None, None, 0)
        return base64.b64encode(data[1]).decode()
    else:
        token = _get_fernet().encrypt(secret.encode()).decode()
        return 'fernet:' + token

def decrypt_secret(token: str) -> str:
    if token.startswith('fernet:'):
        parts = token.split(':', 2)
        # Legacy format stored the key alongside the ciphertext.
        if len(parts) == 3:
            _, key, enc = parts
            f = Fernet(key.encode())
            return f.decrypt(enc.encode()).decode()
        _, enc = parts
        return _get_fernet().decrypt(enc.encode()).decode()
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
