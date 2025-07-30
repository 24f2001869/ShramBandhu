from flask import request, jsonify, session
from shrambandhu.extensions import db
from shrambandhu.utils.auth import login_required
from shrambandhu.utils.webrtc import get_twilio_token, create_room, get_room_status
from datetime import datetime
from shrambandhu.models import User, VoiceCall
import uuid
from . import chat_bp

@chat_bp.route('/token', methods=['GET'], endpoint='chat_token')
@login_required
def get_token():
    """Generate Twilio access token"""
    user = User.query.get(session['user_id'])
    token = get_twilio_token(f"user_{user.id}")
    return jsonify(token=token)

@chat_bp.route('/start-call', methods=['POST'], endpoint='chat_start_call')
@login_required
def start_call():
    """Initialize a voice call"""
    data = request.get_json()
    recipient_id = data.get('recipient_id')
    call_type = data.get('type', 'audio')  # audio/video
    
    if not recipient_id:
        return jsonify({'error': 'Recipient required'}), 400
    
    # Create unique room name
    room_name = f"call_{session['user_id']}_{recipient_id}_{uuid.uuid4().hex[:6]}"
    room = create_room(room_name)
    
    # Store call record (optional)
    call = VoiceCall(
        caller_id=session['user_id'],
        recipient_id=recipient_id,
        room_sid=room.sid,
        room_name=room_name,
        call_type=call_type,
        started_at=datetime.utcnow()
    )
    db.session.add(call)
    db.session.commit()
    
    return jsonify({
        'room_name': room_name,
        'room_sid': room.sid,
        'call_id': call.id
    })

@chat_bp.route('/call-status/<room_sid>', endpoint='chat_call_status')
@login_required
def call_status(room_sid):
    """Check call status"""
    status = get_room_status(room_sid)
    return jsonify(status=status)
