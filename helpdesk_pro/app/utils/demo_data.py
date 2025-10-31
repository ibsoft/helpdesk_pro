from app import db
from app.models.user import User
from app.models.ticket import Ticket
from datetime import datetime

def init_demo_data():
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', email='admin@helpdesk.local', full_name='Demo Administrator', role='admin')
        admin.set_password('ChangeMe123!@')
        db.session.add(admin)
        db.session.commit()

    if not Ticket.query.first():
        demo_tickets = [
            Ticket(subject='Printer not working', description='Office printer error E05', priority='High', department='IT', created_by='admin'),
            Ticket(subject='Email not syncing', description='Outlook fails to sync inbox', priority='Medium', department='Support', created_by='admin'),
            Ticket(subject='VPN connection drops', description='Random disconnections during work', priority='Low', department='Network', created_by='admin')
        ]
        for t in demo_tickets:
            db.session.add(t)
        db.session.commit()
