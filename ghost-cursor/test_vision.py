from dotenv import load_dotenv
load_dotenv()
from core.vision import query_vlm
result = query_vlm("Where is the terminal toggle button?")
print(result)
