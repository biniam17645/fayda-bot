# type_b_extractor.py - COMPLETELY STANDALONE for Type B PDFs (Bayush, Keneni)
import uuid
import os
import re
import fitz
import pytesseract
from PIL import Image, ImageOps
from kenat import Kenat
from datetime import datetime, timedelta


def extract_type_b_data(pdf_path, output_folder):
    request_id = str(uuid.uuid4())[:8]

    doc = fitz.open(pdf_path)
    page = doc.load_page(0)
    pix = page.get_pixmap(dpi=300)

    temp_path = os.path.join(output_folder, f"temp_b_{request_id}.png")
    raw_photo_path = os.path.join(output_folder, f"raw_b_{request_id}.png")
    qr_path = os.path.join(output_folder, f"qr_b_{request_id}.png")

    pix.save(temp_path)
    temp_img = Image.open(temp_path)

    data = {
        "am_name": "", "en_name": "", "dob_am": "", "dob_en": "",
        "sex_am": "", "sex_en": "", "expiry_am": "", "expiry_en": "",
        "doi_am": "", "doi_en": "", "fcn": "", "fin": "", "phone": "",
        "region_am": "", "region_en": "", "zone_am": "", "zone_en": "",
        "woreda_am": "", "woreda_en": "",
        "photo_path": raw_photo_path, "qr_path": qr_path, "temp_path": temp_path
    }

    # Save photo
    temp_img.crop((222, 416, 581, 908)).save(raw_photo_path)

    # QR code crop for Type B
    temp_img.crop((1705, 1524, 2255, 2033)).save(qr_path)

    # ========== EXACT COORDINATE-BASED EXTRACTION FROM inspect_layout.py ==========
    pdf_page = doc.load_page(0)

    # Static coordinate boxes (adjust for Type B if needed)
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

    # Extract Fields
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

    print(f"DEBUG Type B - Name: {data['am_name']} | {data['en_name']}")
    print(f"DEBUG Region: {data['region_am']} | {data['region_en']}")
    print(f"DEBUG Sex: {data['sex_am']} | {data['sex_en']}")
    print(f"DEBUG Zone: {data['zone_am']} | {data['zone_en']}")
    print(f"DEBUG Woreda: {data['woreda_am']} | {data['woreda_en']}")
    print(f"DEBUG Phone: {data['phone']}")

    # ========== TESSERACT EXTRACTION FOR REMAINING FIELDS ==========
    def ocr_b(crop, lang='eng', digits_only=False, is_amharic=False):
        gray = crop.convert('L')
        if is_amharic:
            gray = ImageOps.autocontrast(gray)
        big = gray.resize((gray.width * 3, gray.height * 3),
                          Image.Resampling.LANCZOS)
        config = '--psm 8 digits' if digits_only else '--psm 7'
        text = pytesseract.image_to_string(
            big, lang=lang, config=config).strip()
        artifacts = ['-', '_', '=', ':', ';', '!',
                     '?', '.', ',', '«', '»', '*', '“', '”']
        for ch in artifacts:
            text = text.replace(ch, ' ')
        return " ".join(text.split())

    # --- Demographics (DOB, expiry) ---
    dem_crop = temp_img.crop((1700, 850, 2200, 1400))
    lines = pytesseract.image_to_string(dem_crop, lang='amh+eng').split('\n')
    date_lines = [l for l in lines if "/" in l and "|" in l]
    if len(date_lines) >= 2:
        d_p = date_lines[0].split('|')
        data["dob_am"], data["dob_en"] = d_p[0].strip(), d_p[1].strip()
        e_p = date_lines[1].split('|')
        data["expiry_am"], data["expiry_en"] = e_p[0].strip(), e_p[1].strip()

    # --- FCN (16 digits) ---
    fcn_text = ocr_b(temp_img.crop((1827, 1199, 2116, 1223)), digits_only=True)
    data["fcn"] = "".join(re.findall(r'\d+', fcn_text))[:16]

    # --- FIN (12 digits) ---
    fin_text = ocr_b(temp_img.crop((2067, 2064, 2265, 2100)), digits_only=True)
    data["fin"] = "".join(re.findall(r'\d+', fin_text))[:12]

    # # --- DOI (rotated) ---
    # doi_crop = temp_img.crop((2211, 505, 2289, 866)).rotate(270, expand=True)
    # doi_raw = ocr_b(doi_crop, lang='eng')
    # if "|" in doi_raw:
    #     parts = doi_raw.split("|")
    #     am_digits = "".join(re.findall(r'[\d/]+', parts[0]))
    #     data["doi_am"] = re.sub(r'^[^2]*', '', am_digits).replace("204", "201")
    #     en_text = "".join(re.findall(r'[\d/A-Za-z]+', parts[1]))
    #     data["doi_en"] = re.sub(r'^[^2]*', '', en_text)
    # else:
    #     parts = re.split(r'\s+', doi_raw)
    #     if len(parts) >= 2:
    #         data["doi_am"] = parts[0].replace("204", "201")
    #         data["doi_en"] = parts[1]
    # ========== ADD NEW DATE CALCULATION (Current Date Based) ==========

    # Get current date
    now = datetime.now()

    # ========== CURRENT DATE BASED CALCULATION (DOI & EXPIRY) ==========
    # Get current UTC date
    now = datetime.utcnow()

    # Get Ethiopian date using kenat
    eth_today = Kenat.now()
    eth_year = eth_today.year
    eth_month = eth_today.month
    eth_day = eth_today.day

    # DOI (Date of Issue) - Current date
    # Gregorian format: YYYY/MMM/DD
    data["doi_en"] = now.strftime("%Y/%b/%d")
    # Ethiopian format: DD/MM/YYYY
    data["doi_am"] = f"{eth_day:02d}/{eth_month:02d}/{eth_year}"

    # Expiry Date - Current date + 8 years - 2 days
    expiry_date = now + timedelta(days=(8 * 365) - 2)
    data["expiry_en"] = expiry_date.strftime("%Y/%b/%d")

    # Ethiopian expiry date (add 8 years to Ethiopian calendar)
    expiry_eth_year = eth_year + 8
    # Subtract 2 days (simplified - adjust month/day if needed)
    expiry_eth_day = eth_day - 2
    expiry_eth_month = eth_month
    if expiry_eth_day <= 0:
        # Handle month rollback (simplified)
        expiry_eth_day = 30 + expiry_eth_day
        expiry_eth_month -= 1
        if expiry_eth_month <= 0:
            expiry_eth_month = 13
            expiry_eth_year -= 1

    data["expiry_am"] = f"{expiry_eth_day:02d}/{expiry_eth_month:02d}/{expiry_eth_year}"

    print(f"📅 Current Gregorian: {now.strftime('%Y-%m-%d')}")
    print(f"📅 Current Ethiopian: {data['doi_am']}")
    print(f"📅 Expiry Gregorian: {data['expiry_en']}")
    print(f"📅 Expiry Ethiopian: {data['expiry_am']}")

    doc.close()

    print("\n" + "="*50)
    print("📋 EXTRACTED ID DATA (Type B)")
    print("="*50)
    for key, value in data.items():
        if value and key not in ["photo_path", "qr_path", "temp_path"]:
            print(f"{key}: {value}")
        elif key not in ["photo_path", "qr_path", "temp_path"]:
            print(f"{key}: (empty)")
    print("="*50 + "\n")

    return data
