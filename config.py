# config.py
import os
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv()

class Config:
    SECRET_KEY = os.environ.get('FLASK_SECRET_KEY', 'default-fallback-secret-key-change-me') # Added fallback
    MAX_CONTENT_LENGTH = int(os.environ.get('MAX_CONTENT_SIZE', 500 * 1024 * 1024)) # 500MB default limit
    DEBUG = False # Default to False for base config
    TESTING = False

    # Redis Config (Used directly by chunked_upload)
    REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')

    # Celery Config (Read from env, passed to Celery instance)
    CELERY_BROKER_URL = os.environ.get('CELERY_BROKER_URL', 'redis://localhost:6379/1')
    CELERY_RESULT_BACKEND = os.environ.get('CELERY_RESULT_BACKEND', 'redis://localhost:6379/2')

    # Cloudflare R2 (S3 Compatible) Config
    R2_ENDPOINT_URL = os.environ.get('R2_ENDPOINT_URL')
    R2_ACCESS_KEY_ID = os.environ.get('R2_ACCESS_KEY_ID')
    R2_SECRET_ACCESS_KEY = os.environ.get('R2_SECRET_ACCESS_KEY')
    R2_BUCKET_NAME = os.environ.get('R2_BUCKET_NAME')

    # Ensure critical R2/S3 settings are present for production
    @staticmethod
    def check_production_settings():
        if os.environ.get('FLASK_ENV') == 'production':
            if not all([
                Config.R2_ENDPOINT_URL,
                Config.R2_ACCESS_KEY_ID,
                Config.R2_SECRET_ACCESS_KEY,
                Config.R2_BUCKET_NAME
            ]):
                raise ValueError("Missing critical R2/S3 configuration for production environment!")
            if not Config.SECRET_KEY or Config.SECRET_KEY == 'default-fallback-secret-key-change-me':
                 raise ValueError("SECRET_KEY is not set or is using the default fallback in production!")


class DevelopmentConfig(Config):
    DEBUG = True

class ProductionConfig(Config):
    DEBUG = False # Ensure Debug is False for Production
    # Optional: Add production-specific checks or overrides here if needed
    pass # Check is handled in factory or WSGI entry

# Select config based on environment
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig # Default to Development for safety if FLASK_ENV not set
}

# Perform check when ProductionConfig is selected (can be done in create_app too)
# ProductionConfig.check_production_settings() # Or call this check within create_app for 'production'