import os

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'supersecretkey')
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL')  # Pull from Replit Secrets
    SQLALCHEMY_TRACK_MODIFICATIONS = False
