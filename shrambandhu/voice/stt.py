from google.cloud import speech_v1p1beta1 as speech
import os
import os

def transcribe_audio(audio_file_path, language_code='hi-IN'):
    client = speech.SpeechClient.from_service_account_json(
        os.getenv('GOOGLE_APPLICATION_CREDENTIALS'))
    
    with open(audio_file_path, 'rb') as audio_file:
        content = audio_file.read()
    
    audio = speech.RecognitionAudio(content=content)
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.OGG_OPUS,
        sample_rate_hertz=16000,
        language_code=language_code,
        enable_automatic_punctuation=True,
    )
    
    response = client.recognize(config=config, audio=audio)
    
    transcript = ""
    for result in response.results:
        transcript += result.alternatives[0].transcript
    
    return transcript

def extract_worker_details(transcript):
    # NLP logic to extract name, skills, location etc.
    # This is simplified - you'd use a proper NLP library
    details = {
        'name': '',
        'skills': [],
        'location': '',
        'language': 'hi'
    }
    
    if 'नाम' in transcript:
        details['name'] = transcript.split('नाम')[1].split()[0]
    
    skill_keywords = {
        'मिस्त्री': 'masonry',
        'बढ़ई': 'carpentry',
        'प्लम्बर': 'plumbing'
    }
    
    for hindi, eng in skill_keywords.items():
        if hindi in transcript:
            details['skills'].append(eng)
    
    return details