import os
import shutil
import hashlib
import bcrypt
from datetime import datetime
from flask import url_for, current_app
from flask_login import UserMixin
from app import db

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    full_name = db.Column(db.String(150))
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(20), default='user')
    department = db.Column(db.String(100))
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    avatar_filename = db.Column(db.String(255))
    use_gravatar = db.Column(db.Boolean, default=False, nullable=False)

    def set_password(self, password):
        self.password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    def check_password(self, password):
        return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))

    @property
    def display_name(self) -> str:
        return self.full_name or self.username

    def avatar_url(self, size: int = 64) -> str:
        if self.use_gravatar and self.email:
            email_hash = hashlib.md5(self.email.strip().lower().encode("utf-8")).hexdigest()
            return f"https://www.gravatar.com/avatar/{email_hash}?s={size}&d=identicon"
        if self.avatar_filename:
            try:
                upload_folder = os.path.join(current_app.static_folder, "uploads", "avatars")
                legacy_folder = os.path.join(current_app.root_path, "static", "uploads", "avatars")
                path = os.path.join(upload_folder, self.avatar_filename)
                if not os.path.isfile(path) and os.path.isfile(os.path.join(legacy_folder, self.avatar_filename)):
                    os.makedirs(upload_folder, exist_ok=True)
                    shutil.move(
                        os.path.join(legacy_folder, self.avatar_filename),
                        path,
                    )
            except RuntimeError:
                # Outside application context; skip migration.
                pass
            except OSError:
                pass
            return url_for("static", filename=f"uploads/avatars/{self.avatar_filename}")
        if self.email:
            email_hash = hashlib.md5(self.email.strip().lower().encode("utf-8")).hexdigest()
        else:
            email_hash = "00000000000000000000000000000000"
        return f"https://www.gravatar.com/avatar/{email_hash}?s={size}&d=mp"
