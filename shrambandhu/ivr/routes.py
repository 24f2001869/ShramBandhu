# shrambandhu/ivr/routes.py
from flask import Blueprint, request, Response, url_for, current_app
from twilio.twiml.voice_response import VoiceResponse, Gather, Record, Say # For generating TwiML
from shrambandhu.models import db, User
from shrambandhu.utils.twilio_client import send_sms # Optional: for sending confirmation SMS
from shrambandhu.voice.stt import transcribe_audio, extract_worker_details # Reuse transcription
import os
import tempfile
import requests # To download recording from Twilio
from datetime import datetime # Import datetime for timestamp usage

from . import ivr_bp # Import the blueprint defined in __init__.py

# --- Helper Function ---
def _get_base_url():
    # Helper to construct base URL for webhook callbacks if needed,
    # as url_for might not know the external domain within Twilio callback.
    # Best practice is to set this in config.
    # return current_app.config.get('BASE_URL', request.url_root)
    # For simplicity now, assume url_for works if SERVER_NAME is set in Flask config
    return url_for('index', _external=True).replace(url_for('index'), '') # Hacky way to get base

# --- Initial Call Handling ---
@ivr_bp.route("/welcome", methods=['GET', 'POST'])
def welcome():
    """Handles incoming calls."""
    resp = VoiceResponse()

    # Greet the caller and ask for language selection
    gather = Gather(num_digits=1, action=url_for('ivr.handle_language'), method='POST')
    gather.say("Welcome to Shram Bandhu.", language='en-IN')
    gather.say("Shram Bandhu mein aapka swagat hai.", language='hi-IN')
    gather.say("For English, press 1. Hindi ke liye, 2 dabayein.", language='en-IN')
    resp.append(gather)

    # If the user doesn't input anything, redirect back to welcome
    resp.redirect(url_for('ivr.welcome'))

    return Response(str(resp), mimetype='text/xml')

@ivr_bp.route("/handle-language", methods=['POST'])
def handle_language():
    """Handles language selection."""
    selected_language_digit = request.form.get('Digits')
    resp = VoiceResponse()

    if selected_language_digit == '1':
        language_code = 'en-IN'
        say_language = 'en-IN'
        lang_name = 'English'
    elif selected_language_digit == '2':
        language_code = 'hi-IN'
        say_language = 'hi-IN'
        lang_name = 'Hindi'
    else:
        resp.say("Sorry, invalid selection. Kripya sahi vikalp chunein.", language='hi-IN')
        resp.redirect(url_for('ivr.welcome'))
        return Response(str(resp), mimetype='text/xml')

    # Ask for action: Register or Login (Login is harder via IVR, focus on Register)
    gather = Gather(num_digits=1, action=url_for('ivr.handle_action', lang=language_code), method='POST') # Pass lang code
    if lang_name == 'English':
        gather.say(f"You selected {lang_name}. Press 1 to Register as a new worker. Press 2 for other options.", language=say_language) # Keep login vague for now
    else: # Hindi
         gather.say(f"Aapne {lang_name} chuna hai. Naye worker ke roop mein register karne ke liye 1 dabayein. Anya vikalpon ke liye 2 dabayein.", language=say_language)
    resp.append(gather)

    # Redirect if no input
    resp.redirect(url_for('ivr.handle_language', Digits=selected_language_digit)) # Redirect back to ask action again

    return Response(str(resp), mimetype='text/xml')

@ivr_bp.route("/handle-action", methods=['POST'])
def handle_action():
    """Handles main action selection (Register/Other)."""
    selected_action_digit = request.form.get('Digits')
    language_code = request.args.get('lang', 'en-IN') # Get lang from URL param
    say_language = 'hi-IN' if language_code == 'hi-IN' else 'en-IN'
    resp = VoiceResponse()

    if selected_action_digit == '1':
        # Start Registration - Ask for Phone Number
        gather = Gather(input='dtmf', finish_on_key='#', timeout=10, action=url_for('ivr.handle_phone', lang=language_code), method='POST')
        if say_language == 'en-IN':
            gather.say("Please enter your 10-digit mobile number, followed by the hash key.", language=say_language)
        else:
             gather.say("Kripya apna 10 ank ka mobile number darj karein, aur fir hash key dabayein.", language=say_language)
        resp.append(gather)
        # Redirect if no input - back to action selection? Or repeat prompt? Repeat for now.
        resp.redirect(url_for('ivr.handle_action', lang=language_code, Digits=selected_action_digit)) # Loop back
    elif selected_action_digit == '2':
        # Handle other options (e.g., login - complex, help, etc.) - Placeholder
        if say_language == 'en-IN':
             resp.say("Other options are currently not available via phone. Please visit our website. Goodbye.", language=say_language)
        else:
             resp.say("Anya vikalp abhi phone par uplabdh nahin hain. Kripya hamari website par jayein. Dhanyavaad.", language=say_language)
        resp.hangup()
    else:
        # Invalid input, repeat action prompt
        if say_language == 'en-IN': resp.say("Sorry, invalid selection.", language=say_language)
        else: resp.say("Maaf kijiye, galat vikalp.", language=say_language)
        resp.redirect(url_for('ivr.handle_language', Digits='1' if say_language == 'en-IN' else '2')) # Go back to asking action

    return Response(str(resp), mimetype='text/xml')

# --- Registration Flow ---
@ivr_bp.route("/register/handle-phone", methods=['POST'])
def handle_phone():
    """Handles entered phone number."""
    entered_phone = request.form.get('Digits')
    language_code = request.args.get('lang', 'en-IN')
    say_language = 'hi-IN' if language_code == 'hi-IN' else 'en-IN'
    resp = VoiceResponse()

    # Basic validation (e.g., length) - Needs better validation for Indian numbers
    if entered_phone and len(entered_phone) == 10:
        # Normalize phone (e.g., add +91)
        normalized_phone = "+91" + entered_phone

        # Check if phone already exists and is verified
        existing_user = User.query.filter_by(phone=normalized_phone, is_phone_verified=True).first()
        if existing_user:
            if say_language == 'en-IN': resp.say(f"This number, {entered_phone}, is already registered and verified. Please use the login option. Goodbye.", language=say_language)
            else: resp.say(f"Yeh number, {entered_phone}, pehle se register aur verify ho chuka hai. Kripya login vikalp ka upyog karein. Dhanyavaad.", language=say_language)
            resp.hangup()
        else:
            # Phone number seems new or unverified, proceed to ask for name
             if say_language == 'en-IN':
                resp.say("Thank you. Now, please say your full name after the beep, then press any key.", language=say_language)
             else:
                resp.say("Dhanyavaad. Ab, kripya beep ke baad apna poora naam kahein, fir koi bhi key dabayein.", language=say_language)

             # Record name - transcriptCallback sends transcription directly if provider supports it
             # Using recordingStatusCallback to get the recording URL
             resp.record(
                 action=url_for('ivr.handle_name_recording', lang=language_code, phone=normalized_phone), # Pass lang & phone
                 method='POST',
                 maxLength=15, # Max recording length in seconds
                 finishOnKey='*', # Use * key to finish recording (or any key)
                 playBeep=True,
                 recordingStatusCallback=url_for('ivr.handle_name_recording', lang=language_code, phone=normalized_phone), # Send recording URL here
                 recordingStatusCallbackMethod='POST',
                 recordingStatusCallbackEvent='completed' # Only when recording is done
             )
             # If recording fails or times out, maybe redirect to repeat the name prompt?
             # resp.say("Did not detect input.", language=say_language)
             # resp.redirect(url_for('ivr.handle_phone', lang=language_code, Digits=entered_phone))

    else:
        # Invalid phone number entered
        if say_language == 'en-IN': resp.say("Invalid phone number entered. Please enter a 10-digit number.", language=say_language)
        else: resp.say("Galat phone number darj kiya gaya hai. Kripya 10 ank ka number darj karein.", language=say_language)
        # Redirect back to ask for phone again
        resp.redirect(url_for('ivr.handle_action', lang=language_code, Digits='1')) # Back to start registration prompt

    return Response(str(resp), mimetype='text/xml')


@ivr_bp.route("/register/handle-name-recording", methods=['POST'])
def handle_name_recording():
    """Handles the recording of the user's name."""
    language_code = request.args.get('lang', 'en-IN')
    phone = request.args.get('phone')
    say_language = 'hi-IN' if language_code == 'hi-IN' else 'en-IN'
    resp = VoiceResponse()

    recording_url = request.form.get('RecordingUrl')
    recording_duration = request.form.get('RecordingDuration')

    if not recording_url or not recording_duration or int(recording_duration) < 1:
        # No recording received or too short
        if say_language == 'en-IN': resp.say("Sorry, I didn't catch your name. Please try again.", language=say_language)
        else: resp.say("Maaf kijiye, mujhe aapka naam samajh nahi aaya. Kripya fir se koshish karein.", language=say_language)
        # Redirect back to ask for name again (Need to re-trigger record from previous step logic)
        # This is tricky - ideally, the previous TwiML handles timeout/no-input
        # For now, just redirect back to ask for phone (simpler loop)
        resp.redirect(url_for('ivr.handle_action', lang=language_code, Digits='1'))
        return Response(str(resp), mimetype='text/xml')

    # --- Process Recording ---
    temp_filepath = None
    extracted_name = None
    try:
        # 1. Download the recording from Twilio URL
        audio_response = requests.get(recording_url, stream=True, timeout=15)
        audio_response.raise_for_status()

        # 2. Save to a temporary file
        temp_dir = tempfile.gettempdir()
        # Use a common extension like .wav if unsure, STT might handle it
        temp_filename = f"ivr_name_{phone.replace('+','')}_{int(datetime.utcnow().timestamp())}.wav"
        temp_filepath = os.path.join(temp_dir, temp_filename)
        with open(temp_filepath, 'wb') as f:
            for chunk in audio_response.iter_content(chunk_size=8192):
                f.write(chunk)
        current_app.logger.info(f"IVR Name Recording saved temporarily to: {temp_filepath}")

        # 3. Transcribe (Use appropriate language code)
        transcript = transcribe_audio(temp_filepath, language_code=language_code)
        current_app.logger.info(f"IVR Name Transcription for {phone}: {transcript}")

        # 4. Extract Name (This is highly simplified)
        details = extract_worker_details(transcript) # Reuse existing utility
        extracted_name = details.get('name')

        if not extracted_name:
             # Could use the whole transcript as name if extraction fails? Or ask again.
             current_app.logger.warning(f"Could not extract name for {phone} from transcript: '{transcript}'")
             extracted_name = transcript # Fallback: use full transcript? Risky.

    except Exception as e:
        current_app.logger.error(f"Error processing name recording for {phone}: {e}", exc_info=True)
        if say_language == 'en-IN': resp.say("Sorry, there was an error processing your name.", language=say_language)
        else: resp.say("Maaf kijiye, aapka naam process karne mein error hua.", language=say_language)
        resp.redirect(url_for('ivr.handle_action', lang=language_code, Digits='1')) # Go back
        # Clean up temp file on error
        if temp_filepath and os.path.exists(temp_filepath):
             try: os.remove(temp_filepath)
             except OSError: pass
        return Response(str(resp), mimetype='text/xml')
    finally:
        # Clean up temp file after processing
        if temp_filepath and os.path.exists(temp_filepath):
             try: os.remove(temp_filepath)
             except OSError: pass

    # --- Proceed to ask for skills ---
    if say_language == 'en-IN':
        resp.say(f"Thank you, {extracted_name}. Now, please tell me your skills after the beep, like 'masonry' or 'plumbing and electrical work'. Press any key when finished.", language=say_language)
    else:
        resp.say(f"Dhanyavaad, {extracted_name}. Ab, kripya beep ke baad apne skills batayein, jaise 'Mistri ka kaam' ya 'Plumbing aur Bijli ka kaam'. Bolne ke baad koi bhi key dabayein.", language=say_language)

    # Record skills
    # Pass phone AND extracted name to the next step's action URL
    next_action_url = url_for('ivr.handle_skills_recording', lang=language_code, phone=phone, name=extracted_name)
    resp.record(
         action=next_action_url,
         method='POST',
         maxLength=30, # Longer duration for skills
         finishOnKey='*',
         playBeep=True,
         recordingStatusCallback=next_action_url, # Send recording URL here
         recordingStatusCallbackMethod='POST',
         recordingStatusCallbackEvent='completed'
     )

    return Response(str(resp), mimetype='text/xml')


@ivr_bp.route("/register/handle-skills-recording", methods=['POST'])
def handle_skills_recording():
    """Handles the recording of the user's skills and completes registration."""
    language_code = request.args.get('lang', 'en-IN')
    phone = request.args.get('phone')
    name = request.args.get('name') # Get name passed from previous step
    say_language = 'hi-IN' if language_code == 'hi-IN' else 'en-IN'
    resp = VoiceResponse()

    recording_url = request.form.get('RecordingUrl')
    recording_duration = request.form.get('RecordingDuration')

    if not recording_url or not recording_duration or int(recording_duration) < 1:
        if say_language == 'en-IN': resp.say("Sorry, I didn't catch your skills. Registration cannot be completed.", language=say_language)
        else: resp.say("Maaf kijiye, mujhe aapke skills samajh nahi aaye. Registration poora nahi ho saka.", language=say_language)
        resp.hangup()
        return Response(str(resp), mimetype='text/xml')

    # --- Process Recording ---
    temp_filepath = None
    extracted_skills_list = []
    try:
        audio_response = requests.get(recording_url, stream=True, timeout=15)
        audio_response.raise_for_status()
        temp_dir = tempfile.gettempdir()
        temp_filename = f"ivr_skills_{phone.replace('+','')}_{int(datetime.utcnow().timestamp())}.wav"
        temp_filepath = os.path.join(temp_dir, temp_filename)
        with open(temp_filepath, 'wb') as f:
            for chunk in audio_response.iter_content(chunk_size=8192): f.write(chunk)
        current_app.logger.info(f"IVR Skills Recording saved temporarily to: {temp_filepath}")

        transcript = transcribe_audio(temp_filepath, language_code=language_code)
        current_app.logger.info(f"IVR Skills Transcription for {phone}: {transcript}")

        details = extract_worker_details(transcript) # Reuse utility
        extracted_skills_list = details.get('skills', [])

        if not extracted_skills_list:
            current_app.logger.warning(f"Could not extract skills for {phone} from transcript: '{transcript}'")
            # Maybe save the transcript itself if no skills keywords found?
            # extracted_skills_list = [transcript] # Use raw transcript?

    except Exception as e:
        current_app.logger.error(f"Error processing skills recording for {phone}: {e}", exc_info=True)
        if say_language == 'en-IN': resp.say("Sorry, there was an error processing your skills. Registration cannot be completed.", language=say_language)
        else: resp.say("Maaf kijiye, aapke skills process karne mein error hua. Registration poora nahi ho saka.", language=say_language)
        resp.hangup()
        # Clean up temp file
        if temp_filepath and os.path.exists(temp_filepath):
             try: os.remove(temp_filepath)
             except OSError: pass
        return Response(str(resp), mimetype='text/xml')
    finally:
        # Clean up temp file
        if temp_filepath and os.path.exists(temp_filepath):
             try: os.remove(temp_filepath)
             except OSError: pass

    # --- Create User Record ---
    try:
        # Check if user was somehow created between steps (unlikely but possible)
        user = User.query.filter_by(phone=phone).first()
        if not user:
             user = User(
                 phone=phone,
                 name=name, # Use name gathered earlier
                 role='worker',
                 language=say_language[:2], # Store 'en' or 'hi'
                 is_phone_verified=True, # Assume verified since they called from it? Risky.
                 is_email_verified=False, # No email via IVR
                 is_active=True
             )
             user.set_skills_list(extracted_skills_list) # Save extracted skills
             db.session.add(user)
             db.session.commit()
             current_app.logger.info(f"IVR Registration successful for user {phone}")
             if say_language == 'en-IN':
                 resp.say(f"Thank you, {name}. You have been successfully registered as a worker with skills: {', '.join(extracted_skills_list) if extracted_skills_list else 'Not specified'}. You can now use our website or app. Goodbye.", language=say_language)
             else:
                 resp.say(f"Dhanyavaad, {name}. Aap safaltapoorvak ek worker ke roop mein register ho gaye hain. Aapke skills hain: {', '.join(extracted_skills_list) if extracted_skills_list else 'Nahi bataya gaya'}. Ab aap hamari website ya app ka upyog kar sakte hain. Dhanyavaad.", language=say_language)

             # Optional: Send confirmation SMS
             # sms_message = f"Welcome to ShramBandhu! You are registered as a worker. Skills: {', '.join(extracted_skills_list) if extracted_skills_list else 'Not specified'}."
             # send_sms(phone, sms_message)

        else:
             # User already exists - maybe just update skills?
             current_app.logger.warning(f"User {phone} already existed during final IVR registration step.")
             if say_language == 'en-IN': resp.say("It seems you are already registered. Please use login options. Goodbye.", language=say_language)
             else: resp.say("Lagta hai aap pehle se hi register hain. Kripya login vikalpon ka upyog karein. Dhanyavaad.", language=say_language)

        resp.hangup()

    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error saving IVR registered user {phone}: {e}", exc_info=True)
        if say_language == 'en-IN': resp.say("Sorry, a database error occurred during final registration. Please try again later.", language=say_language)
        else: resp.say("Maaf kijiye, antim registration ke dauraan database mein error hua. Kripya baad mein fir se koshish karein.", language=say_language)
        resp.hangup()

    return Response(str(resp), mimetype='text/xml')