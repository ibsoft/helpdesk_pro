# -*- coding: utf-8 -*-
"""
Address book entry model.
Stores vendor, customer, and stakeholder contact information.
"""

from datetime import datetime

from app import db


class AddressBookEntry(db.Model):
    __tablename__ = "address_book_entry"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)
    category = db.Column(db.String(120))
    company = db.Column(db.String(150))
    job_title = db.Column(db.String(150))
    department = db.Column(db.String(150))
    email = db.Column(db.String(150))
    phone = db.Column(db.String(80))
    mobile = db.Column(db.String(80))
    website = db.Column(db.String(255))
    address_line = db.Column(db.String(255))
    city = db.Column(db.String(120))
    state = db.Column(db.String(120))
    postal_code = db.Column(db.String(40))
    country = db.Column(db.String(120))
    tags = db.Column(db.String(255))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name or "",
            "category": self.category or "",
            "company": self.company or "",
            "job_title": self.job_title or "",
            "department": self.department or "",
            "email": self.email or "",
            "phone": self.phone or "",
            "mobile": self.mobile or "",
            "website": self.website or "",
            "address_line": self.address_line or "",
            "city": self.city or "",
            "state": self.state or "",
            "postal_code": self.postal_code or "",
            "country": self.country or "",
            "tags": self.tags or "",
            "notes": self.notes or "",
        }

    def __repr__(self):
        return f"<AddressBookEntry {self.name}>"
