import os
import base64
import json
from io import BytesIO

import pyautogui
import google.generativeai as genai
from PIL import Image, ImageDraw, ImageFont
from utils.logger import log
from core.app_detector import get_active_app

_client_configured = False

def _configure_client():
    global _client_configured
    if not _client_configured:
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        _client_configured = True

SYSTEM_PROMPT = """You are a UI Vision Agent for desktop applications with pixel-perfect accuracy.

Given a screenshot with a calibration grid overlay and a user query, locate the EXACT UI element they need.

CRITICAL INSTRUCTIONS:
- The screenshot includes a semi-transparent grid with coordinate labels every 100 pixels
- Use grid lines and coordinate labels to calibrate your estimates with extreme precision
- Identify the BOUNDING BOX of the element (top-left corner and bottom-right corner)
- Calculate the precise CENTER point of the bounding box
- Double-check coordinates against grid lines before responding
- Be exact: off by 1 pixel is wrong, off by 5 pixels is unacceptable

Response format (MUST BE EXACT):
{
  "x": <integer center x-coordinate>,
  "y": <integer center y-coordinate>,
  "x1": <integer top-left x>,
  "y1": <integer top-left y>,
  "x2": <integer bottom-right x>,
  "y2": <integer bottom-right y>,
  "element_name": "<concise name>",
  "confidence": <float 0.0-1.0>,
  "explanation": "<1-2 sentences>"
}

If not visible:
{"x": -1, "y": -1, "x1": -1, "y1": -1, "x2": -1, "y2": -1, "element_name": "not_found", "confidence": 0.0, "explanation": "Element not visible."}"""


def _load_app_profile(app_name: str) -> str:
    profiles = {
        "code": "vscode.txt",
        "premiere": "premiere_pro.txt",
        "photoshop": "photoshop.txt",
        "adobe premiere": "premiere_pro.txt",
    }
    for key, filename in profiles.items():
        if key in app_name:
            path = os.path.join("prompts", "profiles", filename)
            try:
                with open(path) as f:
                    return f.read().strip()
            except FileNotFoundError:
                log(f"Profile not found: {path}", level="WARNING")
    return ""


def capture_screenshot():
    """Returns Pillow Image of the primary screen."""
    return pyautogui.screenshot()


def add_grid_overlay(img: Image.Image, grid_spacing: int = 100) -> Image.Image:
    """
    Adds a semi-transparent calibration grid overlay to the screenshot.
    Grid lines and coordinate labels appear every `grid_spacing` pixels.
    
    Args:
        img: Pillow Image object (screenshot)
        grid_spacing: Pixel spacing between grid lines (default 100)
    
    Returns:
        New Image with grid overlay applied
    """
    # Create a copy to avoid modifying the original
    img_with_grid = img.copy()
    draw = ImageDraw.Draw(img_with_grid, "RGBA")
    
    width, height = img.size
    grid_color = (0, 255, 0, 80)  # Semi-transparent green
    text_color = (0, 255, 0, 200)  # Brighter green for text
    
    # Try to use a small default font; fall back if unavailable
    try:
        font = ImageFont.truetype("arial.ttf", 12)
    except:
        font = ImageFont.load_default()
    
    # Draw vertical lines and labels
    for x in range(0, width, grid_spacing):
        draw.line([(x, 0), (x, height)], fill=grid_color, width=1)
        # Draw coordinate label every 200 pixels to avoid clutter
        if x % 200 == 0:
            draw.text((x + 5, 5), str(x), fill=text_color, font=font)
    
    # Draw horizontal lines and labels
    for y in range(0, height, grid_spacing):
        draw.line([(0, y), (width, y)], fill=grid_color, width=1)
        # Draw coordinate label every 200 pixels to avoid clutter
        if y % 200 == 0:
            draw.text((5, y + 5), str(y), fill=text_color, font=font)
    
    log(f"Grid overlay applied | spacing={grid_spacing}px | resolution={width}x{height}")
    return img_with_grid


def get_zoomed_screenshot(center_x: int, center_y: int, zoom_width: int = 400, zoom_height: int = 400) -> tuple:
    """
    Captures a zoomed region around (center_x, center_y) with grid overlay.
    Returns: (zoomed_image, offset_x, offset_y, full_width, full_height)
    
    offset_x, offset_y: coordinates of zoomed region's top-left corner in full screen
    """
    full_img = pyautogui.screenshot()
    full_w, full_h = full_img.size
    
    # Calculate region bounds (centered on target)
    x1 = max(0, center_x - zoom_width // 2)
    y1 = max(0, center_y - zoom_height // 2)
    x2 = min(full_w, x1 + zoom_width)
    y2 = min(full_h, y1 + zoom_height)
    
    # Adjust if region hits screen edge
    if x2 - x1 < zoom_width:
        x1 = max(0, x2 - zoom_width)
    if y2 - y1 < zoom_height:
        y1 = max(0, y2 - zoom_height)
    
    # Crop and add grid
    zoomed = full_img.crop((x1, y1, x2, y2))
    zoomed = add_grid_overlay(zoomed, grid_spacing=50)  # Finer grid for zoom
    
    return zoomed, x1, y1, full_w, full_h


def detect_visual_center(img: Image.Image) -> tuple:
    """
    Uses edge detection to find the visual center of UI elements.
    Returns: (center_x, center_y) relative to image bounds.
    """
    try:
        import numpy as np
        from PIL import ImageFilter
        
        # Convert to grayscale and apply edge detection
        gray = img.convert("L")
        edges = gray.filter(ImageFilter.FIND_EDGES)
        
        # Convert to array for computation
        arr = np.array(edges)
        
        # Find non-zero edges
        if np.any(arr > 0):
            points = np.where(arr > 0)
            center_y = int(np.mean(points[0]))
            center_x = int(np.mean(points[1]))
            return center_x, center_y
        
        # Fallback: center of image
        w, h = img.size
        return w // 2, h // 2
    except Exception as e:
        log(f"Visual center detection failed: {e}", level="WARNING")
        w, h = img.size
        return w // 2, h // 2


def query_vlm(query: str) -> dict:
    """
    Sends screenshot + query to Gemini with multi-stage refinement.
    Returns dict: {x, y, element_name, explanation, confidence}
    
    For low-confidence results, performs zoomed refinement.
    """
    _configure_client()
    app_name = get_active_app()
    screen_w, screen_h = pyautogui.size()
    app_profile = _load_app_profile(app_name)

    user_content = (
        f"Screen resolution: {screen_w}x{screen_h}\n"
        f"Active application: {app_name}\n"
    )
    if app_profile:
        user_content += f"App context:\n{app_profile}\n"
    user_content += f"\nUser query: {query}"

    log(f"Querying VLM | app={app_name} | query='{query}'")

    img = capture_screenshot()
    img = add_grid_overlay(img, grid_spacing=100)

    model_name = os.getenv("VLM_MODEL", "gemini-2.5-flash")
    model = genai.GenerativeModel(
        model_name=model_name,
        system_instruction=SYSTEM_PROMPT
    )

    try:
        response = model.generate_content([user_content, img])
        raw = response.text.strip()
        
        if raw.startswith("```json"):
            raw = raw[7:]
        if raw.startswith("```"):
            raw = raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()

        log(f"VLM raw (stage 1): {raw}")
        result = json.loads(raw)
        
        # Calculate center from bounding box if provided
        if "x1" in result and "y1" in result and "x2" in result and "y2" in result:
            x1, y1, x2, y2 = result["x1"], result["y1"], result["x2"], result["y2"]
            if x1 >= 0 and y1 >= 0 and x2 > x1 and y2 > y1:
                calc_x = (x1 + x2) // 2
                calc_y = (y1 + y2) // 2
                result["x"] = calc_x
                result["y"] = calc_y
                log(f"Center calculated from bbox: ({calc_x}, {calc_y})")
        
        # Extract confidence (default to high if not provided)
        confidence = result.get("confidence", 0.8)
        
        # Stage 2: Zoomed refinement if confidence is low and element was found
        if confidence < 0.75 and result.get("x", -1) >= 0 and result.get("y", -1) >= 0:
            log(f"Low confidence ({confidence}), performing zoomed refinement...")
            
            zoom_img, offset_x, offset_y, _, _ = get_zoomed_screenshot(
                result["x"], result["y"], zoom_width=400, zoom_height=400
            )
            
            zoom_query = f"User query: {query}\nRefined query: Locate the exact center of the element. Use the grid to be precise."
            response2 = model.generate_content([zoom_query, zoom_img])
            raw2 = response2.text.strip()
            
            if raw2.startswith("```json"):
                raw2 = raw2[7:]
            if raw2.startswith("```"):
                raw2 = raw2[3:]
            if raw2.endswith("```"):
                raw2 = raw2[:-3]
            raw2 = raw2.strip()
            
            log(f"VLM raw (stage 2 - zoom): {raw2}")
            result2 = json.loads(raw2)
            
            # Convert zoomed coordinates back to full-screen coordinates
            if result2.get("x", -1) >= 0 and result2.get("y", -1) >= 0:
                refined_x = result2["x"] + offset_x
                refined_y = result2["y"] + offset_y
                result["x"] = refined_x
                result["y"] = refined_y
                result["confidence"] = result2.get("confidence", 0.95)
                log(f"Refined coordinates: ({refined_x}, {refined_y}) | confidence: {result['confidence']}")
        
        # Clamp to screen bounds
        result["x"] = max(0, min(int(result.get("x", -1)), screen_w - 1))
        result["y"] = max(0, min(int(result.get("y", -1)), screen_h - 1))
        result["confidence"] = confidence
        
        return result
    except Exception as e:
        log(f"VLM error: {e}", level="ERROR")
        return {
            "x": -1, "y": -1,
            "element_name": "error",
            "confidence": 0.0,
            "explanation": f"Failed to get or parse model response: {e}"
        }

