import os
import sys

# Add current dir to path to import app
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from app import generate_support_response
from dotenv import load_dotenv

load_dotenv()

# We depend on CEREBRAS_API_KEY from .env
# Wait, user revoked the key! I don't have a valid key to test with.
# Let's check how the fallback is triggered.
