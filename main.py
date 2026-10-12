import uuid
import os
import re
import fitz
import pytesseract
import textwrap
from io import BytesIO
from rembg import remove, new_session
import numpy as np
import json
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageOps, ImageChops

# --- 1. SETUP ---
output_folder = "output"
template_img_path = "templates/temp1.png"
os.makedirs(output_folder, exist_ok=True)

FONT_PATHS = {
    "hawariat": "fonts/AbnetZeHawariat-Bold.ttf",
    "nokia":    "fonts/nokiapureheadline_bold.otf"
}

# --- 2. UTILITIES ---


_rembg_session = None


def get_rembg_session():
    global _rembg_session
    if _rembg_session is None:
        # Use 'isnet-general-use' for better edge detection on people/faces
        # Other options: 'u2net', 'u2netp', 'silueta', 'isnet-anime'
        _rembg_session = new_session('isnet-general-use')
    return _rembg_session


def remove_background(input_path):
    if not os.path.exists(input_path):
        return None
    try:
        with open(input_path, 'rb') as i:
            input_data = i.read()
            session = get_rembg_session()
            output_data = remove(input_data, session=session)
        if isinstance(output_data, bytes):
            img = Image.open(BytesIO(output_data)).convert("RGBA")
            return img
        return None
    except Exception as e:
        print(f"Error removing background: {e}")
        return None


def draw_wrapped_text(draw, pos, text, font, max_width, fill="#000000", anchor=None, spacing=4):
    if not text or str(text).strip() == "":
        return
    text = str(text)
    avg_char_width = font.getlength("a") if hasattr(font, 'getlength') else 15
    width_in_chars = int(max_width / avg_char_width)
    lines = textwrap.wrap(text, width=max(1, width_in_chars))
    current_y = pos[1]
    for line in lines:
        draw.text((pos[0], current_y), line,
                  font=font, fill=fill, anchor=anchor)
        bbox = font.getbbox(line)
        line_height = bbox[3] - bbox[1]
        current_y += line_height + spacing


def safe_draw(draw, pos, text, font, fill="#000000", anchor=None, max_width=None):
    if not text or str(text).strip() == "":
        return
    try:
        if max_width:
            draw_wrapped_text(draw, pos, text, font, max_width, fill, anchor)
        else:
            draw.text(pos, str(text), font=font, fill=fill, anchor=anchor)
    except OSError:
        pass


def process_photo(photo_path, target_size, feather_radius=15, template_name="temp1.jpg", color_mode="color"):
    """Process photo – modern style for temp2/temp3, oval+blur for temp1, with colour/greyscale support"""
    if not os.path.exists(photo_path):
        return None

    photo = remove_background(photo_path)
    if photo is None:
        photo = Image.open(photo_path).convert("RGBA")

    # Check if greyscale mode is requested
    is_greyscale = (color_mode == "grey")

    # Convert to greyscale if needed (but keep alpha channel)
    if is_greyscale:
        r, g, b, alpha = photo.split()
        photo_gray = ImageOps.grayscale(photo).convert("L")
        photo = Image.merge(
            "RGBA", (photo_gray, photo_gray, photo_gray, alpha))
    else:
        # Color mode: normal processing
        pass

    # Resize
    w, h = target_size
    photo = photo.resize((w, h), Image.Resampling.LANCZOS)

    # Mask based on template
    if "temp2" in template_name or "temp3" in template_name:
        upscale_factor = 4
        mask_w, mask_h = w * upscale_factor, h * upscale_factor
        mask = Image.new("L", (mask_w, mask_h), 0)
        m_draw = ImageDraw.Draw(mask)
        base_radius = 32 if h > 200 else 12
        smooth_radius = base_radius * upscale_factor
        m_draw.rounded_rectangle(
            (0, 0, mask_w, mask_h), radius=smooth_radius, fill=255)
        m_draw.rectangle((0, 0, mask_w, mask_h // 2),
                         fill=255)   # keep top square
        mask = mask.resize((w, h), Image.Resampling.LANCZOS)
        final_alpha = ImageChops.multiply(photo.split()[3], mask)
        photo.putalpha(final_alpha)
        return photo.crop((0, 0, w, h - 3))
    else:
        # Original oval + blur + gradient
        mask = Image.new("L", (w, h), 0)
        m_draw = ImageDraw.Draw(mask)
        m_draw.ellipse((0, 0, w, h), fill=255)
        gradient = Image.new('L', (w, h), 255)
        fade_start = int(h * 0.85)
        for y in range(fade_start, h):
            alpha_val = int(255 * (1 - (y - fade_start) / (h - fade_start)))
            for x in range(w):
                gradient.putpixel((x, y), alpha_val)
        mask = ImageChops.multiply(mask, gradient)
        final_mask = mask.filter(
            ImageFilter.GaussianBlur(radius=feather_radius))
        photo.putalpha(ImageChops.multiply(photo.split()[3], final_mask))
        return photo


def get_next_sn(filename="sn_counter.txt", initial_val=8929587):
    if not os.path.exists(filename):
        with open(filename, "w") as f:
            f.write(str(initial_val))
        return initial_val
    with open(filename, "r") as f:
        try:
            current_sn = int(f.read().strip())
        except ValueError:
            current_sn = initial_val
    next_sn = current_sn + 1
    with open(filename, "w") as f:
        f.write(str(next_sn))
    return current_sn

# --- 3. EXTRACTION ENGINE (Tesseract‑based, original) ---


def get_pdf_data(pdf_path):
    request_id = str(uuid.uuid4())[:8]

    doc = fitz.open(pdf_path)
    page = doc.load_page(0)
    pix = page.get_pixmap(dpi=300)

    temp_path = os.path.join(output_folder, f"temp_{request_id}.png")
    raw_photo_path = os.path.join(output_folder, f"raw_{request_id}.png")
    qr_path = os.path.join(output_folder, f"qr_{request_id}.png")

    pix.save(temp_path)
    temp_img = Image.open(temp_path)

    data = {k: "" for k in [
        "am_name", "en_name", "dob_am", "dob_en", "sex_am", "sex_en",
        "expiry_am", "expiry_en", "doi_am", "doi_en", "fcn", "fin", "phone",
        "region_am", "region_en", "zone_am", "zone_en", "woreda_am", "woreda_en"
    ]}

    data["photo_path"] = raw_photo_path
    data["qr_path"] = qr_path
    data["temp_path"] = temp_path

    # Photo crop (fixed coordinates)
    temp_img.crop((222, 416, 581, 908)).save(raw_photo_path)

    # QR Code crop (EXPANDED by 15 pixels in all directions)
    qr_left = 477 - 15
    qr_top = 1729 - 15
    qr_right = 477 + 645 + 15
    qr_bottom = 1729 + 643 + 15
    temp_img.crop((qr_left, qr_top, qr_right, qr_bottom)).save(qr_path)

    # ========== EXACT COORDINATE-BASED EXTRACTION FROM inspect_layout.py ==========
    pdf_page = doc.load_page(0)

    # Static coordinate boxes (EXACTLY as in inspect_layout.py)
    name_rect = fitz.Rect(170, 215, 360, 245)
    region_rect = fitz.Rect(200, 281, 360, 305)
    sex_rect = fitz.Rect(55, 312, 160, 337)
    zone_rect = fitz.Rect(200, 312, 360, 342)
    woreda_rect = fitz.Rect(200, 342, 360, 370)
    phone_rect = fitz.Rect(55, 377, 160, 395)

    # Horizontal clean extractor (EXACTLY as in inspect_layout.py)
    def get_clean_values(rect):
        raw_text = pdf_page.get_text("text", clip=rect)
        lines = []
        system_labels = ["perso", "disclaim",
                         "only", "ማሳሰቢያ", "demographic", "data"]
        for line in raw_text.split("\n"):
            clean = line.strip()
            if not clean:
                continue
            if clean in ["ወረዳ", "ዞን", "ክልል", "ጾታ", "ፆታ", "ዜግነት", "Zone", "Woreda", "Region", "SEX", "Sex", "ስልክ", "Phone", "Number"]:
                continue
            if any(sys_label in clean.lower() for sys_label in system_labels):
                continue
            if "subcity" in clean.lower() or "woreda" in clean.lower() or "ክፍለ" in clean:
                if "ከተማ አስተዳደር" in clean or "administration" in clean.lower():
                    pass
                else:
                    continue
            if not any(c.isalnum() or '\u1200' <= c <= '\u137F' for c in clean):
                continue
            lines.append(clean)
        return lines

    # Extract Fields using exact inspect_layout.py method
    name_lines = get_clean_values(name_rect)
    data["am_name"] = name_lines[0] if len(name_lines) > 0 else ""
    data["en_name"] = name_lines[1] if len(name_lines) > 1 else ""

    region_lines = get_clean_values(region_rect)
    data["region_am"] = region_lines[0] if len(region_lines) > 0 else ""
    data["region_en"] = region_lines[1] if len(region_lines) > 1 else ""

    sex_lines = get_clean_values(sex_rect)
    data["sex_am"] = sex_lines[0] if len(sex_lines) > 0 else ""
    data["sex_en"] = sex_lines[1] if len(sex_lines) > 1 else ""

    zone_lines = get_clean_values(zone_rect)
    data["zone_am"] = zone_lines[0] if len(zone_lines) > 0 else ""
    data["zone_en"] = zone_lines[1] if len(zone_lines) > 1 else ""

    woreda_lines = get_clean_values(woreda_rect)
    data["woreda_am"] = woreda_lines[0] if len(woreda_lines) > 0 else ""
    data["woreda_en"] = woreda_lines[1] if len(woreda_lines) > 1 else ""

    phone_lines = get_clean_values(phone_rect)
    data["phone"] = phone_lines[0] if len(phone_lines) > 0 else ""

    print(f"DEBUG - Name lines: {name_lines}")
    print(f"DEBUG - Region lines: {region_lines}")
    print(f"DEBUG - Sex lines: {sex_lines}")
    print(f"DEBUG - Zone lines: {zone_lines}")
    print(f"DEBUG - Woreda lines: {woreda_lines}")
    print(f"DEBUG - Phone lines: {phone_lines}")

    # ========== TESSERACT EXTRACTION FOR REMAINING FIELDS ==========
    def clean_ocr_text(crop, lang='eng', is_fcn=False):
        gray = crop.convert('L')
        threshold = 130
        binary = gray.point(lambda p: p > threshold and 255)
        denoised = binary.filter(ImageFilter.MedianFilter(size=3))
        big = denoised.resize(
            (denoised.width * 3, denoised.height * 3), Image.Resampling.LANCZOS)
        config = '--psm 7'
        if is_fcn:
            config += ' digits'
        raw_text = pytesseract.image_to_string(
            big, lang=lang, config=config).strip()
        artifacts = ['-', '_', '=', ':', ';', '!',
                     '?', '.', ',', '«', '»', '*', '“', '”']
        for char in artifacts:
            raw_text = raw_text.replace(char, ' ')
        return " ".join(raw_text.split())

    # # --- DOI (rotated) ---
    # doi_crop = temp_img.crop((2210, 520, 2290, 1050)).rotate(270, expand=True)
    # doi_raw = pytesseract.image_to_string(doi_crop, lang='eng').strip()

    # if "|" in doi_raw:
    #     parts = doi_raw.split("|")
    #     if len(parts) >= 2:
    #         am_digits = "".join(re.findall(r'[\d/]+', parts[0]))
    #         if am_digits:
    #             data["doi_am"] = re.sub(
    #                 r'^[^2]*', '', am_digits).replace("204", "201")
    #         en_text = "".join(re.findall(r'[\d/A-Za-z]+', parts[1]))
    #         if en_text:
    #             data["doi_en"] = re.sub(r'^[^2]*', '', en_text)
    # else:
    #     date_match = re.search(
    #         r'(\d{4}/\d{2}/\d{2})\s+(\d{4}/[A-Za-z]+/\d{2})', doi_raw)
    #     if date_match:
    #         data["doi_am"] = date_match.group(1).replace(
    #             "2026", "2018") if "2026" in date_match.group(1) else date_match.group(1)
    #         data["doi_en"] = date_match.group(2)
    # ========== ADD NEW DATE CALCULATION (Current Date Based) ==========
    from datetime import datetime, timedelta

    # Get current date
    now = datetime.now()

    # DOI (Date of Issue) - Current date
    # Ethiopian format: DD/MM/YYYY
    data["doi_am"] = now.strftime("%d/%m/%Y")
    # Gregorian format: YYYY/MMM/DD
    data["doi_en"] = now.strftime("%Y/%b/%d")

    # DOE (Expiry Date) - Current date + 8 years - 2 days
    # Approximate 8 years minus 2 days
    expiry_date = now + timedelta(days=(8 * 365) - 2)
    data["expiry_am"] = expiry_date.strftime("%d/%m/%Y")
    data["expiry_en"] = expiry_date.strftime("%Y/%b/%d")

    print(
        f"📅 Dates calculated from current date: DOI={data['doi_am']} | Expiry={data['expiry_am']}")

    # --- FCN ---
    fcn_crop = temp_img.crop((1825, 1200, 2260, 1245))
    fcn_raw = pytesseract.image_to_string(fcn_crop, config='--psm 7 digits')
    data["fcn"] = "".join(re.findall(r'\d+', fcn_raw))

    # --- FIN ---
    fin_crop = temp_img.crop((2067, 2046, 2350, 2120))
    fin_raw = pytesseract.image_to_string(fin_crop, config='--psm 7 digits')
    data["fin"] = "".join(re.findall(r'\d+', fin_raw))

    # --- Demographics (DOB, expiry) ---
    dem_crop = temp_img.crop((1700, 850, 2200, 1400))
    lines = pytesseract.image_to_string(dem_crop, lang='amh+eng').split('\n')
    date_lines = [l for l in lines if "/" in l and "|" in l]
    if len(date_lines) >= 2:
        d_p = date_lines[0].split('|')
        data["dob_am"], data["dob_en"] = d_p[0].strip(), d_p[1].strip()
        # e_p = date_lines[1].split('|')
        # data["expiry_am"], data["expiry_en"] = e_p[0].strip(), e_p[1].strip()

    # --- Normalize English name for comparison ---
    if data["en_name"]:
        data["en_name"] = " ".join(data["en_name"].split())

    # --- English name preset: Gali Abadura Abawaji -> specific DOI ---
    if data["en_name"] == "Gali Abadura Abawaji":
        data["doi_am"] = "17/09/2018"
        data["doi_en"] = "2026/May/25"

    doc.close()

    print("\n" + "="*50)
    print("📋 EXTRACTED ID DATA (from PDF)")
    print("="*50)
    for key, value in data.items():
        if value and key not in ["photo_path", "qr_path", "temp_path"]:
            print(f"{key}: {value}")
    print("="*50 + "\n")

    return data
# --- 4. RENDERING FUNCTIONS ---


def draw_rotated_spaced_text(canvas, pos, text, font, fill="#000000", angle=90, spacing=5):
    if not text or str(text).strip() == "":
        return
    chars = list(str(text))
    total_w = sum([font.getlength(c) for c in chars]) + \
        (len(chars) - 1) * spacing
    bbox = font.getbbox("Ay")
    h = bbox[3] - bbox[1]
    txt_img = Image.new(
        'RGBA', (int(total_w) + 20, h + 20), (255, 255, 255, 0))
    txt_draw = ImageDraw.Draw(txt_img)
    current_x = 10
    for char in chars:
        txt_draw.text((current_x, 10), char, font=font, fill=fill)
        current_x += font.getlength(char) + spacing
    rotated = txt_img.rotate(angle, expand=True)
    canvas.paste(rotated, pos, rotated)


def draw_spaced_text(canvas, pos, text, font, fill="#000000", spacing=5, angle=0):
    if not text or str(text).strip() == "":
        return
    chars = list(str(text))
    total_w = sum([font.getlength(c) for c in chars]) + \
        (len(chars) - 1) * spacing
    bbox = font.getbbox("Ay")
    h = bbox[3] - bbox[1]
    txt_img = Image.new(
        'RGBA', (int(total_w) + 20, h + 20), (255, 255, 255, 0))
    txt_draw = ImageDraw.Draw(txt_img)
    current_x = 10
    for char in chars:
        txt_draw.text((current_x, 10), char, font=font, fill=fill)
        current_x += font.getlength(char) + spacing
    rotated = txt_img.rotate(angle, expand=True)
    canvas.paste(rotated, pos, rotated)


def generate_reversed_a4_layout(combined_id_path, output_subfolder="print_ready", dpi=300):
    """Clean A4 print layout with mirrored ID at top - no crop marks, no bleed lines"""
    if not os.path.exists(combined_id_path):
        print(f"Error: Source ID file not found at {combined_id_path}")
        return None

    print(">>> LOG: Generating reversed A4 print layout...", flush=True)

    a4_size = (2480, 3508)
    margin_left = 100
    margin_right = 100
    margin_top = 1
    printable_width = a4_size[0] - margin_left - margin_right
    print_output_folder = os.path.join(output_folder, output_subfolder)
    os.makedirs(print_output_folder, exist_ok=True)

    id_img = Image.open(combined_id_path).convert("RGBA")
    reversed_id_img = id_img.transpose(Image.FLIP_LEFT_RIGHT)

    id_width, id_height = reversed_id_img.size
    scale_width = printable_width / id_width
    if scale_width < 1:
        new_width = int(id_width * scale_width)
        new_height = int(id_height * scale_width)
        reversed_id_img = reversed_id_img.resize(
            (new_width, new_height), Image.Resampling.LANCZOS)
        id_width, id_height = new_width, new_height

    a4_sheet = Image.new("RGB", a4_size, "white")
    paste_x = margin_left + (printable_width - id_width) // 2
    paste_y = margin_top
    a4_sheet.paste(reversed_id_img, (paste_x, paste_y), reversed_id_img)

    combined_filename = os.path.basename(combined_id_path)
    base_name = os.path.splitext(combined_filename)[0]
    final_filename = f"PRINT_A4_{base_name}.png"
    a4_out_path = os.path.join(print_output_folder, final_filename)

    a4_sheet.save(a4_out_path, format="PNG", dpi=(dpi, dpi), quality=95)
    print(f"✅ A4 print layout saved: {a4_out_path}")
    return a4_out_path


def render_id(data, template_path=None, color_mode="color"):
    if not template_path:
        template_path = template_img_path

    template_name = os.path.basename(template_path)
    canvas = Image.open(template_path).convert("RGBA")
    canvas.putalpha(255)
    draw = ImageDraw.Draw(canvas)

    x_f = 487
    x_back = 1385
    MAX_WIDTH_FRONT = 450
    MAX_WIDTH_BACK = 400

    f_hawariat = ImageFont.truetype(FONT_PATHS["hawariat"], 22)
    f_nokia = ImageFont.truetype(FONT_PATHS["nokia"], 30)
    f_nokia_small = ImageFont.truetype(FONT_PATHS["nokia"], 18)
    f_fcn_size = ImageFont.truetype(FONT_PATHS["nokia"], 26)
    f_fin_size = ImageFont.truetype(FONT_PATHS["nokia"], 27)
    f_addres_eng = ImageFont.truetype(FONT_PATHS["nokia"], 26)
    f_sn_number = ImageFont.truetype(FONT_PATHS["nokia"], 24)
    f_hawariat_small = ImageFont.truetype(FONT_PATHS["hawariat"], 18)
    f_addres_eng_small = ImageFont.truetype(FONT_PATHS["nokia"], 20)

    is_modern = "temp2" in template_name or "temp3" in template_name

    # Photos
    raw_path = data.get("photo_path")
    if raw_path and os.path.exists(raw_path):
        large = process_photo(raw_path, (330, 450), 18,
                              template_name, color_mode)
        if large:
            if is_modern:
                canvas.paste(large, (140, 130), large)
            else:
                canvas.paste(
                    large, (140 + (330 - large.width) // 2, 130), large)
        small = process_photo(raw_path, (80, 105), 8,
                              template_name, color_mode)
        if small:
            if is_modern:
                canvas.paste(small, (940, 475), small)
            else:
                canvas.paste(
                    small, (940 + (80 - small.width) // 2, 475), small)

    clean_am = data['am_name'].split('\n')[0] if data['am_name'] else ""
    clean_en = data['en_name'].split('\n')[0] if data['en_name'] else ""

    safe_draw(draw, (x_f, 185), clean_am,
              f_hawariat, max_width=MAX_WIDTH_FRONT)
    safe_draw(draw, (x_f, 213), clean_en, f_nokia, max_width=MAX_WIDTH_FRONT)
    safe_draw(draw, (x_f, 301),
              f"{data['dob_am']} | {data['dob_en']}", f_nokia)

    draw_rotated_spaced_text(canvas, (92, 405), data.get(
        'doi_am', ''), f_nokia_small, angle=90, spacing=3)
    draw_rotated_spaced_text(canvas, (92, 130), data.get(
        'doi_en', ''), f_nokia_small, angle=90, spacing=3)

    safe_draw(draw, (x_f, 410), data['sex_am'], f_hawariat, anchor="ls")
    am_w = draw.textlength(data['sex_am'], font=f_hawariat)
    safe_draw(draw, (x_f + am_w, 410),
              f" | {data['sex_en']}", f_nokia, anchor="ls")
    safe_draw(draw, (x_f, 488),
              f"{data['expiry_am']} | {data['expiry_en']}", f_nokia, anchor="ls")

    fcn_y = 506 if is_modern else 516
    fcn_spaced = " ".join(re.findall(r'.{1,4}', data['fcn']))
    draw_spaced_text(canvas, (x_f + 70, fcn_y),
                     fcn_spaced, f_fcn_size, spacing=2)

    safe_draw(draw, (x_back, 75), data['phone'], f_nokia)

    safe_draw(draw, (x_back, 255), data.get('region_am', ''),
              f_hawariat, fill="#000000", max_width=MAX_WIDTH_BACK)
    safe_draw(draw, (x_back, 280), data.get('region_en', ''),
              f_addres_eng, fill="#000000", max_width=MAX_WIDTH_BACK)

    zone_am = data.get('zone_am', '')
    zone_en = data.get('zone_en', '')
    zone_am_y = 340
    zone_en_y = 365

    if zone_am:
        safe_draw(draw, (x_back, zone_am_y), zone_am, f_hawariat,
                  fill="#000000", max_width=MAX_WIDTH_BACK)
        lines_am = len(textwrap.wrap(zone_am, width=int(
            MAX_WIDTH_BACK / f_hawariat.getlength("a"))))
        if lines_am > 1:
            zone_en_y = zone_am_y + (lines_am * 28) + 5
    if zone_en:
        safe_draw(draw, (x_back, zone_en_y), zone_en, f_addres_eng,
                  fill="#000000", max_width=MAX_WIDTH_BACK)
        lines_en = len(textwrap.wrap(zone_en, width=int(
            MAX_WIDTH_BACK / f_addres_eng.getlength("a"))))
        woreda_am_y = zone_en_y + (lines_en * 32) + 10
    else:
        woreda_am_y = zone_en_y + 40
    woreda_am_y = woreda_am_y + 20

    woreda_am = data.get('woreda_am', '')
    woreda_en = data.get('woreda_en', '')
    if woreda_am:
        safe_draw(draw, (x_back, woreda_am_y), woreda_am, f_hawariat,
                  fill="#000000", max_width=MAX_WIDTH_BACK)
        lines_woreda_am = len(textwrap.wrap(woreda_am, width=int(
            MAX_WIDTH_BACK / f_hawariat.getlength("a"))))
        woreda_en_y = woreda_am_y + (lines_woreda_am * 28) + 5
    else:
        woreda_en_y = woreda_am_y + 40
    woreda_en_y = woreda_en_y - 10

    if woreda_en:
        safe_draw(draw, (x_back, woreda_en_y), woreda_en,
                  f_addres_eng, fill="#000000", max_width=MAX_WIDTH_BACK)

    fin_spaced = " ".join(re.findall(r'.{1,4}', data['fin']))
    safe_draw(draw, (1516, 545), fin_spaced, f_fin_size)

    sn_number = get_next_sn()
    safe_draw(draw, (2247, 610), f"{sn_number}", f_sn_number, fill="#000000")

    qr_path = data.get("qr_path")
    if qr_path and os.path.exists(qr_path):
        qr_img = Image.open(qr_path).convert("RGBA")
        qr_img = qr_img.resize((515, 515), Image.Resampling.LANCZOS)
        canvas.paste(qr_img, (1815, 52), qr_img)

    # Use English name for filename, fallback to FCN if name is empty
    name = data.get('en_name', '').strip()
    if name:
        safe_name = re.sub(r'[^\w\s-]', '', name).strip()
        safe_name = re.sub(r'[-\s]+', '_', safe_name)
        filename = f"{safe_name}.png"
    else:
        filename = f"ID_{data['fcn']}.png"

    final_out = os.path.join(output_folder, filename)
    if os.path.exists(final_out):
        os.remove(final_out)
    canvas.save(final_out, format="PNG", quality=100)

    try:
        if os.path.exists(data.get("temp_path", "")):
            os.remove(data["temp_path"])
        if os.path.exists(raw_path):
            os.remove(raw_path)
        if os.path.exists(qr_path):
            os.remove(qr_path)
    except:
        pass

    return final_out
