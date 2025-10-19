from functools import wraps
from flask import abort
from flask_login import current_user


def role_required(*roles):
    """
    Restrict access to users whose role is in the given list.
    Example: @role_required('admin', 'manager')
    """
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if not current_user.is_authenticated:
                abort(403)
            if current_user.role.lower() not in [r.lower() for r in roles]:
                abort(403)
            return f(*args, **kwargs)
        return wrapper
    return decorator
