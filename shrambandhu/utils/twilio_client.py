from twilio.rest import Client
from shrambandhu.config import Config

client = Client(Config.TWILIO_ACCOUNT_SID, Config.TWILIO_AUTH_TOKEN)

def send_whatsapp_message(to, body):
    message = client.messages.create(
        body=body,
        from_='whatsapp:' + Config.TWILIO_PHONE_NUMBER,
        to='whatsapp:' + to
    )
    print(f"Message SID: {message.sid}")  # Print SID for debugging
    return message.sid

def receive_whatsapp_message(request):
    from_number = request.form.get('From')
    message_body = request.form.get('Body')
    media_url = request.form.get('MediaUrl0')
    
    return {
        'from': from_number,
        'body': message_body,
        'media_url': media_url
    }


def send_sms(to, body):
    try:
        message = client.messages.create(
            body=body,
            from_=Config.TWILIO_PHONE_NUMBER,
            to=to
        )
        return message.sid
    except Exception as e:
        print(f"SMS sending failed: {str(e)}")
        return None    