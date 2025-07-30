from flask import current_app
from twilio.jwt.access_token import AccessToken
from twilio.jwt.access_token.grants import VoiceGrant
from twilio.rest import Client
from shrambandhu.config import Config

twilio_client = Client(Config.TWILIO_ACCOUNT_SID, Config.TWILIO_AUTH_TOKEN)

def get_twilio_token(user_identity):
    """Generate Twilio access token for voice"""
    token = AccessToken(
        Config.TWILIO_ACCOUNT_SID,
        Config.TWILIO_API_KEY,
        Config.TWILIO_API_SECRET,
        identity=user_identity
    )
    
    voice_grant = VoiceGrant(
        outgoing_application_sid=Config.TWILIO_TWIML_APP_SID,
        incoming_allow=True
    )
    token.add_grant(voice_grant)
    
    return token.to_jwt().decode('utf-8')

def create_room(room_name):
    """Create a Twilio video/audio room"""
    return twilio_client.video.rooms.create(
        unique_name=room_name,
        type='peer-to-peer',
        record_participants_connect=False
    )

def get_room_status(room_sid):
    """Check if room exists"""
    try:
        room = twilio_client.video.rooms(room_sid).fetch()
        return room.status
    except:
        return 'completed'