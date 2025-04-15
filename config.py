# config.py
import os
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('FLASK_SECRET_KEY') # Corrected variable name
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_SIZE', 500000000))
    DEBUG = True
    TESTING = False
    CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/0')
    CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/1') # Use a different DB for results


class DevelopmentConfig(Config):
    DEBUG = True

class ProductionConfig(Config):
    pass

# Select config based on environment
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': ProductionConfig
}