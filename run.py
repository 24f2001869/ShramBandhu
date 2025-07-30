# run.py (Updated to load .env explicitly)

import os
from dotenv import load_dotenv # Import the function

# Load environment variables from .env file BEFORE importing the app factory
dotenv_path = os.path.join(os.path.dirname(__file__), '.env') # Finds .env in the same directory as run.py
if os.path.exists(dotenv_path):
    print(f"Loading .env file from {dotenv_path}")
    load_dotenv(dotenv_path=dotenv_path)
else:
    print("Warning: .env file not found.")

# Now import create_app after environment variables are potentially loaded
from shrambandhu import create_app

# Get the configuration name from environment or default
config_name = os.getenv('FLASK_CONFIG', 'default')
app = create_app(config_name)

if __name__ == '__main__':
    # Debug will be controlled by FLASK_DEBUG env var or DevelopmentConfig
    app.run(host='0.0.0.0', port=5000)