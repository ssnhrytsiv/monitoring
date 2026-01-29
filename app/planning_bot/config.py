import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()
load_dotenv(".env.local", override=True)

PLANNING_BOT_TOKEN = os.getenv("PLANNING_BOT_TOKEN", "")
