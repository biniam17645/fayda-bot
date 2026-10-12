from google import genai
from google.genai import types
import json
import os
import re
import uuid
import logging
import time
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps, ImageChops
import cv2
from pyzbar import pyzbar
import numpy as np
from io import BytesIO

# Custom imports – only for rendering helpers
from main import generate_reversed_a4_layout, process_photo, safe_draw, draw_rotated_spaced_text, draw_spaced_text, get_next_sn, FONT_PATHS

logger = logging.getLogger(__name__)

# ========== GEMINI TEXT EXTRACTION ==========


def extract_data_with_gemini(front_path, back_path, max_retries=3):
    for attempt in range(max_retries):
        try:
            client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
            front_img = Image.open(front_path)
            back_img = Image.open(back_path)

            prompt = """
            You are an expert data extractor. Look at the two attached images of an Ethiopian Fayda ID (Front and Back).
            Extract the details and return them STRICTLY as a JSON object matching the keys below. 
            If a value is missing, return an empty string "". Correct obvious typos.
            
            For addresses, ensure both English and Amharic are populated. For example, if Region is "Oromia", region_am should be "ኦሮሚያ".
            For dates, Ethiopian dates look like DD/MM/YYYY, Gregorian look like YYYY/MMM/DD.
            Sex should be "Female" and "ሴት" OR "Male" and "ወንድ".

            JSON Keys required:
            "am_name", "en_name", "fcn", "fin", "phone", 
            "dob_am", "dob_en", "expiry_am", "expiry_en", "doi_am", "doi_en", 
            "sex_am", "sex_en", "region_en", "region_am", "zone_en", "zone_am", 
            "woreda_en", "woreda_am"
            """

            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=[prompt, front_img, back_img],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.0
                )
            )

            data = json.loads(response.text)

            # if data.get('doi_am') and "2026" in data['doi_am']:
            #     data['doi_am'] = data['doi_am'].replace("2026", "2018")
            # if data.get('expiry_am') and "2034" in data['expiry_am']:
            #     data['expiry_am'] = data['expiry_am'].replace("2034", "2026")
            # if not data.get('expiry_am') and data.get('expiry_en') and "2034" in data['expiry_en']:
            #     data['expiry_am'] = "25/08/2026"

            return data

        except Exception as e:
            logger.warning(
                f"Gemini attempt {attempt+1}/{max_retries} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
            else:
                raise Exception(
                    f"Gemini extraction failed after {max_retries} attempts: {e}")

    return {k: "" for k in ['am_name', 'en_name', 'fcn', 'fin', 'phone', 'dob_am', 'dob_en',
                            'expiry_am', 'expiry_en', 'doi_am', 'doi_en', 'sex_am', 'sex_en',
                            'region_en', 'region_am', 'zone_en', 'zone_am', 'woreda_en', 'woreda_am']}

# ========== FACE AND QR EXTRACTION (FROM CLOUD VISION VERSION - KEPT WORKING) ==========


def extract_face_photo(image_path, output_path):
    """Detects face and crops it with 20% expansion on all sides."""
    try:
        import io
        from google.cloud import vision

        # Use the API key from your working version
        vision_client = vision.ImageAnnotatorClient(
            client_options={'api_key': "AIzaSyB_NSK_9YsZt92JcJTcGSxzovcjJ-LKrg8"})

        with io.open(image_path, 'rb') as image_file:
            content = image_file.read()
        image = vision.Image(content=content)
        response = vision_client.face_detection(image=image)
        faces = response.face_annotations
        if not faces:
            return False
        face = faces[0]
        vertices = face.bounding_poly.vertices
        x_coords = [v.x for v in vertices]
        y_coords = [v.y for v in vertices]
        left, top, right, bottom = min(x_coords), min(
            y_coords), max(x_coords), max(y_coords)
        width, height = right - left, bottom - top
        ex, ey = int(width * 0.20), int(height * 0.20)
        img = Image.open(image_path).convert("RGBA")
        iw, ih = img.size
        photo_crop = img.crop(
            (max(0, left-ex), max(0, top-ey), min(iw, right+ex), min(ih, bottom+ey)))
        photo_crop.save(output_path)
        return True
    except Exception as e:
        logger.error(f"Face crop error: {e}")
        return False


def extract_qr_code(image_path, output_path):
    """Detects and crops QR code using pyzbar and OpenCV."""
    try:
        img_cv = cv2.imread(image_path)
        barcodes = pyzbar.decode(img_cv)
        if not barcodes:
            return False
        rect = barcodes[0].rect
        img_pil = Image.open(image_path).convert("RGBA")
        qr_crop = img_pil.crop(
            (rect.left, rect.top, rect.left + rect.width, rect.top + rect.height))
        qr_crop.save(output_path)
        return True
    except:
        return False

# ========== MAIN EXTRACTION ==========


def get_screenshot_data(front_path, back_path):
    data = extract_data_with_gemini(front_path, back_path)

    # ========== OVERRIDE DOI AND EXPIRY WITH CURRENT DATE BASED CALCULATION ==========
    from datetime import datetime, timedelta

    # Get current date
    now = datetime.now()

    # DOI (Date of Issue) - Current date
    # Ethiopian format: DD/MM/YYYY
    data["doi_am"] = now.strftime("%d/%m/%Y")
    # Gregorian format: YYYY/MMM/DD
    data["doi_en"] = now.strftime("%Y/%b/%d")

    # Expiry Date - Current date + 8 years - 2 days
    expiry_date = now + timedelta(days=(8 * 365) - 2)
    data["expiry_am"] = expiry_date.strftime("%d/%m/%Y")
    data["expiry_en"] = expiry_date.strftime("%Y/%b/%d")

    print(
        f"📅 Dates calculated from current date: DOI={data['doi_am']} | Expiry={data['expiry_am']}")

    # Presets
    if data.get('woreda_en', '').strip().lower() == "kersa":
        data['woreda_am'] = "ቀርሳ"

    # ... rest of the function remains unchanged ...

    # Presets
    if data.get('woreda_en', '').strip().lower() == "kersa":
        data['woreda_am'] = "ቀርሳ"

    request_id = str(uuid.uuid4())[:8]
    photo_path = os.path.join("output", f"photo_{request_id}.png")
    qr_path = os.path.join("output", f"qr_{request_id}.png")
    data["photo_path"] = photo_path
    data["qr_path"] = qr_path
    data["temp_path"] = None

    if not extract_face_photo(front_path, photo_path):
        try:
            img = Image.open(front_path)
            w, h = img.size
            img.crop((int(w*0.6), int(h*0.1), int(w*0.95),
                     int(h*0.45))).save(photo_path)
        except Exception as e:
            logger.error(f"Manual photo crop failed: {e}")

    if not extract_qr_code(back_path, qr_path):
        try:
            img = Image.open(back_path)
            w, h = img.size
            img.crop((int(w*0.7), int(h*0.05), w-50, int(h*0.55))).save(qr_path)
        except Exception as e:
            logger.error(f"Manual QR crop failed: {e}")

    print("\n" + "="*50)
    print("📋 GEMINI PARSED DATA SUMMARY")
    print("="*50)
    for k, v in data.items():
        if v and k not in ["photo_path", "qr_path"]:
            print(f"{k}: {v}")
    print("="*50 + "\n")

    return data

# ========== RENDERING (FROM YOUR WORKING CLOUD VISION VERSION) ==========


def render_screenshot_id(data, template_path, color_mode="color"):
    """Dedicated rendering for Screenshot data with fixed sex positioning."""
    canvas = Image.open(template_path).convert("RGBA")
    draw = ImageDraw.Draw(canvas)
    x_f, x_back = 487, 1385
    MAX_W_F, MAX_W_B = 450, 400

    # Extract template name from path
    template_name = os.path.basename(template_path)

    # Fonts - using your exact font names
    f_hawariat = ImageFont.truetype(FONT_PATHS["hawariat"], 22)
    f_nokia = ImageFont.truetype(FONT_PATHS["nokia"], 30)
    f_nokia_small = ImageFont.truetype(FONT_PATHS["nokia"], 18)
    f_nokia_medium = ImageFont.truetype(FONT_PATHS["nokia"], 26)
    f_nokia_large = ImageFont.truetype(FONT_PATHS["nokia"], 27)
    f_addr = ImageFont.truetype(FONT_PATHS["nokia"], 26)
    f_sn = ImageFont.truetype(FONT_PATHS["nokia"], 24)
    f_hawariat_small = ImageFont.truetype(FONT_PATHS["hawariat"], 18)
    f_addr_small = ImageFont.truetype(FONT_PATHS["nokia"], 20)

    # Check if template uses modern style (temp2 or temp3)
    use_modern_style = "temp2" in template_name or "temp3" in template_name

    # 1. Photos - Pass template_name to process_photo
    if data.get("photo_path") and os.path.exists(data["photo_path"]):
        # Large photo
        large = process_photo(data["photo_path"],
                              (330, 450), 18, template_name)
        if large:
            if use_modern_style:
                # Template 2/3: Left-aligned at x=140
                canvas.paste(large, (140, 130), large)
            else:
                # Template 1: Center horizontally
                canvas.paste(
                    large, (140 + (330 - large.width) // 2, 130), large)

        # Small photo
        small = process_photo(data["photo_path"], (80, 105), 8, template_name)
        if small:
            if use_modern_style:
                # Template 2/3: Left-aligned at x=940
                canvas.paste(small, (940, 475), small)
            else:
                # Template 1: Center horizontally
                canvas.paste(
                    small, (940 + (80 - small.width) // 2, 475), small)

    # 2. Front Data
    if data.get('am_name'):
        safe_draw(draw, (x_f, 185), data['am_name'],
                  f_hawariat, max_width=MAX_W_F)
    if data.get('en_name'):
        safe_draw(draw, (x_f, 213),
                  data['en_name'], f_nokia, max_width=MAX_W_F)

    if data.get('dob_am') or data.get('dob_en'):
        dob_text = f"{data.get('dob_am', '')} | {data.get('dob_en', '')}".strip(
            ' |')
        safe_draw(draw, (x_f, 301), dob_text, f_nokia)

    if data.get('doi_am'):
        draw_rotated_spaced_text(
            canvas, (92, 405), data['doi_am'], f_nokia_small, angle=90, spacing=3)
    if data.get('doi_en'):
        draw_rotated_spaced_text(
            canvas, (92, 130), data['doi_en'], f_nokia_small, angle=90, spacing=3)

    if data.get('sex_am') and data.get('sex_en'):
        safe_draw(draw, (x_f, 410), data['sex_am'], f_hawariat, anchor="ls")
        am_width = draw.textlength(data['sex_am'], font=f_hawariat)
        safe_draw(draw, (x_f + am_width + 5, 406),
                  f"| {data['sex_en']}", f_nokia, anchor="ls")
    elif data.get('sex_am'):
        safe_draw(draw, (x_f, 410), data['sex_am'], f_hawariat, anchor="ls")
    elif data.get('sex_en'):
        safe_draw(draw, (x_f, 410), data['sex_en'], f_nokia, anchor="ls")

    if data.get('expiry_am') or data.get('expiry_en'):
        expiry_text = f"{data.get('expiry_am', '')} | {data.get('expiry_en', '')}".strip(
            ' |')
        safe_draw(draw, (x_f, 488), expiry_text, f_nokia, anchor="ls")

    fcn_y = 506 if use_modern_style else 516
    if data.get('fcn'):
        fcn_s = " ".join(re.findall(r'.{1,4}', data['fcn']))
        draw_spaced_text(canvas, (x_f + 70, fcn_y),
                         fcn_s, f_nokia_medium, spacing=2)

    # 3. Back Data
    if data.get('phone'):
        safe_draw(draw, (x_back, 75), data['phone'], f_nokia)

    if data.get('region_am'):
        safe_draw(draw, (x_back, 255),
                  data['region_am'], f_hawariat, fill="#000000", max_width=MAX_W_B)
    if data.get('region_en'):
        safe_draw(draw, (x_back, 280),
                  data['region_en'], f_addr, fill="#000000", max_width=MAX_W_B)

    if data.get('zone_am'):
        zone_font = f_hawariat_small if len(
            data['zone_am']) > 23 else f_hawariat
        safe_draw(draw, (x_back, 340),
                  data['zone_am'], zone_font, fill="#000000", max_width=MAX_W_B)
    if data.get('zone_en'):
        zone_en_font = f_addr_small if len(data['zone_en']) > 30 else f_addr
        safe_draw(draw, (x_back, 365),
                  data['zone_en'], zone_en_font, fill="#000000", max_width=MAX_W_B)

    if data.get('woreda_am'):
        safe_draw(draw, (x_back, 425),
                  data['woreda_am'], f_hawariat, fill="#000000", max_width=MAX_W_B)
    if data.get('woreda_en'):
        safe_draw(draw, (x_back, 450),
                  data['woreda_en'], f_addr, fill="#000000", max_width=MAX_W_B)

    if data.get('fin'):
        fin_s = " ".join(re.findall(r'.{1,4}', data['fin']))
        safe_draw(draw, (1516, 545), fin_s, f_nokia_large)

    safe_draw(draw, (2247, 610), f"{get_next_sn()}", f_sn, fill="#000000")

    # 4. QR Code
    if data.get("qr_path") and os.path.exists(data["qr_path"]):
        try:
            qr = Image.open(data["qr_path"]).convert(
                "RGBA").resize((515, 515), Image.Resampling.LANCZOS)
            canvas.paste(qr, (1815, 52), qr)
        except Exception as e:
            print(f"Error pasting QR code: {e}")

    # Use English name for filename
    name = data.get('en_name', '').strip()
    if name:
        safe_name = re.sub(r'[^\w\s-]', '', name).strip()
        safe_name = re.sub(r'[-\s]+', '_', safe_name)
        filename = f"{safe_name}.png"
    else:
        filename = f"ID_{data.get('fcn', uuid.uuid4().hex[:8])}.png"

    out = os.path.join("output", filename)
    canvas.convert("RGB").save(out, quality=100)
    print(f"✅ ID card saved: {out}\n")
    return out

# ========== WORKFLOW ENTRY POINT ==========


def process_screenshot_workflow(front_path, back_path, template_path=None, color_mode="color"):
    """Entry point for the bot."""
    if not template_path:
        template_path = "templates/temp1.jpg"

    # Ensure output directory exists
    os.makedirs("output", exist_ok=True)

    data = get_screenshot_data(front_path, back_path)
    output_path = render_screenshot_id(data, template_path)
    a4_path = generate_reversed_a4_layout(output_path)
    return data, output_path, a4_path
