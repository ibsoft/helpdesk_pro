from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, create_access_token
from app.models.ticket import Ticket
from app.models.user import User
from app import db

api_bp = Blueprint('api', __name__)

@api_bp.route('/login', methods=['POST'])
def api_login():
    data = request.get_json()
    user = User.query.filter_by(username=data.get('username')).first()
    if user and user.check_password(data.get('password')):
        token = create_access_token(identity=user.username)
        return jsonify({'token': token})
    return jsonify({'error': 'Invalid credentials'}), 401

@api_bp.route('/tickets', methods=['GET'])
@jwt_required()
def api_get_tickets():
    tickets = Ticket.query.all()
    return jsonify([{'id': t.id, 'subject': t.subject, 'status': t.status} for t in tickets])
