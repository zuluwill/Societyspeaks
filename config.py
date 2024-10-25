import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev')

    # Use DATABASE_URL from Replit's secrets if available, otherwise use a default
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL')

    # Add these settings for more stable connections
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
        'connect_args': {
            'connect_timeout': 10,
            'keepalives': 1,
            'keepalives_idle': 30,
            'keepalives_interval': 10,
            'keepalives_count': 5
        }
    }

    SQLALCHEMY_TRACK_MODIFICATIONS = False