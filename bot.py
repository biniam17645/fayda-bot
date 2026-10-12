# bot.py - Complete Fixed Version
import os
import uuid
import logging
import sys
import re
import asyncio
import json
import base64
import time
from io import BytesIO
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from functools import partial
import threading
import libsql
import pytesseract
import fitz
from PIL import Image
from dotenv import load_dotenv

from telegram import (
    Update,
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
    ConversationHandler,
)
from telegram.request import HTTPXRequest

# Custom modules
from main import render_id, process_photo, generate_reversed_a4_layout, get_pdf_data
from screenshot import process_screenshot_workflow
from type_b_extractor import extract_type_b_data

# Celery imports
from celery_app import celery_app
from tasks import process_pdf_task, process_screenshot_task, process_bulk_task
import redis
from celery.result import AsyncResult

load_dotenv()

# ============ CONFIGURATION ============
TOKEN = os.getenv("BOT_TOKEN") or os.getenv("TELEGRAM_BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "8131225823"))
BOT_USERNAME = os.getenv("BOT_USERNAME", "FAYDA_ID_C_BOT")
REFERRAL_REWARD = 2
REFERRAL_TARGET = 5
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

if not TOKEN:
    print("CRITICAL: BOT_TOKEN not set!")
    sys.exit(1)

# ============ LOGGING ============
logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# ============ DIRECTORIES ============
INPUT_DIR = "input"
OUTPUT_DIR = "output"
A4_DIR = "a4_layouts"
os.makedirs(INPUT_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs(A4_DIR, exist_ok=True)

# ============ REDIS SETUP ============
try:
    redis_client = redis.from_url(REDIS_URL)
    redis_client.ping()
    logger.info("✅ Redis connected successfully")
except Exception as e:
    logger.warning(
        f"⚠️ Redis connection failed: {e}. Falling back to in-memory.")
    redis_client = None

JOB_STATUS_KEY = "job_status_{job_id}"
JOB_RESULT_KEY = "job_result_{job_id}"

# ============ TRANSLATIONS ============
LANGUAGES = {
    'en': {
        'name': 'English 🇬🇧',
        'welcome': "Welcome {name}! 👋\n\nPlease choose your preferred language:",
        'template_selected': "✅ Template saved! Use the buttons below.",
        'upload_id': "📤 Upload ID",
        'my_ids': "📂 My IDs",
        'wallet': "💳 Wallet",
        'templates': "🎨 Templates",
        'deposit': "➕ Deposit",
        'support': "👨‍💻 Support",
        'bulk_process': "📊 Bulk Process",
        'settings': "⚙️ Settings",
        'invite': "🎁 Invite Friends",
        'dashboard': "📱 Dashboard",
        'no_ids': "📭 **No IDs Generated Yet**\n\nUpload an ID using the 📤 Upload ID button to get started!",
        'my_ids_header': "📊 **My IDs**\n\n📈 Total: {total} | Today: {today}\n\n",
        'wallet_info': "💳 **Wallet**\nRemaining IDs: `{balance}`\nTotal generated: `{total}`",
        'deposit_info': "➕ **Buy Credits**\n\n• 30 ETB = 1 ID\n• 90 ETB = 3 IDs\n• 150 ETB = 5 IDs\n• 300 ETB = 10 IDs\n• 900 ETB = 30 IDs\n\nPay via Telebirr: `0943686869` (Ermias Shumi).\nAfter payment, paste the transaction link here.",
        'support_info': "👨‍💻 **Support**\n\nNeed help? Send your issue in a single message below and an admin will reply right here.\n\n💬 *Prefer to chat directly?* Contact @brukshumi\n\n*(Send /cancel to exit)*",
        'support_sent': "✅ Message sent. You'll get a reply here.",
        'support_cancelled': "Cancelled.",
        'upload_prompt': "📤 Send your ID (screenshot or PDF).\nFor screenshots: send front image first, then back.\nFor PDF: send the PDF file directly.",
        'bulk_prompt': "📊 **Bulk Processing**\n\nHow many PDFs do you want to process?\nSelect a number below:",
        'bulk_processing': "⏳ Processing {count} PDFs... This may take a while.",
        'bulk_complete': "✅ Bulk processing complete! Generated {successful}/{total} IDs.",
        'settings_prompt': "⚙️ **Settings**\n\nSelect what you want to configure:",
        'settings_format': "📄 **Output Format**\n\nChoose your preferred output format:",
        'settings_quality': "🎨 **Image Quality**\n\nChoose your preferred image quality:",
        'settings_layout': "🖨️ **Layout Mode**\n\nChoose your preferred layout mode:",
        'settings_saved': "✅ Settings saved!",
        'invite_prompt': "🎁 **Invite Friends & Earn Credits!**\n\nShare your referral link and earn **{reward} IDs** for every **{target} friends** who join!\n\n📊 **Your Stats:**\n• Total Referrals: {total}\n• Current Progress: {progress}/{target}\n• IDs Earned: {earned}\n\nShare your link with friends and start earning!",
        'invite_share_text': "🎁 Join me and get your ID cards easily!\n\n{link}\n\nUse my referral link and start generating your IDs!",
        'invite_joined': "🎉 **New Referral!**\n\n{name} joined using your referral link!\n\nProgress: {progress}/{target}\n\nKeep sharing to earn more IDs!",
        'invite_reward': "🎉 **Congratulations!**\n\nYou've reached {target} referrals! 🎊\n\nEarned: +{reward} IDs\nTotal IDs: {balance}\n\nKeep inviting to earn more!",
        'dashboard_prompt': "📱 **Dashboard**\n\nAccess your account and manage your IDs:",
        'no_credits': "❌ No credits left. Use ➕ Deposit to buy more.",
        'processing': "⏳ Processing...",
        'id_ready': "✅ ID ready! {balance}\n⚠️ If any data is incorrect, click 'Report Error' below (valid for 10 minutes).",
        'a4_layout': "🖨️ A4 print layout (mirrored)",
        'normal_layout': "📄 Normal layout",
        'error_retry': "❌ Something went wrong. Please try again later. If the issue persists, contact support.",
        'payment_submitted': "⏳ Payment link sent to admin. Please wait for verification.",
        'payment_approved': "✅ Payment approved! +{amount} credits.",
        'payment_rejected': "❌ Your payment was rejected. Please check your transaction link and amount, then try again.",
        'template_choose': "Choose color or greyscale mode:",
        'template_preview': "Preview not available for {label}\nChoose color or greyscale mode:",
        'color_mode': "🎨 Color",
        'grey_mode': "⚫ Grey",
        'already_selected': "Already selected",
        'history_empty': "📭 No IDs in history.",
        'history_limit': "Showing 10 of {total} IDs",
        'bulk_select': "Select number of PDFs to process:",
        'settings_format_options': "Choose output format:",
        'settings_quality_options': "Choose image quality:",
        'settings_layout_options': "Choose layout mode:",
        'report_error': "⚠️ Report Error",
        'report_expired': "⚠️ This report button has expired (10 minutes limit). Please generate the ID again if you need to report an error.",
        'correction_start': "🔄 Starting correction process... You will be asked for each selected field one by one.",
        'correction_done': "✅ Your corrections have been applied! Here's your updated ID.",
        'correction_cancelled': "Correction cancelled.",
        'correction_field': "📝 **Field {current}/{total}**: {label}\nOriginal value: `{original}`\n\nPlease send the corrected value:",
        'correction_applied': "✅ Corrections applied and ID regenerated!",
        'correction_failed': "❌ Sorry, there was an error applying your corrections. Please try again or contact support.",
        'session_expired': "❌ Session expired. Please start over.",
        'select_fields': "Select fields to correct (tap to toggle). Press DONE when finished.",
        'no_fields': "No fields selected. Please select at least one field.",
        'job_started': "⏳ **Processing started!**\n\nI'll send you the result once it's ready. This usually takes 30-60 seconds.\n\n🔔 You'll get a notification when it's done.\n\nUse /status to check progress.",
        'job_processing': "🔄 **Working...**\n\n{message}",
        'job_pending': "⏳ **Processing...**\n\n{message}\n\n⏱️ Waiting time: {time}s",
        'job_done': "✅ **Done!** Your ID card is ready above.",
        'job_failed': "❌ **Processing Failed**\n\nError: {error}\n\nPlease try again or contact support.",
        'job_timeout': "⏰ **Processing is taking longer than expected.**\n\nDon't worry, your ID is still being generated. I'll notify you as soon as it's ready!\n\nIf you don't receive it within 5 minutes, please contact support.",
        'no_active_job': "No active job found.",
        'job_status': "⏳ Waiting in queue... ({message})",
        'job_status_processing': "🔄 Processing... ({message})",
        'job_status_completed': "✅ Your ID is ready! Check the messages above.",
        'referral_error': "❌ Something went wrong with the referral. Please try again or contact support.",
    },
    'am': {
        'name': 'አማርኛ 🇪🇹',
        'welcome': "እንኳን ደህና መጣህ {name}! 👋\n\nእባክህ የሚፈልገውን ቋንቋ ምረጥ:",
        'template_selected': "✅ አብነት ተቀመጠ! ከታች ያሉትን ቁልፎች ተጠቀም።",
        'upload_id': "📤 መታወቂያ ስቀል",
        'my_ids': "📂 መታወቂያዎቼ",
        'wallet': "💳 ቦርሳ",
        'templates': "🎨 አብነቶች",
        'deposit': "➕ ገንዘብ አስገባ",
        'support': "👨‍💻 እርዳታ",
        'bulk_process': "📊 በብዛት ማስኬድ",
        'settings': "⚙️ ቅንብሮች",
        'invite': "🎁 ጓደኞችን ጋብዝ",
        'dashboard': "📱 ዳሽቦርድ",
        'no_ids': "📭 **እስካሁን ምንም መታወቂያ አልተዘጋጀም**\n\nእባክህ 📤 መታወቂያ ስቀል ቁልፍን ተጫን ለመጀመር!",
        'my_ids_header': "📊 **መታወቂያዎቼ**\n\n📈 አጠቃላይ: {total} | ዛሬ: {today}\n\n",
        'wallet_info': "💳 **ቦርሳ**\nቀሪ መታወቂያዎች: `{balance}`\nአጠቃላይ የተዘጋጁ: `{total}`",
        'deposit_info': "➕ **ክሬዲቶች ግዛ**\n\n• 30 ብር = 1 መታወቂያ\n• 90 ብር = 3 መታወቂያዎች\n• 150 ብር = 5 መታወቂያዎች\n• 300 ብር = 10 መታወቂያዎች\n• 900 ብር = 30 መታወቂያዎች\n\nበቴሌብር: `0943686869` (ኤርሚያስ ሹሚ) ክፈል።\nከክፍያ በኋላ የግብይት አገናኙን እዚህ ላይ ለጥፍ።",
        'support_info': "👨‍💻 **እርዳታ**\n\nእርዳታ ይፈልጋሉ? ችግርህን በአንድ መልእክት ላክ እና አስተዳዳሪ እዚህ ላይ መልስ ይሰጣል።\n\n💬 *በቀጥታ መነጋገር ትፈልጋለህ?* @brukshumi አግኝ\n\n*(ለመሰረዝ /cancel ላክ)*",
        'support_sent': "✅ መልእክት ተላከ። መልስ እዚህ ላይ ታገኛለህ።",
        'support_cancelled': "ተሰርዟል።",
        'upload_prompt': "📤 መታወቂያህን ላክ (ስክሪን ሾት ወይም ፒዲኤፍ)።\nለስክሪን ሾት: የፊት ምስል በመጀመሪያ ላክ፣ ከዚያ የኋላ።\nለፒዲኤፍ: ፒዲኤፍ ፋይሉን በቀጥታ ላክ።",
        'bulk_prompt': "📊 **በብዛት ማስኬድ**\n\nስንት ፒዲኤፎች ማስኬድ ትፈልጋለህ?\nከታች ቁጥር ምረጥ:",
        'bulk_processing': "⏳ {count} ፒዲኤፎችን በማስኬድ ላይ... ይህ ጊዜ ሊወስድ ይችላል።",
        'bulk_complete': "✅ በብዛት ማስኬድ ተጠናቀቀ! {successful}/{total} መታወቂያዎች ተዘጋጁ።",
        'settings_prompt': "⚙️ **ቅንብሮች**\n\nምን ማዋቀር እንደሚፈልጉ ምረጡ:",
        'settings_format': "📄 **የውጤት ቅርጸት**\n\nየሚፈለገውን የውጤት ቅርጸት ምረጥ:",
        'settings_quality': "🎨 **የምስል ጥራት**\n\nየሚፈለገውን የምስል ጥራት ምረጥ:",
        'settings_layout': "🖨️ **የአቀማመጥ ሁነታ**\n\nየሚፈለገውን የአቀማመጥ ሁነታ ምረጥ:",
        'settings_saved': "✅ ቅንብሮች ተቀመጡ!",
        'invite_prompt': "🎁 **ጓደኞችን ጋብዝ እና ክሬዲቶች አግኝ!**\n\nየማጣቀሻ አገናኝህን አጋራ እና **{reward} መታወቂያዎች** ለ **{target} ጓደኞች** ሲቀላቀሉ አግኝ!\n\n📊 **ስታቲስቲክስህ:**\n• አጠቃላይ ማጣቀሻዎች: {total}\n• የአሁኑ እድገት: {progress}/{target}\n• ያገኘኸው መታወቂያዎች: {earned}\n\nአገናኝህን ከጓደኞችህ ጋር አጋራ እና መጠቀም ጀምር!",
        'invite_share_text': "🎁 ይቀላቀሉኝ እና መታወቂያዎችዎን በቀላሉ ያግኙ!\n\n{link}\n\nየማጣቀሻ አገናኝዬን ይጠቀሙ እና መታወቂያዎችዎን ማመንጨት ይጀምሩ!",
        'invite_joined': "🎉 **አዲስ ማጣቀሻ!**\n\n{name} የማጣቀሻ አገናኝህን በመጠቀም ተቀላቀለ!\n\nእድገት: {progress}/{target}\n\nተጨማሪ መታወቂያዎች ለማግኘት ማጣቀሻህን መጋራትህን ቀጥል!",
        'invite_reward': "🎉 **እንኳን ደስ ያለህ!**\n\n{target} ማጣቀሻዎች ላይ ደርሰሃል! 🎊\n\nያገኘኸው: +{reward} መታወቂያዎች\nአጠቃላይ መታወቂያዎች: {balance}\n\nተጨማሪ ለማግኘት መጋበዝህን ቀጥል!",
        'dashboard_prompt': "📱 **ዳሽቦርድ**\n\nመለያህን እና መታወቂያዎችህን አስተዳድር:",
        'no_credits': "❌ በቂ ክሬዲቶች የሉም። ለመግዛት ➕ ገንዘብ አስገባ ተጫን።",
        'processing': "⏳ በማስኬድ ላይ...",
        'id_ready': "✅ መታወቂያ ተዘጋጀ! {balance}\n⚠️ ማንኛውም መረጃ የተሳሳተ ከሆነ፣ ከታች 'ስህተት አሳውቅ' ቁልፍን ተጫን (ለ10 ደቂቃዎች የሚሰራ)።",
        'a4_layout': "🖨️ የA4 ህትመት አቀማመጥ (የተገለበጠ)",
        'normal_layout': "📄 መደበኛ አቀማመጥ",
        'error_retry': "❌ የሆነ ስህተት ተከስቷል። እባክህ ቆየት ብለህ ሞክር። ችግሩ ከቀጠለ እርዳታ አግኝ።",
        'payment_submitted': "⏳ የክፍያ አገናኝ ለአስተዳዳሪ ተልኳል። እባክህ ማረጋገጫ ጠብቅ።",
        'payment_approved': "✅ ክፍያ ጸድቋል! +{amount} ክሬዲቶች።",
        'payment_rejected': "❌ ክፍያህ ተሰርዟል። እባክህ የግብይት አገናኝህን እና መጠኑን ፈትሽ፣ ከዚያ እንደገና ሞክር።",
        'template_choose': "የቀለም ወይም ግራጫ ሁነታ ምረጥ:",
        'template_preview': "ለ{label} ቅድመ-እይታ አይገኝም\nየቀለም ወይም ግራጫ ሁነታ ምረጥ:",
        'color_mode': "🎨 ቀለም",
        'grey_mode': "⚫ ግራጫ",
        'already_selected': "አስቀድሞ ተመርጧል",
        'history_empty': "📭 በታሪክ ውስጥ ምንም መታወቂያዎች የሉም።",
        'history_limit': "ከ{total} መታወቂያዎች 10ቱን በማሳየት ላይ",
        'bulk_select': "ለማስኬድ የፒዲኤፍ ብዛት ምረጥ:",
        'settings_format_options': "የውጤት ቅርጸት ምረጥ:",
        'settings_quality_options': "የምስል ጥራት ምረጥ:",
        'settings_layout_options': "የአቀማመጥ ሁነታ ምረጥ:",
        'report_error': "⚠️ ስህተት አሳውቅ",
        'report_expired': "⚠️ ይህ ሪፖርት ቁልፍ ጊዜው አልፏል (የ10 ደቂቃ ገደብ)። ስህተት ለማሳወቅ ከፈለግህ እባክህ መታወቂያውን እንደገና አዘጋጅ።",
        'correction_start': "🔄 የማረም ሂደት እየጀመረ ነው... ለእያንዳንዱ ለተመረጠ መስክ በተራ ትጠየቃለህ።",
        'correction_done': "✅ ማሻሻያዎችህ ተተግብረዋል! የዘመነ መታወቂያህ እነሆ።",
        'correction_cancelled': "ማረም ተሰርዟል።",
        'correction_field': "📝 **መስክ {current}/{total}**: {label}\nየመጀመሪያ እሴት: `{original}`\n\nእባክህ የተስተካከለውን እሴት ላክ:",
        'correction_applied': "✅ ማሻሻያዎች ተተግብረዋል እና መታወቂያ እንደገና ተዘጋጅቷል!",
        'correction_failed': "❌ ይቅርታ፣ ማሻሻያዎችህን በመተግበር ላይ ስህተት ተከስቷል። እባክህ እንደገና ሞክር ወይም እርዳታ አግኝ።",
        'session_expired': "❌ ክፍለ ጊዜ አልቋል። እባክህ እንደገና ጀምር።",
        'select_fields': "ለማረም መስኮች ምረጥ (ለመቀያየር ተጫን)። ሲጨርሱ DONE ተጫን።",
        'no_fields': "ምንም መስኮች አልተመረጡም። እባክህ ቢያንስ አንድ መስክ ምረጥ።",
        'job_started': "⏳ **ሂደት ተጀመረ!**\n\nውጤቱ ሲዘጋጅ እልክልሃለሁ። ብዙ ጊዜ አይወስድም - በማስኬድ ላይ ነው።\n\nሁኔታውን ለማየት /status ይጠቀሙ።",
        'job_processing': "🔄 **በማስኬድ ላይ...**\n\n{message}",
        'job_pending': "⏳ **በማስኬድ ላይ...**\n\n{message}\n\n⏱️ የቆየ ጊዜ: {time}s",
        'job_done': "✅ **ተጠናቀቀ!** መታወቂያህ ከላይ ዝግጁ ነው።",
        'job_failed': "❌ **ማስኬድ አልተሳካም**\n\nስህተት: {error}\n\nእባክህ እንደገና ሞክር ወይም እርዳታ አግኝ።",
        'job_timeout': "⏰ **ማስኬድ ከተጠበቀው በላይ ጊዜ ወስዷል።**\n\nአትጨነቅ፣ መታወቂያህ አሁንም እየተዘጋጀ ነው። ሲዘጋጅ አሳውቅሃለሁ።\n\nከ5 ደቂቃ በኋላ ካልደረሰህ እባክህ እርዳታ አግኝ።",
        'no_active_job': "ምንም ንቁ ስራ አልተገኘም።",
        'job_status': "⏳ ወረፋ ላይ በመጠበቅ ላይ... ({message})",
        'job_status_processing': "🔄 በማስኬድ ላይ... ({message})",
        'job_status_completed': "✅ መታወቂያህ ዝግጁ ነው! ከላይ ያሉትን መልእክቶች ተመልከት።",
        'referral_error': "❌ በማጣቀሻ ላይ ስህተት ተከስቷል። እባክህ እንደገና ሞክር ወይም እርዳታ አግኝ።",
    },
    'om': {
        'name': 'Afaan Oromoo 🇪🇹',
        'welcome': "Baga nagaan dhufte {name}! 👋\n\nMaaloo afaan barbaaddu filadhu:",
        'template_selected': "✅ Template'ni kaa'ame! Batoonni gadii fayyadami.",
        'upload_id': "📤 ID Galchi",
        'my_ids': "📂 ID' koo",
        'wallet': "💳 Kasaara",
        'templates': "🎨 Template'oota",
        'deposit': "➕ Maallaqa kaa'i",
        'support': "👨‍💻 Gargaarsa",
        'bulk_process': "📊 Baay'inaan Hojii",
        'settings': "⚙️ Qindaa'ina",
        'invite': "🎁 Hiriyoota Affaari",
        'dashboard': "📱 Daashboordii",
        'no_ids': "📭 **ID Hanga ammaa hin uumamne**\n\nMaaloo ID galchuuf batoon 📤 Upload ID tuqi!",
        'my_ids_header': "📊 **ID' Koo**\n\n📈 Waliigala: {total} | Har'a: {today}\n\n",
        'wallet_info': "💳 **Kasaara**\nID' hafan: `{balance}`\nWaliigala uumaman: `{total}`",
        'deposit_info': "➕ **Kireedita Bitadhu**\n\n• 30 ETB = 1 ID\n• 90 ETB = 3 ID'oota\n• 150 ETB = 5 ID'oota\n• 300 ETB = 10 ID'oota\n• 900 ETB = 30 ID'oota\n\nTelebirr'aan kaffali: `0943686869` (Ermias Shumi).\nKaffaltii booda, geessituu daldalaa asitti maxxanfachuu.",
        'support_info': "👨‍💻 **Gargaarsa**\n\nGargaarsa barbaaduu? Rakkoo keessan ergaa tokkoon ergaa fi admin asitti deebii isiniif kenna.\n\n💬 *Walitti haasa'uu barbaaduu?* @brukshumi qunnamaa\n\n*(Haqamuuf /cancel ergaa)*",
        'support_sent': "✅ Ergaan ergame. Deebii asitti argatta.",
        'support_cancelled': "Haqame.",
        'upload_prompt': "📤 ID keessan ergaa (screenshot ykn PDF).\nScreenshot'uuf: fuuldura ergaa, booda duuba.\nPDF'uuf: faayila PDF'ii ergaa.",
        'bulk_prompt': "📊 **Baay'inaan Hojii**\n\nPDF'oota meeqa hojjechuu barbaaddu?\nLakkoofsa gadii filadhu:",
        'bulk_processing': "⏳ PDF'oota {count} hojjechaa jira... Kun yeroo fudhachuu danda'a.",
        'bulk_complete': "✅ Baay'inaan hojjiin xumurame! {successful}/{total} ID'oota uumaman.",
        'settings_prompt': "⚙️ **Qindaa'ina**\n\nMaal qindeessuu barbaaddu filadhu:",
        'settings_format': "📄 **Akkasanka Bahaa**\n\nAkkasanka bahaa barbaaddu filadhu:",
        'settings_quality': "🎨 **Qulqullina Fakkii**\n\nQulqullina fakkii barbaaddu filadhu:",
        'settings_layout': "🖨️ **Haala Qindaa'ina**\n\nHaala qindaa'ina barbaaddu filadhu:",
        'settings_saved': "✅ Qindaa'inni kaa'ame!",
        'invite_prompt': "🎁 **Hiriyoota Affaari fi Kireedita Argadhu!**\n\nGeessituu keessan qoodaa fi **{reward} ID'oota** argadhu **{target} hiriyoota** yeroo seenan!\n\n📊 **Tuuta Keessan:**\n• Waliigala Affaarama: {total}\n• Bu'uura ammaa: {progress}/{target}\n• ID'oota Argatan: {earned}\n\nGeessituu keessan hiriyoota keessan wajjin qoodaa fi bu'aa argachuu eegaltaa!",
        'invite_share_text': "🎁 Na qabaa fi kaardii ID keessan salphatti argadhaa!\n\n{link}\n\nGeessituu koo fayyadamii ID keessan uumuu eegalaa!",
        'invite_joined': "🎉 **Affaarama Haaraa!**\n\n{name} geessituu keessan fayyadamee seenee!\n\nBu'uura: {progress}/{target}\n\nID'oota dabalata argachuuf affaaruu itti fufaa!",
        'invite_reward': "🎉 **Baga Gammadde!**\n\nAffaarama {target} ga'eetta! 🎊\n\nArgatte: +{reward} ID'oota\nID'oota waliigalaa: {balance}\n\nDabalata argachuuf affaaru itti fufi!",
        'dashboard_prompt': "📱 **Daashboordii**\n\nAkaawuntii keessanii fi ID'oota keessan bulchaa:",
        'no_credits': "❌ Kireedita hin hafan. ➕ Deposit tuqi bitachuuf.",
        'processing': "⏳ Hojjechaa jira...",
        'id_ready': "✅ ID qophaa'e! {balance}\n⚠️ Odeeffannoonni tokko yoo dogoggore, 'Dogoggora Gabaasa' batoon gadii tuqi (daqiiqaa 10'f hojjeta).",
        'a4_layout': "🖨️ A4 maxxansa qindaa'ina (kan garagale)",
        'normal_layout': "📄 Qindaa'ina yeroo hunda",
        'error_retry': "❌ Dogoggora tokko uumame. Maaloo booda deebi'ii yaali. Rakkoon yoo itti fufe gargaarsa argadhu.",
        'payment_submitted': "⏳ Geessituu kaffaltii admin'tti ergame. Maaloo mirkaneessa eegi.",
        'payment_approved': "✅ Kaffaltiin mirkanaa'e! +{amount} kireedita.",
        'payment_rejected': "❌ Kaffaltiin keessan haqame. Maaloo geessituu daldalaa fi baay'ina keessan sakatta'aa, booda deebi'ii yaali.",
        'template_choose': "Akkasanka halluu ykn daaraa filadhu:",
        'template_preview': "Kanaaf {label} durargitii hin jiru\nAkkasanka halluu ykn daaraa filadhu:",
        'color_mode': "🎨 Halluu",
        'grey_mode': "⚫ Daaraa",
        'already_selected': "Duraan filatameera",
        'history_empty': "📭 Seenaa keessatti ID'oonni hin jiran.",
        'history_limit': "ID'oota {total} keessaa 10 agarsiifaa jira",
        'bulk_select': "Lakkoofsa PDF'ootaa hojjechuuf filadhu:",
        'settings_format_options': "Akkasanka bahaa filadhu:",
        'settings_quality_options': "Qulqullina fakkii filadhu:",
        'settings_layout_options': "Haala qindaa'ina filadhu:",
        'report_error': "⚠️ Dogoggora Gabaasa",
        'report_expired': "⚠️ Batoon gabaasa kana yeroon darbee (daqiqaa 10'f hojjeta). Dogoggora gabaasuu yoo barbaadan maaloo ID'ii deebi'ii uumaa.",
        'correction_start': "🔄 Hojii sirreessaa jalqabaa jira... Maaloo bakka filatame tokko tokkoon gaafatamtu.",
        'correction_done': "✅ Sirreessi keessan hojiirra oole! ID'ii haaraa keessan kunoo.",
        'correction_cancelled': "Sirreessi haqame.",
        'correction_field': "📝 **Bakka {current}/{total}**: {label}\nGatii jalqabaa: `{original}`\n\nMaaloo gatii sirreessaa ergaa:",
        'correction_applied': "✅ Sirreessi hojiirra oolee ID'ii deebi'ee uumame!",
        'correction_failed': "❌ Dhiifama, sirreessa keessan hojiirra oolchuun dogoggora uumame. Maaloo deebi'ii yaali ykn gargaarsa argadhu.",
        'session_expired': "❌ Yeroo xumurame. Maaloo irraa eegalaa.",
        'select_fields': "Bakka sirreessuuf filadhu (tuquun jijjiiri). Xumuruuf DONE tuqi.",
        'no_fields': "Bakki tokko illee hin filatamne. Maaloo tokko filadhu.",
        'job_started': "⏳ **Hojii eegale!**\n\nBu'aan yeroo qophaa'u erga. Yeroo muraasa qofa.\n\nHaala ilaaluuf /status fayyadami.",
        'job_processing': "🔄 **Hojjechaa jira...**\n\n{message}",
        'job_pending': "⏳ **Hojjechaa jira...**\n\n{message}\n\n⏱️ Yeroo darbee: {time}s",
        'job_done': "✅ **Xumurame!** ID'ii keessan gubbaatti qophaa'e.",
        'job_failed': "❌ **Hojii hin milkoofne**\n\nDogoggora: {error}\n\nMaaloo deebi'ii yaali ykn gargaarsa argadhu.",
        'job_timeout': "⏰ **Hojichi yeroo dheeraa fudhate.**\n\nHin sodaatinaa, ID'ii keessan amma iyyuu hojjechaa jira. Yeroo xumurame isin beeksisa.\n\n5 daqiiqaa booda yoo hin argatine maaloo gargaarsa argadhu.",
        'no_active_job': "Hojii tokkollee hin argamne.",
        'job_status': "⏳ Tarkaanfii eegaa jira... ({message})",
        'job_status_processing': "🔄 Hojjechaa jira... ({message})",
        'job_status_completed': "✅ ID'ii keessan qophaa'e! Ergaa gubbaa ilaali.",
        'referral_error': "❌ Dogoggora affaarama keessatti uumame. Maaloo deebi'ii yaali ykn gargaarsa argadhu.",
    }
}

# ============ DATABASE ============


def get_db_connection():
    url = os.getenv("TURSO_DATABASE_URL")
    token = os.getenv("TURSO_AUTH_TOKEN")
    if not url or not token:
        raise RuntimeError("Turso credentials missing")
    return libsql.connect(url, auth_token=token)


def init_db():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance INTEGER DEFAULT 0,
            total_generated INTEGER DEFAULT 0,
            default_template TEXT DEFAULT 'temp1_color',
            language TEXT DEFAULT 'en',
            output_format TEXT DEFAULT 'pdf',
            image_quality TEXT DEFAULT 'high',
            layout_mode TEXT DEFAULT 'mirrored',
            referral_code TEXT,
            referred_by INTEGER DEFAULT NULL,
            referral_count INTEGER DEFAULT 0,
            referral_earned INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            tx_id TEXT PRIMARY KEY,
            user_id INTEGER,
            amount INTEGER,
            credits INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS error_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            field TEXT,
            original_value TEXT,
            corrected_value TEXT,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            request_id TEXT,
            original_data_json TEXT,
            corrections_json TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS last_generated (
            request_id TEXT PRIMARY KEY,
            user_id INTEGER,
            data_json TEXT,
            template_path TEXT,
            color_mode TEXT,
            photo_base64 TEXT,
            qr_base64 TEXT,
            created_epoch REAL,
            output_path TEXT,
            a4_path TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS id_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            request_id TEXT,
            en_name TEXT,
            am_name TEXT,
            fcn TEXT,
            fin TEXT,
            generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            template_used TEXT,
            file_path TEXT,
            a4_path TEXT,
            data_json TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER,
            referred_id INTEGER UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS bulk_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            job_id TEXT UNIQUE,
            total_files INTEGER,
            processed INTEGER DEFAULT 0,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            completed_at TIMESTAMP
        )
    """)
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_history_user_id ON id_history(user_id)")
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_history_generated_at ON id_history(generated_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_payments_user_id ON payments(user_id)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status)")
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_referrals_referrer ON referrals(referrer_id)")
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_referrals_referred ON referrals(referred_id)")
    c.execute(
        "CREATE INDEX IF NOT EXISTS idx_users_referral_code ON users(referral_code)")

    # Migrations
    for col, dtype in [
        ("language", "TEXT DEFAULT 'en'"),
        ("output_format", "TEXT DEFAULT 'pdf'"),
        ("image_quality", "TEXT DEFAULT 'high'"),
        ("layout_mode", "TEXT DEFAULT 'mirrored'"),
        ("referral_code", "TEXT"),
        ("referred_by", "INTEGER"),
        ("referral_count", "INTEGER DEFAULT 0"),
        ("referral_earned", "INTEGER DEFAULT 0"),
        ("corrections_json", "TEXT"),
        ("photo_base64", "TEXT"),
        ("qr_base64", "TEXT"),
        ("created_epoch", "REAL"),
        ("output_path", "TEXT"),
        ("a4_path", "TEXT"),
        ("credits", "INTEGER DEFAULT 0"),
    ]:
        try:
            c.execute(f"ALTER TABLE users ADD COLUMN {col} {dtype}")
        except Exception:
            pass
    try:
        c.execute("ALTER TABLE error_reports ADD COLUMN corrections_json TEXT")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE last_generated ADD COLUMN photo_base64 TEXT")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE last_generated ADD COLUMN qr_base64 TEXT")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE last_generated ADD COLUMN created_epoch REAL")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE last_generated ADD COLUMN output_path TEXT")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE last_generated ADD COLUMN a4_path TEXT")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE payments ADD COLUMN credits INTEGER DEFAULT 0")
    except Exception:
        pass
    try:
        c.execute("ALTER TABLE id_history ADD COLUMN a4_path TEXT")
    except Exception:
        pass
    try:
        c.execute(
            "ALTER TABLE users ADD COLUMN created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
    except Exception:
        pass

    conn.commit()
    conn.close()
    logger.info("✅ Turso Database initialized")


def get_user(user_id: int) -> Dict:
    conn = get_db_connection()
    row = conn.execute("""
        SELECT balance, total_generated, default_template, language, 
               output_format, image_quality, layout_mode, referral_code, referred_by,
               referral_count, referral_earned
        FROM users WHERE user_id = ?
    """, (user_id,)).fetchone()
    conn.close()
    if row:
        return {
            "balance": row[0],
            "total_generated": row[1],
            "default_template": row[2],
            "language": row[3],
            "output_format": row[4] or "pdf",
            "image_quality": row[5] or "high",
            "layout_mode": row[6] or "mirrored",
            "referral_code": row[7],
            "referred_by": row[8],
            "referral_count": row[9] or 0,
            "referral_earned": row[10] or 0
        }
    else:
        referral_code = generate_referral_code(user_id)
        conn = get_db_connection()
        conn.execute("""
            INSERT INTO users (user_id, balance, total_generated, default_template, 
                             language, output_format, image_quality, layout_mode, referral_code)
            VALUES (?, 0, 0, 'temp1_color', 'en', 'pdf', 'high', 'mirrored', ?)
        """, (user_id, referral_code))
        conn.commit()
        conn.close()
        return {
            "balance": 0,
            "total_generated": 0,
            "default_template": "temp1_color",
            "language": "en",
            "output_format": "pdf",
            "image_quality": "high",
            "layout_mode": "mirrored",
            "referral_code": referral_code,
            "referred_by": None,
            "referral_count": 0,
            "referral_earned": 0
        }


def generate_referral_code(user_id: int) -> str:
    import hashlib
    return hashlib.md5(f"{user_id}_{time.time()}".encode()).hexdigest()[:8].upper()


def update_user_settings(user_id: int, setting: str, value: str):
    conn = get_db_connection()
    conn.execute(
        f"UPDATE users SET {setting} = ? WHERE user_id = ?", (value, user_id))
    conn.commit()
    conn.close()


def get_user_language(user_id: int) -> str:
    conn = get_db_connection()
    row = conn.execute(
        "SELECT language FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return row[0] if row else "en"


def get_translation(user_id: int, key: str, **kwargs) -> str:
    lang = get_user_language(user_id)
    text = LANGUAGES.get(lang, LANGUAGES['en']).get(
        key, LANGUAGES['en'].get(key, key))
    if kwargs:
        try:
            return text.format(**kwargs)
        except:
            return text
    return text


def update_balance(user_id: int, delta: int):
    conn = get_db_connection()
    conn.execute(
        "UPDATE users SET balance = balance + ? WHERE user_id = ?", (delta, user_id))
    conn.commit()
    conn.close()


def update_total_generated(user_id: int):
    conn = get_db_connection()
    conn.execute(
        "UPDATE users SET total_generated = total_generated + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def set_default_template(user_id: int, template_name: str):
    conn = get_db_connection()
    conn.execute("UPDATE users SET default_template = ? WHERE user_id = ?",
                 (template_name, user_id))
    conn.commit()
    conn.close()


def set_user_language(user_id: int, lang: str):
    conn = get_db_connection()
    conn.execute(
        "UPDATE users SET language = ? WHERE user_id = ?", (lang, user_id))
    conn.commit()
    conn.close()


def get_all_users():
    conn = get_db_connection()
    rows = conn.execute("SELECT user_id FROM users").fetchall()
    conn.close()
    return [row[0] for row in rows]


def create_payment(user_id: int, tx_id: str, amount: int, credits: int = 0):
    conn = get_db_connection()
    conn.execute("INSERT OR IGNORE INTO payments (tx_id, user_id, amount, credits) VALUES (?, ?, ?, ?)",
                 (tx_id, user_id, amount, credits))
    conn.commit()
    conn.close()


def mark_payment_approved(tx_id: str):
    conn = get_db_connection()
    conn.execute(
        "UPDATE payments SET status = 'approved' WHERE tx_id = ?", (tx_id,))
    conn.commit()
    conn.close()


def mark_payment_rejected(tx_id: str):
    conn = get_db_connection()
    conn.execute(
        "UPDATE payments SET status = 'rejected' WHERE tx_id = ?", (tx_id,))
    conn.commit()
    conn.close()


def get_payment(tx_id: str):
    conn = get_db_connection()
    row = conn.execute(
        "SELECT user_id, amount, credits, status FROM payments WHERE tx_id = ?", (tx_id,)).fetchone()
    conn.close()
    if row:
        return {"user_id": row[0], "amount": row[1], "credits": row[2], "status": row[3]}
    return None

# ============ REFERRAL FUNCTIONS ============


def process_referral(referrer_id: int, referred_id: int) -> bool:
    conn = get_db_connection()
    try:
        existing = conn.execute(
            "SELECT 1 FROM referrals WHERE referred_id = ?", (referred_id,)).fetchone()
        if existing:
            conn.close()
            return False
        conn.execute("INSERT INTO referrals (referrer_id, referred_id) VALUES (?, ?)",
                     (referrer_id, referred_id))
        conn.execute(
            "UPDATE users SET referral_count = referral_count + 1 WHERE user_id = ?", (referrer_id,))
        row = conn.execute(
            "SELECT referral_count, referral_earned FROM users WHERE user_id = ?", (referrer_id,)).fetchone()
        count = row[0] if row else 0
        earned = row[1] if row else 0
        reward_given = False
        if count >= REFERRAL_TARGET and earned == 0:
            update_balance(referrer_id, REFERRAL_REWARD)
            conn.execute(
                "UPDATE users SET referral_earned = 1 WHERE user_id = ?", (referrer_id,))
            reward_given = True
        conn.commit()
        conn.close()
        return reward_given
    except Exception as e:
        logger.error(f"Process referral error: {e}")
        conn.close()
        return False


def get_referral_stats(user_id: int) -> Dict:
    conn = get_db_connection()
    row = conn.execute(
        "SELECT referral_count, referral_earned FROM users WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    if row:
        return {"total": row[0] or 0, "earned": row[1] or 0, "progress": row[0] or 0, "target": REFERRAL_TARGET}
    return {"total": 0, "earned": 0, "progress": 0, "target": REFERRAL_TARGET}


def get_user_by_referral_code(code: str):
    if not code:
        return None
    conn = get_db_connection()
    row = conn.execute(
        "SELECT user_id FROM users WHERE referral_code = ?", (code,)).fetchone()
    conn.close()
    return row[0] if row else None


def get_referral_link(user_id: int) -> str:
    user = get_user(user_id)
    code = user.get("referral_code")
    if not code:
        code = generate_referral_code(user_id)
        conn = get_db_connection()
        conn.execute(
            "UPDATE users SET referral_code = ? WHERE user_id = ?", (code, user_id))
        conn.commit()
        conn.close()
    return f"https://t.me/{BOT_USERNAME}?start=ref_{code}"

# ============ HISTORY FUNCTIONS ============


def save_id_history(user_id, id_data, template_used, file_path, a4_path=None):
    conn = get_db_connection()
    try:
        conn.execute("""
            INSERT INTO id_history (user_id, request_id, en_name, am_name, fcn, fin, template_used, file_path, a4_path, data_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            id_data.get('request_id', ''),
            id_data.get('en_name', ''),
            id_data.get('am_name', ''),
            id_data.get('fcn', ''),
            id_data.get('fin', ''),
            template_used,
            file_path,
            a4_path,
            json.dumps(id_data)
        ))
        conn.commit()
        logger.info(
            f"✅ History saved for user {user_id}: {id_data.get('en_name', 'Unknown')}")
    except Exception as e:
        logger.error(f"Failed to save history: {e}")
    finally:
        conn.close()


def get_user_history(user_id, limit=20, offset=0):
    conn = get_db_connection()
    rows = conn.execute("""
        SELECT en_name, am_name, fcn, fin, generated_at, template_used, file_path, a4_path, request_id
        FROM id_history
        WHERE user_id = ?
        ORDER BY generated_at DESC
        LIMIT ? OFFSET ?
    """, (user_id, limit, offset)).fetchall()
    conn.close()
    return rows


def get_user_stats(user_id):
    conn = get_db_connection()
    total = conn.execute(
        "SELECT COUNT(*) FROM id_history WHERE user_id = ?", (user_id,)).fetchone()[0]
    today = conn.execute("""
        SELECT COUNT(*) FROM id_history 
        WHERE user_id = ? AND DATE(generated_at) = DATE('now')
    """, (user_id,)).fetchone()[0]
    conn.close()
    return {"total": total, "today": today}


def count_user_history(user_id):
    conn = get_db_connection()
    total = conn.execute(
        "SELECT COUNT(*) FROM id_history WHERE user_id = ?", (user_id,)).fetchone()[0]
    conn.close()
    return total

# ============ BULK PROCESSING FUNCTIONS ============


def create_bulk_job(user_id: int, total_files: int) -> str:
    job_id = str(uuid.uuid4())
    conn = get_db_connection()
    conn.execute("""
        INSERT INTO bulk_jobs (user_id, job_id, total_files, status)
        VALUES (?, ?, ?, 'pending')
    """, (user_id, job_id, total_files))
    conn.commit()
    conn.close()
    return job_id


def update_bulk_job(job_id: str, processed: int = None, status: str = None):
    conn = get_db_connection()
    updates = []
    params = []
    if processed is not None:
        updates.append("processed = ?")
        params.append(processed)
    if status is not None:
        updates.append("status = ?")
        params.append(status)
        if status == "completed":
            updates.append("completed_at = CURRENT_TIMESTAMP")
    if updates:
        query = f"UPDATE bulk_jobs SET {', '.join(updates)} WHERE job_id = ?"
        params.append(job_id)
        conn.execute(query, params)
        conn.commit()
    conn.close()


def get_bulk_job(job_id: str):
    conn = get_db_connection()
    row = conn.execute("""
        SELECT user_id, total_files, processed, status, created_at, completed_at
        FROM bulk_jobs WHERE job_id = ?
    """, (job_id,)).fetchone()
    conn.close()
    if row:
        return {
            "user_id": row[0],
            "total_files": row[1],
            "processed": row[2] or 0,
            "status": row[3],
            "created_at": row[4],
            "completed_at": row[5]
        }
    return None

# ============ HELPER FUNCTIONS ============


def image_to_base64(image_path: str) -> str:
    if not image_path or not os.path.exists(image_path):
        return ""
    try:
        with open(image_path, "rb") as f:
            return base64.b64encode(f.read()).decode('utf-8')
    except Exception as e:
        logger.error(f"Error converting image to Base64: {e}")
        return ""


def base64_to_image(base64_str: str, output_path: str) -> bool:
    if not base64_str:
        return False
    try:
        image_data = base64.b64decode(base64_str)
        with open(output_path, "wb") as f:
            f.write(image_data)
        return True
    except Exception as e:
        logger.error(f"Error converting Base64 to image: {e}")
        return False


def is_report_expired(request_id):
    conn = get_db_connection()
    row = conn.execute(
        "SELECT created_epoch FROM last_generated WHERE request_id = ?", (request_id,)).fetchone()
    conn.close()
    if not row:
        return True
    created_epoch = row[0]
    if created_epoch is None:
        return True
    return (time.time() - created_epoch) > 600


def cleanup_expired_records():
    while True:
        time.sleep(3600)
        conn = get_db_connection()
        expiry_time = time.time() - 600
        try:
            deleted = conn.execute(
                "DELETE FROM last_generated WHERE created_epoch < ?", (expiry_time,))
            conn.commit()
            if deleted.rowcount > 0:
                logger.info(
                    f"Cleaned up {deleted.rowcount} expired last_generated records")
            old_reports = time.time() - (30 * 86400)
            deleted_reports = conn.execute(
                "DELETE FROM error_reports WHERE created_at < datetime(?, 'unixepoch')", (old_reports,))
            conn.commit()
            if deleted_reports.rowcount > 0:
                logger.info(
                    f"Cleaned up {deleted_reports.rowcount} old error_reports")
        except Exception as e:
            logger.warning(f"Failed to clean up expired records: {e}")
        finally:
            conn.close()


cleanup_thread = threading.Thread(target=cleanup_expired_records, daemon=True)
cleanup_thread.start()

# ============ GLOBAL ERROR HANDLER ============


async def global_error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    error_str = str(context.error).lower()
    ignore_patterns = [
        "message is not modified",
        "query is too old",
        "callback query expired",
        "message can't be deleted",
        "chat not found",
        "can't parse entities",
        "no such table",
    ]
    for pattern in ignore_patterns:
        if pattern in error_str:
            logger.debug(f"Ignored non-critical error: {context.error}")
            return
    logger.error(f"Unhandled error: {context.error}", exc_info=context.error)
    if update and hasattr(update, 'effective_user') and update.effective_user:
        try:
            user_id = update.effective_user.id
            text = get_translation(user_id, 'error_retry')
            await context.bot.send_message(chat_id=user_id, text=text)
        except Exception:
            pass

# ============ TELEGRAM APPLICATION ============
telegram_request = HTTPXRequest(
    connect_timeout=60.0,
    read_timeout=120.0,
    connection_pool_size=20
)

builder = Application.builder().token(TOKEN).request(telegram_request)
application = builder.build()
application.add_error_handler(global_error_handler)

# ============ BUTTON PATTERNS ============
UPLOAD_PATTERN = r'^📤 (Upload ID|መታወቂያ ስቀል|ID Galchi)$'
MY_IDS_PATTERN = r'^📂 (My IDs|መታወቂያዎቼ|ID\' koo)$'
WALLET_PATTERN = r'^💳 (Wallet|ቦርሳ|Kasaara)$'
TEMPLATES_PATTERN = r'^🎨 (Templates|አብነቶች|Template\'oota)$'
DEPOSIT_PATTERN = r'^➕ (Deposit|ገንዘብ አስገባ|Maallaqa kaa\'i)$'
BULK_PATTERN = r'^📊 (Bulk Process|በብዛት ማስኬድ|Baay\'inaan Hojii)$'
SETTINGS_PATTERN = r'^⚙️ (Settings|ቅንብሮች|Qindaa\'ina)$'
INVITE_PATTERN = r'^🎁 (Invite Friends|ጓደኞችን ጋብዝ|Hiriyoota Affaari)$'
DASHBOARD_PATTERN = r'^📱 (Dashboard|ዳሽቦርድ|Daashboordii)$'
SUPPORT_PATTERN = r'^👨‍💻 (Support|እርዳታ|Gargaarsa)$'

# ============ BUILD DYNAMIC KEYBOARD ============


def get_main_keyboard(user_id: int):
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton(get_translation(user_id, 'upload_id')),
             KeyboardButton(get_translation(user_id, 'my_ids'))],
            [KeyboardButton(get_translation(user_id, 'wallet')),
             KeyboardButton(get_translation(user_id, 'templates'))],
            [KeyboardButton(get_translation(user_id, 'deposit')),
             KeyboardButton(get_translation(user_id, 'bulk_process'))],
            [KeyboardButton(get_translation(user_id, 'settings')),
             KeyboardButton(get_translation(user_id, 'invite'))],
            [KeyboardButton(get_translation(user_id, 'dashboard'))],
            [KeyboardButton(get_translation(user_id, 'support'))],
        ],
        resize_keyboard=True,
        one_time_keyboard=False,
    )

# ============ CELERY JOB FUNCTIONS ============


async def check_job_status(job_id: str) -> dict:
    if not redis_client:
        return {'status': 'unknown', 'message': 'Redis not available'}

    status_key = JOB_STATUS_KEY.format(job_id=job_id)
    status_data = redis_client.get(status_key)

    if not status_data:
        return {'status': 'expired', 'message': 'Job expired or not found'}

    try:
        status = json.loads(status_data)
    except:
        return {'status': 'error', 'message': 'Invalid status data'}

    if status.get('status') == 'completed':
        result_key = JOB_RESULT_KEY.format(job_id=job_id)
        result_data = redis_client.get(result_key)
        if result_data:
            try:
                status['result'] = json.loads(result_data)
            except:
                pass

    return status


async def start_job(user_id: int, job_type: str, data: dict) -> str:
    """Start a background job and return job ID"""
    job_id = str(uuid.uuid4())

    if redis_client:
        status_data = {
            'status': 'pending',
            'job_type': job_type,
            'user_id': user_id,
            'created_at': time.time(),
            'progress': 0,
            'message': 'Job queued...'
        }
        try:
            redis_client.setex(
                JOB_STATUS_KEY.format(job_id=job_id),
                3600,
                json.dumps(status_data)
            )
        except Exception as e:
            logger.warning(f"Redis setex error: {e}")

    if job_type == 'pdf':
        task = process_pdf_task.delay(
            user_id=user_id,
            file_path=data['file_path'],
            template=data['template'],
            color_mode=data['color_mode'],
            job_id=job_id
        )
    elif job_type == 'screenshot':
        task = process_screenshot_task.delay(
            user_id=user_id,
            front_path=data['front_path'],
            back_path=data['back_path'],
            template=data['template'],
            color_mode=data['color_mode'],
            job_id=job_id
        )
    elif job_type == 'bulk':
        task = process_bulk_task.delay(
            user_id=user_id,
            file_paths=data['file_paths'],
            template=data['template'],
            color_mode=data['color_mode'],
            job_id=job_id
        )
    else:
        raise ValueError(f"Unknown job type: {job_type}")

    # Use hash for O(1) lookup
    if redis_client:
        try:
            redis_client.hset("task_to_job_map", task.id, job_id)
            redis_client.expire("task_to_job_map", 3600)
        except Exception as e:
            logger.warning(f"Redis hset error: {e}")

    logger.info(f"Started job {job_id} with task {task.id} for user {user_id}")
    return job_id

# ============ HANDLERS ============


async def log_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message and update.message.text:
        logger.info(f"📝 Text: '{update.message.text}'")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    first_name = update.effective_user.first_name or "User"
    user = get_user(user_id)

    if update.message.text and ' ' in update.message.text:
        deep_link = update.message.text.split(' ', 1)[1]
        if deep_link.startswith('ref_'):
            referral_code = deep_link.replace('ref_', '')
            referrer_id = get_user_by_referral_code(referral_code)
            if referrer_id and referrer_id != user_id:
                try:
                    reward_given = process_referral(referrer_id, user_id)
                    if not user.get('referred_by'):
                        conn = get_db_connection()
                        conn.execute(
                            "UPDATE users SET referred_by = ? WHERE user_id = ?", (referrer_id, user_id))
                        conn.commit()
                        conn.close()
                        lang = get_user_language(referrer_id)
                        progress = get_referral_stats(referrer_id)
                        try:
                            join_msg = LANGUAGES[lang]['invite_joined'].format(
                                name=first_name, progress=progress['progress'], target=REFERRAL_TARGET
                            )
                            await context.bot.send_message(chat_id=referrer_id, text=join_msg, parse_mode="Markdown")
                            if reward_given:
                                user_data = get_user(referrer_id)
                                reward_msg = LANGUAGES[lang]['invite_reward'].format(
                                    target=REFERRAL_TARGET, reward=REFERRAL_REWARD, balance=user_data[
                                        'balance']
                                )
                                await context.bot.send_message(chat_id=referrer_id, text=reward_msg, parse_mode="Markdown")
                        except Exception as e:
                            logger.error(
                                f"Failed to send referral notification: {e}")
                except Exception as e:
                    logger.error(f"Referral processing error: {e}")

    welcome_text = LANGUAGES['en']['welcome'].format(name=first_name)
    keyboard = [
        [
            InlineKeyboardButton("🇬🇧 English", callback_data="lang_en"),
            InlineKeyboardButton("🇪🇹 አማርኛ", callback_data="lang_am"),
            InlineKeyboardButton("🇪🇹 Afaan Oromoo", callback_data="lang_om")
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(welcome_text, reply_markup=reply_markup)


async def language_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    language = query.data.replace("lang_", "")
    set_user_language(user_id, language)
    try:
        await query.message.delete()
    except:
        pass
    await show_template_selection(chat_id=user_id, context=context)


async def show_template_selection(chat_id: int, context: ContextTypes.DEFAULT_TYPE):
    bot = context.bot
    user_id = chat_id
    user = get_user(user_id)
    current_template = user["default_template"]
    lang = user["language"]
    templates = [
        ("📄 Template 1", "templates/preview1.jpg", "temp1"),
        ("🎨 Template 2", "templates/preview2.jpg", "temp2"),
        ("📱 Template 3", "templates/preview3.jpg", "temp3"),
    ]
    context.user_data["initial_template_messages"] = []
    for label, img_path, base_suffix in templates:
        color_suffix = f"{base_suffix}_color"
        grey_suffix = f"{base_suffix}_grey"
        color_selected = (current_template == color_suffix)
        grey_selected = (current_template == grey_suffix)
        color_text = LANGUAGES[lang]['color_mode'] + \
            (" ✅" if color_selected else "")
        grey_text = LANGUAGES[lang]['grey_mode'] + \
            (" ✅" if grey_selected else "")
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(color_text, callback_data=f"set_{color_suffix}"),
             InlineKeyboardButton(grey_text, callback_data=f"set_{grey_suffix}")]
        ])
        if os.path.exists(img_path):
            with open(img_path, "rb") as img:
                msg = await bot.send_photo(
                    chat_id=user_id,
                    photo=img,
                    caption=f"**{label}**\n{LANGUAGES[lang]['template_choose']}",
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
        else:
            caption = LANGUAGES[lang]['template_preview'].format(label=label)
            msg = await bot.send_message(chat_id=user_id, text=caption, reply_markup=keyboard)
        context.user_data["initial_template_messages"].append({
            "msg_id": msg.message_id,
            "base_suffix": base_suffix,
            "label": label,
            "img_path": img_path if os.path.exists(img_path) else None,
            "color_suffix": color_suffix,
            "grey_suffix": grey_suffix
        })
        await asyncio.sleep(0.3)


async def initial_template_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    new_template = data.replace("set_", "")
    user_id = query.from_user.id
    lang = get_user_language(user_id)
    current_template = get_user(user_id)["default_template"]
    if new_template == current_template:
        await query.answer(LANGUAGES[lang]['already_selected'], show_alert=False)
        return
    if data in context.user_data.get("processed_templates", []):
        return
    context.user_data.setdefault("processed_templates", []).append(data)
    await query.answer()
    set_default_template(user_id, new_template)
    messages = context.user_data.get("initial_template_messages", [])
    for msg_info in messages:
        base_suffix = msg_info["base_suffix"]
        label = msg_info["label"]
        color_suffix = msg_info["color_suffix"]
        grey_suffix = msg_info["grey_suffix"]
        color_selected = (new_template == color_suffix)
        grey_selected = (new_template == grey_suffix)
        color_text = LANGUAGES[lang]['color_mode'] + \
            (" ✅" if color_selected else "")
        grey_text = LANGUAGES[lang]['grey_mode'] + \
            (" ✅" if grey_selected else "")
        new_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(color_text, callback_data=f"set_{color_suffix}"),
             InlineKeyboardButton(grey_text, callback_data=f"set_{grey_suffix}")]
        ])
        try:
            if msg_info.get("img_path"):
                await context.bot.edit_message_caption(
                    chat_id=user_id,
                    message_id=msg_info["msg_id"],
                    caption=f"**{label}**\n{LANGUAGES[lang]['template_choose']}",
                    reply_markup=new_keyboard,
                    parse_mode="Markdown"
                )
            else:
                await context.bot.edit_message_text(
                    chat_id=user_id,
                    message_id=msg_info["msg_id"],
                    text=LANGUAGES[lang]['template_preview'].format(
                        label=label),
                    reply_markup=new_keyboard
                )
        except Exception as e:
            if "not modified" not in str(e).lower():
                logger.warning(f"Could not edit template message: {e}")
    if data in context.user_data.get("processed_templates", []):
        context.user_data["processed_templates"].remove(data)
    for msg_info in messages:
        try:
            await context.bot.delete_message(chat_id=user_id, message_id=msg_info["msg_id"])
        except:
            pass
    sticker_file_id = "CAACAgQAAxkBAAIRXGoMtiL6dxUWBlYkyaG4gtEBRonsAAJ4HQAClPZYUOogLjaoDQM3OwQ"
    await context.bot.send_sticker(chat_id=user_id, sticker=sticker_file_id)
    text = LANGUAGES[lang]['template_selected']
    keyboard = get_main_keyboard(user_id)
    await context.bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard)


async def view_history_web_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    webapp_url = os.getenv("WEBAPP_URL", "https://your-domain.com/dashboard")
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📱 Open Dashboard", web_app={"url": webapp_url})]
    ])
    await query.message.reply_text(
        "📂 **Open Your Dashboard**\n\nView all your IDs, download them, and manage your account.",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

# ============ MAIN MENU HANDLERS ============


async def handle_upload_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = get_translation(user_id, 'upload_prompt')
    await update.message.reply_text(text)


async def handle_my_ids(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_language(user_id)
    page = context.user_data.get("history_page", 0)
    limit = 10
    history = get_user_history(user_id, limit=limit, offset=page * limit)
    total = count_user_history(user_id)
    stats = get_user_stats(user_id)
    if not history:
        text = LANGUAGES[lang]['no_ids']
        await update.message.reply_text(text, parse_mode="Markdown")
        return
    response = LANGUAGES[lang]['my_ids_header'].format(
        total=stats['total'], today=stats['today'])
    for i, row in enumerate(history, 1):
        en_name = row[0] or "Unknown"
        fcn = row[2] or "N/A"
        date = row[4][:10] if row[4] else "Unknown"
        response += f"{page * limit + i}. **{en_name}**\n"
        response += f"   🆔 {fcn} | 📅 {date}\n\n"
    keyboard = []
    nav_buttons = []
    if page > 0:
        nav_buttons.append(InlineKeyboardButton(
            "⬅️", callback_data="history_prev"))
    nav_buttons.append(InlineKeyboardButton(
        f"{page + 1}/{((total - 1) // limit) + 1}", callback_data="history_current"))
    if (page + 1) * limit < total:
        nav_buttons.append(InlineKeyboardButton(
            "➡️", callback_data="history_next"))
    keyboard.append(nav_buttons)
    keyboard.append([InlineKeyboardButton(
        "📱 Web Dashboard", callback_data="view_history_web")])
    reply_markup = InlineKeyboardMarkup(keyboard) if keyboard else None
    await update.message.reply_text(response, parse_mode="Markdown", reply_markup=reply_markup)


async def history_navigation_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data.replace("history_", "")
    user_id = query.from_user.id
    if action == "prev":
        context.user_data["history_page"] = context.user_data.get(
            "history_page", 0) - 1
    elif action == "next":
        context.user_data["history_page"] = context.user_data.get(
            "history_page", 0) + 1
    elif action == "current":
        page = context.user_data.get("history_page", 0)
        total = count_user_history(user_id)
        limit = 10
        await query.edit_message_text(f"📊 Page {page + 1} of {((total - 1) // limit) + 1}")
        return
    await handle_my_ids(update, context)


async def handle_wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = get_user(user_id)
    lang = get_user_language(user_id)
    text = LANGUAGES[lang]['wallet_info'].format(
        balance=user['balance'], total=user['total_generated'])
    await update.message.reply_text(text, parse_mode="Markdown")


async def handle_deposit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = get_translation(user_id, 'deposit_info')
    await update.message.reply_text(text, parse_mode="Markdown")


async def handle_templates(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_language(user_id)
    current_template = get_user(user_id)["default_template"]
    templates = [
        ("📄 Template 1", "templates/preview1.jpg", "temp1"),
        ("🎨 Template 2", "templates/preview2.jpg", "temp2"),
        ("📱 Template 3", "templates/preview3.jpg", "temp3"),
    ]
    context.user_data["template_messages"] = []
    for label, img_path, base_suffix in templates:
        color_suffix = f"{base_suffix}_color"
        grey_suffix = f"{base_suffix}_grey"
        color_selected = (current_template == color_suffix)
        grey_selected = (current_template == grey_suffix)
        color_text = LANGUAGES[lang]['color_mode'] + \
            (" ✅" if color_selected else "")
        grey_text = LANGUAGES[lang]['grey_mode'] + \
            (" ✅" if grey_selected else "")
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(color_text, callback_data=f"set_existing_{color_suffix}"),
             InlineKeyboardButton(grey_text, callback_data=f"set_existing_{grey_suffix}")]
        ])
        if os.path.exists(img_path):
            with open(img_path, "rb") as img:
                msg = await update.message.reply_photo(
                    photo=img,
                    caption=f"**{label}**\n{LANGUAGES[lang]['template_choose']}",
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
        else:
            caption = LANGUAGES[lang]['template_preview'].format(label=label)
            msg = await update.message.reply_text(caption, reply_markup=keyboard)
        context.user_data["template_messages"].append({
            "msg_id": msg.message_id,
            "base_suffix": base_suffix,
            "label": label,
            "img_path": img_path if os.path.exists(img_path) else None,
            "color_suffix": color_suffix,
            "grey_suffix": grey_suffix
        })
        await asyncio.sleep(0.3)


async def set_existing_template_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    new_template = data.replace("set_existing_", "")
    user_id = query.from_user.id
    lang = get_user_language(user_id)
    current_template = get_user(user_id)["default_template"]
    if new_template == current_template:
        await query.answer(LANGUAGES[lang]['already_selected'], show_alert=False)
        return
    if data in context.user_data.get("processed_existing_templates", []):
        return
    context.user_data.setdefault(
        "processed_existing_templates", []).append(data)
    await query.answer()
    set_default_template(user_id, new_template)
    messages = context.user_data.get("template_messages", [])
    for msg_info in messages:
        base_suffix = msg_info["base_suffix"]
        label = msg_info["label"]
        color_suffix = msg_info["color_suffix"]
        grey_suffix = msg_info["grey_suffix"]
        color_selected = (new_template == color_suffix)
        grey_selected = (new_template == grey_suffix)
        color_text = LANGUAGES[lang]['color_mode'] + \
            (" ✅" if color_selected else "")
        grey_text = LANGUAGES[lang]['grey_mode'] + \
            (" ✅" if grey_selected else "")
        new_keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(color_text, callback_data=f"set_existing_{color_suffix}"),
             InlineKeyboardButton(grey_text, callback_data=f"set_existing_{grey_suffix}")]
        ])
        try:
            if msg_info.get("img_path"):
                await context.bot.edit_message_caption(
                    chat_id=user_id,
                    message_id=msg_info["msg_id"],
                    caption=f"**{label}**\n{LANGUAGES[lang]['template_choose']}",
                    reply_markup=new_keyboard,
                    parse_mode="Markdown"
                )
            else:
                await context.bot.edit_message_text(
                    chat_id=user_id,
                    message_id=msg_info["msg_id"],
                    text=LANGUAGES[lang]['template_preview'].format(
                        label=label),
                    reply_markup=new_keyboard
                )
        except Exception as e:
            if "not modified" not in str(e).lower():
                logger.warning(f"Could not edit template message: {e}")
    if data in context.user_data.get("processed_existing_templates", []):
        context.user_data["processed_existing_templates"].remove(data)
    for msg_info in messages:
        try:
            await context.bot.delete_message(chat_id=user_id, message_id=msg_info["msg_id"])
        except:
            pass
    sticker_file_id = "CAACAgQAAxkBAAIRXGoMtiL6dxUWBlYkyaG4gtEBRonsAAJ4HQAClPZYUOogLjaoDQM3OwQ"
    await context.bot.send_sticker(chat_id=user_id, sticker=sticker_file_id)
    text = LANGUAGES[lang]['settings_saved']
    keyboard = get_main_keyboard(user_id)
    await context.bot.send_message(chat_id=user_id, text=text, reply_markup=keyboard)

# ============ BULK PROCESSING ============


async def handle_bulk_process(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_language(user_id)
    user = get_user(user_id)
    if user["balance"] <= 0:
        await update.message.reply_text(LANGUAGES[lang]['no_credits'])
        return
    text = LANGUAGES[lang]['bulk_prompt']
    keyboard = []
    row = []
    for i in range(1, 11):
        row.append(InlineKeyboardButton(str(i), callback_data=f"bulk_{i}"))
        if len(row) == 5:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton(
        "❌ Cancel", callback_data="bulk_cancel")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)


async def bulk_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "bulk_cancel":
        await query.edit_message_text("❌ Bulk processing cancelled.")
        return
    count = int(query.data.replace("bulk_", ""))
    user_id = query.from_user.id
    lang = get_user_language(user_id)
    user = get_user(user_id)
    if user["balance"] < count:
        await query.edit_message_text(f"❌ Not enough credits. You have {user['balance']} credits but need {count}.")
        return
    job_id = create_bulk_job(user_id, count)
    context.user_data["bulk_job"] = job_id
    context.user_data["bulk_count"] = count
    context.user_data["bulk_processed"] = 0
    context.user_data["bulk_files"] = []
    text = LANGUAGES[lang]['bulk_processing'].format(count=count)
    await query.edit_message_text(text)
    context.user_data["awaiting_bulk"] = True
    await context.bot.send_message(
        chat_id=user_id,
        text=f"📤 Send me {count} PDF files one by one.\n\nI'll process them and send you the results.\n\nSend /cancel to stop."
    )


async def handle_bulk_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_language(user_id)
    if not context.user_data.get("awaiting_bulk"):
        return
    if not update.message.document or not update.message.document.mime_type == "application/pdf":
        await update.message.reply_text("❌ Please send a PDF file.")
        return
    job_id = context.user_data.get("bulk_job")
    if not job_id:
        await update.message.reply_text("❌ No bulk job found. Please start again.")
        context.user_data["awaiting_bulk"] = False
        return
    job = get_bulk_job(job_id)
    if not job or job["status"] == "completed":
        await update.message.reply_text("❌ This bulk job is already completed.")
        context.user_data["awaiting_bulk"] = False
        return
    total = job["total_files"]
    processed = job["processed"] + 1
    if processed > total:
        await update.message.reply_text(f"❌ You've already sent {total} files. Starting processing...")
        await process_bulk_files_async(update, context, job_id)
        return
    doc = update.message.document
    file = await context.bot.get_file(doc.file_id)
    local_input = os.path.join(INPUT_DIR, f"bulk_{job_id}_{processed}.pdf")
    await file.download_to_drive(local_input)
    context.user_data.setdefault("bulk_files", []).append(local_input)
    update_bulk_job(job_id, processed=processed)
    await update.message.reply_text(f"✅ Received {processed}/{total}. Continue sending PDFs.")
    if processed >= total:
        await process_bulk_files_async(update, context, job_id)


# Replace the process_bulk_files_async function in bot.py

async def process_bulk_files_async(update: Update, context: ContextTypes.DEFAULT_TYPE, job_id: str):
    user_id = update.effective_user.id
    lang = get_user_language(user_id)
    job = get_bulk_job(job_id)
    if not job:
        return
    files = context.user_data.get("bulk_files", [])
    total = len(files)
    update_bulk_job(job_id, status="processing")
    status_msg = await context.bot.send_message(
        chat_id=user_id,
        text=f"⏳ Processing {total} files... This may take a few minutes."
    )
    user = get_user(user_id)

    # Start the Celery bulk job - THIS RETURNS THE CELERY JOB ID
    celery_job_id = await start_job(
        user_id=user_id,
        job_type='bulk',
        data={
            'file_paths': files,
            'template': user['default_template'],
            'color_mode': "grey" if "_grey" in user['default_template'] else "color"
        }
    )

    # Store the CELERY job ID, not the database job_id
    context.user_data['current_job'] = celery_job_id

    # Poll the CELERY job ID
    await poll_bulk_job_status(update, context, celery_job_id, job_id, user_id, lang, total, status_msg)


async def poll_bulk_job_status(update: Update, context: ContextTypes.DEFAULT_TYPE, celery_job_id: str, db_job_id: str, user_id: int, lang: str, total: int, status_msg):
    """Poll the Celery bulk job status"""
    start_time = time.time()
    last_status = ""

    for attempt in range(300):  # 5 minutes max
        await asyncio.sleep(2)  # Check every 2 seconds

        # Check the CELERY job status
        status = await check_job_status(celery_job_id)
        current_status = status.get('status', 'unknown')
        message = status.get('message', '')

        # Update status message
        if current_status != last_status:
            try:
                if current_status == 'pending':
                    elapsed = int(time.time() - start_time)
                    text = LANGUAGES[lang]['job_pending'].format(
                        message=message, time=elapsed)
                    await status_msg.edit_text(text, parse_mode="Markdown")
                elif current_status == 'processing':
                    text = LANGUAGES[lang]['job_processing'].format(
                        message=message)
                    await status_msg.edit_text(text, parse_mode="Markdown")
                elif current_status == 'completed':
                    result = status.get('result', {})
                    await handle_bulk_completion(update, context, status_msg, result, db_job_id, user_id, lang, total)
                    return
                elif current_status == 'failed':
                    error = status.get('result', {}).get(
                        'error', 'Unknown error')
                    text = LANGUAGES[lang]['job_failed'].format(error=error)
                    await status_msg.edit_text(text, parse_mode="Markdown")
                    context.user_data.pop('current_job', None)
                    context.user_data["awaiting_bulk"] = False
                    return
                elif current_status == 'expired':
                    await status_msg.edit_text("⚠️ Job expired or not found.")
                    context.user_data.pop('current_job', None)
                    context.user_data["awaiting_bulk"] = False
                    return
                last_status = current_status
            except Exception as e:
                logger.debug(f"Status update error: {e}")

        if current_status in ['completed', 'failed', 'expired']:
            break

    if last_status not in ['completed', 'failed', 'expired']:
        try:
            await status_msg.edit_text(LANGUAGES[lang]['job_timeout'], parse_mode="Markdown")
        except:
            pass
        context.user_data.pop('current_job', None)
        context.user_data["awaiting_bulk"] = False


async def handle_bulk_completion(update: Update, context: ContextTypes.DEFAULT_TYPE, status_msg, result: dict, db_job_id: str, user_id: int, lang: str, total: int):
    """Handle bulk job completion - FIXED: saves to last_generated table"""
    try:
        successful = result.get('successful', 0)
        results = result.get('results', [])

        # Update database job status
        update_bulk_job(db_job_id, status="completed")

        # Send completion message
        text = LANGUAGES[lang]['bulk_complete'].format(
            successful=successful, total=total)
        await status_msg.edit_text(text)

        # Send each ID file
        for idx, res in enumerate(results, 1):
            if res.get('success'):
                output_path = res.get('output_path')
                a4_path = res.get('a4_path')
                request_id = res.get('request_id')
                data_json = res.get('data_json', '{}')
                id_data = json.loads(data_json)

                # Save to history
                save_id_history(user_id, id_data, 'template',
                                output_path, a4_path)

                # ✅ CRITICAL: Save to last_generated for Report Error button
                conn = get_db_connection()
                try:
                    conn.execute("""
                        INSERT OR REPLACE INTO last_generated 
                        (request_id, user_id, data_json, template_path, color_mode,
                         created_epoch, output_path, a4_path)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """, (
                        request_id,
                        user_id,
                        data_json,
                        res.get('template', ''),
                        res.get('color_mode', ''),
                        time.time(),  # ✅ CRITICAL: Set the timestamp!
                        output_path,
                        a4_path
                    ))
                    conn.commit()
                except Exception as db_err:
                    logger.error(f"Failed to update last_generated: {db_err}")
                finally:
                    conn.close()

                # Deduct credit for each successful ID (if not admin)
                if user_id != ADMIN_CHAT_ID:
                    update_balance(user_id, -1)
                    update_total_generated(user_id)

                # Send the ID file
                error_keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        LANGUAGES[lang]['report_error'],
                        callback_data=f"report_error_{request_id}"
                    )
                ]])

                if output_path and os.path.exists(output_path):
                    with open(output_path, "rb") as f:
                        await context.bot.send_document(
                            chat_id=user_id,
                            document=f,
                            caption=f"✅ ID {idx}/{total} ready!",
                            reply_markup=error_keyboard
                        )

                if a4_path and os.path.exists(a4_path):
                    with open(a4_path, "rb") as f:
                        await context.bot.send_document(
                            chat_id=user_id,
                            document=f,
                            caption=f"🖨️ A4 layout {idx}/{total}"
                        )

                # Clean up
                for path in [output_path, a4_path]:
                    if path and os.path.exists(path):
                        try:
                            os.remove(path)
                        except:
                            pass

        # Show final balance
        if user_id != ADMIN_CHAT_ID:
            new_balance = get_user(user_id)["balance"]
            await context.bot.send_message(
                chat_id=user_id,
                text=f"💳 Remaining credits: {new_balance}"
            )

        context.user_data.pop('current_job', None)
        context.user_data["awaiting_bulk"] = False
        context.user_data["bulk_job"] = None
        context.user_data["bulk_files"] = []

    except Exception as e:
        logger.error(f"Error handling bulk completion: {e}", exc_info=True)
        await status_msg.edit_text("❌ Error delivering some IDs. Please check your history.")
        context.user_data.pop('current_job', None)
        context.user_data["awaiting_bulk"] = False

# ============ SETTINGS ============


async def handle_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_language(user_id)
    text = LANGUAGES[lang]['settings_prompt']
    keyboard = [
        [InlineKeyboardButton(
            "📄 Output Format", callback_data="settings_format")],
        [InlineKeyboardButton(
            "🎨 Image Quality", callback_data="settings_quality")],
        [InlineKeyboardButton(
            "🖨️ Layout Mode", callback_data="settings_layout")],
        [InlineKeyboardButton(
            "🎨 Templates", callback_data="settings_templates")],
        [InlineKeyboardButton("❌ Close", callback_data="settings_close")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)


async def settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = get_user_language(user_id)
    user = get_user(user_id)

    if query.data == "settings_format":
        text = LANGUAGES[lang]['settings_format']
        current = user.get("output_format", "pdf")
        keyboard = [
            [InlineKeyboardButton(
                "📄 PDF" + (" ✅" if current == "pdf" else ""), callback_data="set_format_pdf")],
            [InlineKeyboardButton(
                "🖼️ PNG" + (" ✅" if current == "png" else ""), callback_data="set_format_png")],
            [InlineKeyboardButton(
                "📷 JPG" + (" ✅" if current == "jpg" else ""), callback_data="set_format_jpg")],
            [InlineKeyboardButton("🔙 Back", callback_data="settings_back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    elif query.data == "settings_quality":
        text = LANGUAGES[lang]['settings_quality']
        current = user.get("image_quality", "high")
        keyboard = [
            [InlineKeyboardButton(
                "🔴 High" + (" ✅" if current == "high" else ""), callback_data="set_quality_high")],
            [InlineKeyboardButton("🟡 Medium" + (" ✅" if current ==
                                  "medium" else ""), callback_data="set_quality_medium")],
            [InlineKeyboardButton(
                "🟢 Low" + (" ✅" if current == "low" else ""), callback_data="set_quality_low")],
            [InlineKeyboardButton("🔙 Back", callback_data="settings_back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    elif query.data == "settings_layout":
        text = LANGUAGES[lang]['settings_layout']
        current = user.get("layout_mode", "mirrored")
        keyboard = [
            [InlineKeyboardButton("🔄 Mirrored (A4)" + (" ✅" if current ==
                                  "mirrored" else ""), callback_data="set_layout_mirrored")],
            [InlineKeyboardButton("📄 Normal" + (" ✅" if current ==
                                  "normal" else ""), callback_data="set_layout_normal")],
            [InlineKeyboardButton("🔙 Back", callback_data="settings_back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(text, parse_mode="Markdown", reply_markup=reply_markup)
    elif query.data == "settings_templates":
        await query.message.delete()
        await handle_templates(update, context)
    elif query.data == "settings_back":
        await query.message.delete()
        await handle_settings(update, context)
    elif query.data == "settings_close":
        await query.message.delete()
        keyboard = get_main_keyboard(user_id)
        await context.bot.send_message(chat_id=user_id, text=LANGUAGES[lang]['settings_saved'], reply_markup=keyboard)
    elif query.data.startswith("set_format_"):
        format_type = query.data.replace("set_format_", "")
        update_user_settings(user_id, "output_format", format_type)
        await query.edit_message_text(f"✅ Format set to {format_type.upper()}")
        await asyncio.sleep(1)
        await settings_callback(update, context)
    elif query.data.startswith("set_quality_"):
        quality = query.data.replace("set_quality_", "")
        update_user_settings(user_id, "image_quality", quality)
        await query.edit_message_text(f"✅ Quality set to {quality}")
        await asyncio.sleep(1)
        await settings_callback(update, context)
    elif query.data.startswith("set_layout_"):
        layout = query.data.replace("set_layout_", "")
        update_user_settings(user_id, "layout_mode", layout)
        await query.edit_message_text(f"✅ Layout set to {layout}")
        await asyncio.sleep(1)
        await settings_callback(update, context)

# ============ INVITE ============


async def handle_invite(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_language(user_id)
    stats = get_referral_stats(user_id)
    link = get_referral_link(user_id)
    user = get_user(user_id)
    text = LANGUAGES[lang]['invite_prompt'].format(
        reward=REFERRAL_REWARD,
        target=REFERRAL_TARGET,
        total=stats['total'],
        progress=stats['progress'],
        earned=stats['earned']
    )
    share_text = LANGUAGES[lang]['invite_share_text'].format(link=link)
    keyboard = [
        [InlineKeyboardButton("📤 Share Link", switch_inline_query=share_text)],
        [InlineKeyboardButton("📊 View Stats", callback_data="invite_stats")],
        [InlineKeyboardButton("📋 Copy Link", callback_data="invite_copy")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)


async def invite_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    lang = get_user_language(user_id)
    if query.data == "invite_share":
        link = get_referral_link(user_id)
        share_text = LANGUAGES[lang]['invite_share_text'].format(link=link)
        await query.edit_message_text(share_text)
    elif query.data == "invite_stats":
        stats = get_referral_stats(user_id)
        text = f"📊 **Referral Stats**\n\n• Total Referrals: {stats['total']}\n• Progress: {stats['progress']}/{stats['target']}\n• IDs Earned: {stats['earned']}\n\nKeep sharing to earn more!"
        await query.edit_message_text(text, parse_mode="Markdown")
    elif query.data == "invite_copy":
        link = get_referral_link(user_id)
        await query.edit_message_text(f"📋 **Your referral link:**\n\n`{link}`\n\nShare this link with your friends!")

# ============ DASHBOARD ============


async def handle_dashboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_language(user_id)
    webapp_url = os.getenv("WEBAPP_URL", "https://your-domain.com/dashboard")
    text = LANGUAGES[lang]['dashboard_prompt']
    keyboard = [
        [InlineKeyboardButton("📱 Open Dashboard", web_app={
                              "url": webapp_url})],
        [InlineKeyboardButton("📊 My Stats", callback_data="dashboard_stats")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(text, parse_mode="Markdown", reply_markup=reply_markup)


async def dashboard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)
    stats = get_user_stats(user_id)
    if query.data == "dashboard_stats":
        text = f"📊 **Your Stats**\n\n"
        text += f"💳 Balance: {user['balance']}\n"
        text += f"📈 Total IDs: {stats['total']}\n"
        text += f"📅 Today: {stats['today']}\n"
        text += f"🎨 Template: {user['default_template']}\n"
        text += f"📄 Format: {user.get('output_format', 'pdf')}\n"
        text += f"🎨 Quality: {user.get('image_quality', 'high')}\n"
        text += f"🖨️ Layout: {user.get('layout_mode', 'mirrored')}\n"
        referral_stats = get_referral_stats(user_id)
        text += f"\n🎁 Referrals: {referral_stats['total']}\n"
        text += f"🏆 IDs Earned: {referral_stats['earned']}\n"
        await query.edit_message_text(text, parse_mode="Markdown")

# ============ SUPPORT ============

SUPPORT_STATE = 1
ticket_map = {}


async def handle_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = get_translation(user_id, 'support_info')
    await update.message.reply_text(text, parse_mode="Markdown")
    return SUPPORT_STATE


async def support_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    ticket_id = str(uuid.uuid4())[:8]
    ticket_map[ticket_id] = user_id
    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=f"📩 **Ticket #{ticket_id}**\nFrom: {user_id}\n\n{update.message.text}",
        parse_mode="Markdown"
    )
    text = get_translation(user_id, 'support_sent')
    await update.message.reply_text(text)
    return ConversationHandler.END


async def cancel_support(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = get_translation(user_id, 'support_cancelled')
    await update.message.reply_text(text)
    return ConversationHandler.END


async def admin_reply_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID or not update.message.reply_to_message:
        return
    match = re.search(r"Ticket #(\w+)", update.message.reply_to_message.text)
    if not match:
        return
    ticket_id = match.group(1)
    user_id = ticket_map.get(ticket_id)
    if user_id:
        await context.bot.send_message(
            chat_id=user_id,
            text=f"👨‍💻 **Admin reply:**\n{update.message.text}",
            parse_mode="Markdown"
        )
        await update.message.reply_text(f"✅ Reply sent to user {user_id}")
        del ticket_map[ticket_id]

# ============ BROADCAST ============

BROADCAST_PHOTO_STATE = 1


async def broadcast_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("Unauthorized.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /broadcast <message>")
        return
    text = " ".join(context.args)
    users = get_all_users()
    success = 0
    keyboard = [
        [InlineKeyboardButton("💳 Wallet", callback_data="broadcast_wallet"),
         InlineKeyboardButton("➕ Deposit", callback_data="broadcast_deposit"),
         InlineKeyboardButton("🎨 Templates", callback_data="broadcast_templates")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    for uid in users:
        try:
            await context.bot.send_message(chat_id=uid, text=f"📢 {text}", reply_markup=reply_markup)
            success += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"Failed to send broadcast to {uid}: {e}")
    await update.message.reply_text(f"✅ Broadcast sent to {success} out of {len(users)} users.")


async def broadcast_photo_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("Unauthorized.")
        return ConversationHandler.END
    await update.message.reply_text("📸 Send me the photo you want to broadcast to all users.\n\nYou can also add a caption.\n\nSend /cancel to cancel.")
    return BROADCAST_PHOTO_STATE


async def broadcast_photo_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_CHAT_ID:
        await update.message.reply_text("Unauthorized.")
        return ConversationHandler.END
    if not update.message.photo:
        await update.message.reply_text("Please send a photo.")
        return BROADCAST_PHOTO_STATE
    caption = update.message.caption or ""
    photo = update.message.photo[-1]
    users = get_all_users()
    success = 0
    keyboard = [
        [InlineKeyboardButton("💳 Wallet", callback_data="broadcast_wallet"),
         InlineKeyboardButton("➕ Deposit", callback_data="broadcast_deposit"),
         InlineKeyboardButton("🎨 Templates", callback_data="broadcast_templates")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    status_msg = await update.message.reply_text(f"⏳ Broadcasting photo to {len(users)} users...")
    for uid in users:
        try:
            await context.bot.send_photo(chat_id=uid, photo=photo.file_id, caption=caption, reply_markup=reply_markup)
            success += 1
            await asyncio.sleep(0.05)
        except Exception as e:
            logger.error(f"Failed to send broadcast to {uid}: {e}")
    await status_msg.edit_text(f"✅ Photo broadcast sent to {success} out of {len(users)} users.")
    return ConversationHandler.END


async def cancel_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Broadcast cancelled.")
    return ConversationHandler.END


async def broadcast_wallet_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    user = get_user(user_id)
    lang = get_user_language(user_id)
    text = LANGUAGES[lang]['wallet_info'].format(
        balance=user['balance'], total=user['total_generated'])
    await query.message.reply_text(text, parse_mode="Markdown")


async def broadcast_deposit_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    text = get_translation(user_id, 'deposit_info')
    await query.message.reply_text(text, parse_mode="Markdown")


async def broadcast_templates_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    await handle_templates(update, context)

# ============ FILE PROCESSING ============


async def run_in_thread(func, *args, **kwargs):
    return await asyncio.to_thread(partial(func, *args, **kwargs))


async def process_file_async(update: Update, context: ContextTypes.DEFAULT_TYPE, file_type="pdf"):
    user_id = update.effective_user.id
    lang = get_user_language(user_id)

    if context.user_data.get("awaiting_bulk"):
        await handle_bulk_pdf(update, context)
        return

    if user_id != ADMIN_CHAT_ID:
        user = get_user(user_id)
        if user["balance"] <= 0:
            await update.message.reply_text(LANGUAGES[lang]['no_credits'])
            return
        user_data = user
    else:
        user_data = {"balance": 999999, "default_template": get_user(user_id)[
            "default_template"]}

    status_msg = await update.message.reply_text(LANGUAGES[lang]['job_started'], parse_mode="Markdown")

    try:
        if file_type == "pdf":
            doc = update.message.document
            file = await context.bot.get_file(doc.file_id)
            local_input = os.path.join(
                INPUT_DIR, f"input_{uuid.uuid4().hex}.pdf")
            await file.download_to_drive(local_input)
            job_id = await start_job(
                user_id=user_id,
                job_type='pdf',
                data={
                    'file_path': local_input,
                    'template': user_data['default_template'],
                    'color_mode': "grey" if "_grey" in user_data['default_template'] else "color"
                }
            )
        else:
            if "front_path" not in context.user_data:
                if not update.message.photo:
                    await status_msg.edit_text("❌ Send a photo for the front side.")
                    return
                file = await context.bot.get_file(update.message.photo[-1].file_id)
                local_front = os.path.join(
                    INPUT_DIR, f"front_{uuid.uuid4().hex}.jpg")
                await file.download_to_drive(local_front)
                context.user_data["front_path"] = local_front
                await status_msg.edit_text("✅ Front received. Now send the **back** image.")
                return
            else:
                if not update.message.photo:
                    await status_msg.edit_text("❌ Send a photo for the back side.")
                    return
                file = await context.bot.get_file(update.message.photo[-1].file_id)
                local_back = os.path.join(
                    INPUT_DIR, f"back_{uuid.uuid4().hex}.jpg")
                await file.download_to_drive(local_back)
                front_path = context.user_data.pop("front_path")
                job_id = await start_job(
                    user_id=user_id,
                    job_type='screenshot',
                    data={
                        'front_path': front_path,
                        'back_path': local_back,
                        'template': user_data['default_template'],
                        'color_mode': "grey" if "_grey" in user_data['default_template'] else "color"
                    }
                )

        context.user_data['current_job'] = job_id
        asyncio.create_task(poll_job_status_background(
            update, context, status_msg, job_id, user_id, lang))

    except Exception as e:
        logger.error(f"Error starting job: {e}", exc_info=True)
        await status_msg.edit_text("❌ Error starting processing. Please try again.")


async def poll_job_status_background(update: Update, context: ContextTypes.DEFAULT_TYPE, status_msg, job_id: str, user_id: int, lang: str):
    """Poll job status in the background without blocking the bot"""
    start_time = time.time()
    last_status = ""
    last_update_time = 0

    for attempt in range(300):  # 5 minutes max
        await asyncio.sleep(2)  # Check every 2 seconds

        status = await check_job_status(job_id)
        current_status = status.get('status', 'unknown')
        message = status.get('message', '')

        # Update status message only when status changes or every 30 seconds
        current_time = time.time()
        if current_status != last_status or (current_time - last_update_time) > 30:
            try:
                if current_status == 'pending':
                    elapsed = int(current_time - start_time)
                    text = LANGUAGES[lang]['job_pending'].format(
                        message=message, time=elapsed)
                    await status_msg.edit_text(text, parse_mode="Markdown")
                elif current_status == 'processing':
                    text = LANGUAGES[lang]['job_processing'].format(
                        message=message)
                    await status_msg.edit_text(text, parse_mode="Markdown")
                elif current_status == 'completed':
                    result = status.get('result', {})
                    await handle_job_completion(update, context, status_msg, result, user_id, lang, job_id)
                    return
                elif current_status == 'failed':
                    error = status.get('result', {}).get(
                        'error', 'Unknown error')
                    text = LANGUAGES[lang]['job_failed'].format(error=error)
                    await status_msg.edit_text(text, parse_mode="Markdown")
                    context.user_data.pop('current_job', None)
                    return
                elif current_status == 'expired':
                    await status_msg.edit_text("⚠️ Job expired or not found.")
                    context.user_data.pop('current_job', None)
                    return
                last_update_time = current_time
            except Exception as e:
                logger.debug(f"Status update error (likely harmless): {e}")
            last_status = current_status

        if current_status in ['completed', 'failed', 'expired']:
            break

    if last_status not in ['completed', 'failed', 'expired']:
        try:
            await status_msg.edit_text(LANGUAGES[lang]['job_timeout'], parse_mode="Markdown")
        except:
            pass
        context.user_data.pop('current_job', None)


async def handle_job_completion(update: Update, context: ContextTypes.DEFAULT_TYPE, status_msg, result: dict, user_id: int, lang: str, job_id: str):
    """Handle single job completion - FIXED: saves to last_generated table"""
    try:
        if result.get('success'):
            if user_id != ADMIN_CHAT_ID:
                update_balance(user_id, -1)
                update_total_generated(user_id)
                new_balance = get_user(user_id)["balance"]
                balance_msg = f"Remaining: {new_balance}"
            else:
                balance_msg = "Admin: unlimited"

            request_id = result.get('request_id')
            output_path = result.get('output_path')
            a4_path = result.get('a4_path')
            data_json = result.get('data_json', '{}')
            id_data = json.loads(data_json)

            # Save to history
            save_id_history(user_id, id_data, 'template', output_path, a4_path)

            # ✅ CRITICAL: Save to last_generated for Report Error button
            conn = get_db_connection()
            try:
                conn.execute("""
                    INSERT OR REPLACE INTO last_generated 
                    (request_id, user_id, data_json, template_path, color_mode,
                     created_epoch, output_path, a4_path)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    request_id,
                    user_id,
                    data_json,
                    result.get('template', ''),
                    result.get('color_mode', ''),
                    time.time(),  # ✅ CRITICAL: Set the timestamp!
                    output_path,
                    a4_path
                ))
                conn.commit()
            except Exception as db_err:
                logger.error(f"Failed to update last_generated: {db_err}")
            finally:
                conn.close()

            error_keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    LANGUAGES[lang]['report_error'],
                    callback_data=f"report_error_{request_id}"
                )
            ]])

            if output_path and os.path.exists(output_path):
                with open(output_path, "rb") as f:
                    await context.bot.send_document(
                        chat_id=user_id,
                        document=f,
                        caption=LANGUAGES[lang]['id_ready'].format(
                            balance=balance_msg),
                        reply_markup=error_keyboard
                    )

            if a4_path and os.path.exists(a4_path):
                with open(a4_path, "rb") as f:
                    await context.bot.send_document(
                        chat_id=user_id,
                        document=f,
                        caption=LANGUAGES[lang]['a4_layout']
                    )

            for path in [output_path, a4_path]:
                if path and os.path.exists(path):
                    try:
                        os.remove(path)
                    except:
                        pass

            await status_msg.edit_text(LANGUAGES[lang]['job_done'], parse_mode="Markdown")
        else:
            error = result.get('error', 'Unknown error')
            text = LANGUAGES[lang]['job_failed'].format(error=error)
            await status_msg.edit_text(text, parse_mode="Markdown")
        context.user_data.pop('current_job', None)
    except Exception as e:
        logger.error(f"Error handling job completion: {e}", exc_info=True)
        await status_msg.edit_text("❌ Error delivering your ID. Please try again.")
        context.user_data.pop('current_job', None)


async def check_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    lang = get_user_language(user_id)
    job_id = context.user_data.get('current_job')
    if not job_id:
        await update.message.reply_text(LANGUAGES[lang]['no_active_job'])
        return
    status = await check_job_status(job_id)
    current_status = status.get('status', 'unknown')
    message = status.get('message', '')
    if current_status == 'pending':
        text = LANGUAGES[lang]['job_status'].format(message=message)
    elif current_status == 'processing':
        text = LANGUAGES[lang]['job_status_processing'].format(message=message)
    elif current_status == 'completed':
        text = LANGUAGES[lang]['job_status_completed']
    else:
        text = f"❌ Status: {current_status}"
    await update.message.reply_text(text, parse_mode="Markdown")


async def handle_pdf(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await process_file_async(update, context, file_type="pdf")


async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await process_file_async(update, context, file_type="screenshot")

# ============ PAYMENT DETECTION ============


async def handle_payment_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if "transactioninfo.ethiotelecom.et" not in text:
        return
    user_id = update.effective_user.id
    lang = get_user_language(user_id)
    tx_id = text.strip().split("/")[-1].strip()
    conn = get_db_connection()
    existing = conn.execute(
        "SELECT 1 FROM payments WHERE tx_id = ?", (tx_id,)).fetchone()
    conn.close()
    if existing:
        await update.message.reply_text("⚠️ This payment link has already been submitted.")
        return
    create_payment(user_id, tx_id, 0)
    await update.message.reply_text(LANGUAGES[lang]['payment_submitted'])
    keyboard = [
        [InlineKeyboardButton("+1", callback_data=f"pay_approve_{tx_id}_1"),
         InlineKeyboardButton("+3", callback_data=f"pay_approve_{tx_id}_3"),
         InlineKeyboardButton("+5", callback_data=f"pay_approve_{tx_id}_5")],
        [InlineKeyboardButton("+10", callback_data=f"pay_approve_{tx_id}_10"),
         InlineKeyboardButton("+30", callback_data=f"pay_approve_{tx_id}_30")],
        [InlineKeyboardButton("❌ Reject", callback_data=f"pay_reject_{tx_id}")]
    ]
    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=f"💰 Payment\nUser: {user_id}\nTx: {tx_id}\n{text}",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def admin_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    if data in context.user_data.get("processed_payments", []):
        return
    context.user_data.setdefault("processed_payments", []).append(data)
    await query.answer()
    if data.startswith("pay_approve_"):
        parts = data.split("_")
        if len(parts) >= 4:
            tx_id = parts[2]
            amount = int(parts[3])
            conn = get_db_connection()
            row = conn.execute(
                "SELECT user_id FROM payments WHERE tx_id = ?", (tx_id,)).fetchone()
            conn.close()
            if row:
                user_id = row[0]
                lang = get_user_language(user_id)
                mark_payment_approved(tx_id)
                update_balance(user_id, amount)
                text = LANGUAGES[lang]['payment_approved'].format(
                    amount=amount)
                await context.bot.send_message(chat_id=user_id, text=text)
                await query.edit_message_text(f"✅ Added {amount} credits to user {user_id}")
            else:
                await query.edit_message_text("❌ Payment not found.")
    elif data.startswith("pay_reject_"):
        tx_id = data.split("_")[2]
        conn = get_db_connection()
        row = conn.execute(
            "SELECT user_id FROM payments WHERE tx_id = ?", (tx_id,)).fetchone()
        conn.close()
        if row:
            user_id = row[0]
            lang = get_user_language(user_id)
            mark_payment_rejected(tx_id)
            text = LANGUAGES[lang]['payment_rejected']
            await context.bot.send_message(chat_id=user_id, text=text)
            await query.edit_message_text(f"❌ Rejected payment for user {user_id}")
        else:
            await query.edit_message_text("❌ Payment not found.")
    context.user_data["processed_payments"].remove(data)

# ============ ERROR REPORTING ============

user_correction_state = {}


async def report_error_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    request_id = query.data.replace("report_error_", "")
    if is_report_expired(request_id):
        await query.edit_message_caption(
            caption="⚠️ This report button has expired (10 minutes limit). Please generate the ID again if you need to report an error.",
            reply_markup=None
        )
        return
    user_id = query.from_user.id
    lang = get_user_language(user_id)
    user_correction_state[user_id] = {
        'request_id': request_id,
        'selected_fields': set(),
        'corrections': {},
        'step': 0,
        'fields_list': []
    }
    fields = [
        "am_name", "en_name", "dob_am", "dob_en", "doi_am", "doi_en",
        "expiry_am", "expiry_en", "sex_am", "sex_en", "fcn", "phone",
        "region_am", "region_en", "zone_am", "zone_en", "woreda_am", "woreda_en", "fin"
    ]
    FIELD_LABELS = {
        "am_name": "ሙሉ ስም" if lang == 'am' else "Full Name" if lang == 'en' else "Maqaa Guutuu",
        "en_name": "Full Name" if lang == 'en' else "ሙሉ ስም" if lang == 'am' else "Maqaa Guutuu",
        "dob_am": "የትውልድ ቀን (ኢትዮጵያ)" if lang == 'am' else "Date of Birth (Ethiopian)" if lang == 'en' else "Guyyaa Dhalootaa (Itoophiyaa)",
        "dob_en": "Date of Birth (Gregorian)" if lang == 'en' else "የትውልድ ቀን (ግሪጎሪያን)" if lang == 'am' else "Guyyaa Dhalootaa (Giregoriyaan)",
        "doi_am": "የተሰጠበት ቀን (ኢትዮጵያ)" if lang == 'am' else "Date of Issue (Ethiopian)" if lang == 'en' else "Guyyaa Kenname (Itoophiyaa)",
        "doi_en": "Date of Issue (Gregorian)" if lang == 'en' else "የተሰጠበት ቀን (ግሪጎሪያን)" if lang == 'am' else "Guyyaa Kenname (Giregoriyaan)",
        "expiry_am": "የሚያበቃበት ቀን (ኢትዮጵያ)" if lang == 'am' else "Expiry Date (Ethiopian)" if lang == 'en' else "Guyyaa Xumura (Itoophiyaa)",
        "expiry_en": "Expiry Date (Gregorian)" if lang == 'en' else "የሚያበቃበት ቀን (ግሪጎሪያን)" if lang == 'am' else "Guyyaa Xumura (Giregoriyaan)",
        "sex_am": "ፆታ" if lang == 'am' else "Sex" if lang == 'en' else "Saalaa",
        "sex_en": "Sex" if lang == 'en' else "ፆታ" if lang == 'am' else "Saalaa",
        "fcn": "ካርድ ቁጥር (FCN/FAN)" if lang == 'am' else "Card Number (FCN/FAN)" if lang == 'en' else "Lakkoofsa Kaardii (FCN/FAN)",
        "phone": "ስልክ ቁጥር" if lang == 'am' else "Phone Number" if lang == 'en' else "Lakkoofsa Bilbilaa",
        "region_am": "ክልል" if lang == 'am' else "Region" if lang == 'en' else "Naannoo",
        "region_en": "Region" if lang == 'en' else "ክልል" if lang == 'am' else "Naannoo",
        "zone_am": "ዞን" if lang == 'am' else "Zone" if lang == 'en' else "Godina",
        "zone_en": "Zone" if lang == 'en' else "ዞን" if lang == 'am' else "Godina",
        "woreda_am": "ወረዳ" if lang == 'am' else "Woreda" if lang == 'en' else "Aanaa",
        "woreda_en": "Woreda" if lang == 'en' else "ወረዳ" if lang == 'am' else "Aanaa",
        "fin": "ፋይዳ ቁጥር (FIN)" if lang == 'am' else "FIN Number" if lang == 'en' else "Lakkoofsa FIN"
    }
    user_correction_state[user_id]['fields_list'] = fields
    user_correction_state[user_id]['field_labels'] = FIELD_LABELS
    user_correction_state[user_id]['lang'] = lang
    await show_field_selection(update, context, user_id)


async def show_field_selection(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    state = user_correction_state.get(user_id)
    if not state:
        return
    fields = state['fields_list']
    FIELD_LABELS = state.get('field_labels', {})
    lang = state.get('lang', 'en')
    keyboard = []
    for field in fields:
        label = FIELD_LABELS.get(field, field)
        checked = "✅ " if field in state['selected_fields'] else "⬜ "
        keyboard.append([InlineKeyboardButton(
            f"{checked}{label}", callback_data=f"toggle_{field}")])
    keyboard.append([InlineKeyboardButton(
        "✅ DONE", callback_data="correction_done")])
    keyboard.append([InlineKeyboardButton(
        "❌ Cancel", callback_data="cancel_correction")])
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = LANGUAGES[lang]['select_fields']
    if update.callback_query:
        await update.callback_query.edit_message_caption(caption=text, reply_markup=reply_markup)
    else:
        await context.bot.send_message(chat_id=user_id, text=text, reply_markup=reply_markup)


async def toggle_field_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    field = query.data.replace("toggle_", "")
    user_id = query.from_user.id
    state = user_correction_state.get(user_id)
    if not state:
        await query.edit_message_text("Session expired. Please start over.")
        return
    if field in state['selected_fields']:
        state['selected_fields'].remove(field)
    else:
        state['selected_fields'].add(field)
    await show_field_selection(update, context, user_id)


async def correction_done_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    state = user_correction_state.get(user_id)
    if not state or not state['selected_fields']:
        lang = state.get('lang', 'en') if state else 'en'
        await query.edit_message_text(LANGUAGES[lang]['no_fields'])
        return
    await query.message.delete()
    lang = state.get('lang', 'en')
    text = LANGUAGES[lang]['correction_start']
    await context.bot.send_message(chat_id=user_id, text=text)
    state['step'] = 0
    state['corrections'] = {}
    state['fields_to_correct'] = list(state['selected_fields'])
    await ask_next_correction(update, context, user_id)


async def ask_next_correction(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    state = user_correction_state.get(user_id)
    if not state:
        return
    idx = state['step']
    fields = state['fields_to_correct']
    if idx >= len(fields):
        await send_corrections_to_admin(update, context, user_id)
        return
    field = fields[idx]
    FIELD_LABELS = state.get('field_labels', {})
    label = FIELD_LABELS.get(field, field)
    lang = state.get('lang', 'en')
    conn = get_db_connection()
    row = conn.execute("SELECT data_json FROM last_generated WHERE request_id = ?",
                       (state['request_id'],)).fetchone()
    conn.close()
    original_data = json.loads(row[0]) if row else {}
    original_value = original_data.get(field, "N/A")
    text = LANGUAGES[lang]['correction_field'].format(
        current=idx+1,
        total=len(fields),
        label=label,
        original=original_value
    )
    await context.bot.send_message(chat_id=user_id, text=text, parse_mode="Markdown")
    context.user_data["awaiting_correction_for"] = user_id
    context.user_data["correction_step"] = idx
    context.user_data["correction_field"] = field


async def receive_correction_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if context.user_data.get("awaiting_correction_for") != user_id:
        return
    corrected_value = update.message.text.strip()
    field = context.user_data.get("correction_field")
    step = context.user_data.get("correction_step")
    if not field or step is None:
        await update.message.reply_text("❌ Session expired. Please start over.")
        context.user_data.pop("awaiting_correction_for", None)
        return
    state = user_correction_state.get(user_id)
    if not state:
        await update.message.reply_text("❌ Session expired. Please start over.")
        return
    state['corrections'][field] = corrected_value
    state['step'] = step + 1
    context.user_data.pop("awaiting_correction_for", None)
    context.user_data.pop("correction_field", None)
    context.user_data.pop("correction_step", None)
    await ask_next_correction(update, context, user_id)


async def send_corrections_to_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id: int):
    state = user_correction_state.get(user_id)
    if not state:
        return
    lang = state.get('lang', 'en')
    processing_msg = await context.bot.send_message(
        chat_id=user_id,
        text="⏳ Applying your corrections and regenerating your ID... Please wait."
    )
    request_id = state['request_id']
    corrections = state['corrections']
    conn = None
    output_path = None
    a4_path = None
    temp_photo_path = ""
    temp_qr_path = ""
    report_id = None
    changes_text = ""
    original_user_id = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        row = cursor.execute(
            "SELECT data_json, user_id, template_path, color_mode, photo_base64, qr_base64 FROM last_generated WHERE request_id = ?",
            (request_id,)
        ).fetchone()
        if not row:
            await processing_msg.edit_text("❌ Original data not found. Please generate ID again.")
            return
        original_data_json, original_user_id, template_path, color_mode, photo_base64, qr_base64 = row
        original_data = json.loads(original_data_json)
        changes = []
        for field, new_val in corrections.items():
            old_val = original_data.get(field, "")
            changes.append(f"• {field}: `{old_val}` → `{new_val}`")
            if field == "fin":
                cleaned_val = re.sub(r'[^\d]', '', new_val)
                original_data[field] = cleaned_val
            else:
                original_data[field] = new_val
        changes_text = "\n".join(changes)
        cursor.execute("""
            INSERT INTO error_reports (user_id, field, original_value, corrected_value, status, request_id, original_data_json, corrections_json)
            VALUES (?, ?, ?, ?, 'auto_applied', ?, ?, ?)
        """, (original_user_id, "multiple", "", "", request_id, original_data_json, json.dumps(corrections)))
        report_id = cursor.lastrowid
        conn.commit()
        await processing_msg.edit_text("🖼️ Rendering your corrected ID...")
        if photo_base64:
            temp_photo_path = os.path.join(
                INPUT_DIR, f"temp_photo_{uuid.uuid4().hex[:8]}.png")
            base64_to_image(photo_base64, temp_photo_path)
            original_data["photo_path"] = temp_photo_path
        if qr_base64:
            temp_qr_path = os.path.join(
                INPUT_DIR, f"temp_qr_{uuid.uuid4().hex[:8]}.png")
            base64_to_image(qr_base64, temp_qr_path)
            original_data["qr_path"] = temp_qr_path
        output_path = await run_in_thread(render_id, original_data, template_path, color_mode)
        a4_path = await run_in_thread(generate_reversed_a4_layout, output_path)
        await processing_msg.delete()
        error_keyboard = InlineKeyboardMarkup([[InlineKeyboardButton(
            LANGUAGES[lang]['report_error'], callback_data=f"report_error_{request_id}"
        )]])
        with open(output_path, "rb") as f:
            await context.bot.send_document(
                chat_id=user_id,
                document=f,
                caption=LANGUAGES[lang]['correction_done'],
                reply_markup=error_keyboard
            )
        with open(a4_path, "rb") as f:
            await context.bot.send_document(chat_id=user_id, document=f, caption=LANGUAGES[lang]['a4_layout'])
    except Exception as e:
        logger.error(f"Error in send_corrections_to_admin: {e}", exc_info=True)
        await processing_msg.edit_text(LANGUAGES[lang]['correction_failed'])
        if original_user_id:
            try:
                await context.bot.send_message(
                    chat_id=ADMIN_CHAT_ID,
                    text=f"⚠️ **Correction Failed**\nUser: {original_user_id}\nError: {str(e)[:200]}"
                )
            except:
                pass
        return
    finally:
        for path in [output_path, a4_path, temp_photo_path, temp_qr_path]:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception as cleanup_error:
                    logger.warning(
                        f"Failed to clean up {path}: {cleanup_error}")
        if conn:
            try:
                conn.close()
            except:
                pass
        if user_id in user_correction_state:
            del user_correction_state[user_id]
    if report_id and changes_text and original_user_id:
        try:
            admin_text = f"📝 Correction Applied (Auto) #{report_id}\nUser: {original_user_id}\n\nChanges applied:\n{changes_text}"
            await context.bot.send_message(chat_id=ADMIN_CHAT_ID, text=admin_text, parse_mode=None)
            logger.info(f"Admin notification sent for correction #{report_id}")
        except Exception as admin_error:
            logger.error(f"Failed to send admin notification: {admin_error}")


async def cancel_correction_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    state = user_correction_state.get(user_id)
    lang = state.get('lang', 'en') if state else 'en'
    if state:
        del user_correction_state[user_id]
    await query.edit_message_caption(caption=LANGUAGES[lang]['correction_cancelled'])

# ============ DASHBOARD WEBAPP HANDLER ============


async def handle_dashboard_webapp(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.web_app_data:
        await update.message.reply_text(
            "📱 Use the dashboard button to access your account.\n\n"
            "💡 You can:\n"
            "• View your ID history\n"
            "• Download previous IDs\n"
            "• Buy credits\n"
            "• Manage your account"
        )
        return
    try:
        data = json.loads(update.message.web_app_data.data)
        logger.info(f"📱 WebApp data received: {data}")
        action = data.get('type')
        user_id = update.effective_user.id
        lang = get_user_language(user_id)
        if action == 'payment':
            credits = int(data.get('credits', 0))
            amount = int(data.get('amount', 0))
            method = data.get('method', 'telebirr')
            transaction = data.get('transaction', '')
            reference = data.get('reference', '')
            if not transaction:
                await update.message.reply_text("❌ Please provide a transaction reference.")
                return
            if amount <= 0 or credits <= 0:
                await update.message.reply_text("❌ Invalid payment amount or credits.")
                return
            tx_id = f"WEB_{uuid.uuid4().hex[:10].upper()}"
            create_payment(user_id, tx_id, amount, credits)
            keyboard = [
                [InlineKeyboardButton(
                    f"✅ Approve ({credits} credits)", callback_data=f"web_pay_approve_{tx_id}_{credits}")],
                [InlineKeyboardButton(
                    "❌ Reject", callback_data=f"web_pay_reject_{tx_id}")]
            ]
            admin_msg = f"""💰 **Web Dashboard Payment**

👤 User ID: `{user_id}`
💳 Credits: {credits}
💵 Amount: {amount} ETB
📱 Method: {method}
🆔 Tx ID: `{tx_id}`
📝 Reference: `{reference}`

Transaction link: {transaction}

_From Web Dashboard_"""
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=admin_msg,
                parse_mode="Markdown",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            await update.message.reply_text(
                f"✅ **Payment Submitted!**\n\n"
                f"📝 Transaction ID: `{tx_id}`\n"
                f"💳 Credits: {credits}\n"
                f"💵 Amount: {amount} ETB\n\n"
                f"⏳ Waiting for admin verification. You'll be notified when approved.",
                parse_mode="Markdown"
            )
            return
        elif action == 'download':
            file_path = data.get('file_path', '')
            request_id = data.get('request_id', '')
            if request_id:
                conn = get_db_connection()
                row = conn.execute(
                    "SELECT file_path, a4_path FROM id_history WHERE request_id = ? AND user_id = ?",
                    (request_id, user_id)
                ).fetchone()
                conn.close()
                if row and os.path.exists(row[0]):
                    file_path = row[0]
                    a4_path = row[1] if len(row) > 1 else None
                else:
                    await update.message.reply_text("❌ ID not found in your history.")
                    return
            elif file_path and os.path.exists(file_path):
                a4_path = file_path.replace(
                    'output/', 'a4_layouts/').replace('ID_', 'A4_ID_')
                if not os.path.exists(a4_path):
                    a4_path = None
            else:
                await update.message.reply_text("❌ File not found.")
                return
            try:
                with open(file_path, 'rb') as f:
                    await context.bot.send_document(
                        chat_id=user_id,
                        document=f,
                        caption="📄 Here's your ID file!",
                        filename=os.path.basename(file_path)
                    )
                if a4_path and os.path.exists(a4_path):
                    with open(a4_path, 'rb') as f:
                        await context.bot.send_document(
                            chat_id=user_id,
                            document=f,
                            caption="🖨️ A4 print layout",
                            filename=os.path.basename(a4_path)
                        )
                await update.message.reply_text("✅ File(s) sent successfully!")
            except Exception as e:
                logger.error(f"Download error: {e}")
                await update.message.reply_text(f"❌ Error downloading file: {str(e)[:100]}")
            return
        elif action == 'history':
            stats = get_user_stats(user_id)
            await update.message.reply_text(
                f"📊 **Your History**\n\n"
                f"📈 Total IDs: {stats['total']}\n"
                f"📅 Today: {stats['today']}\n"
                f"💳 Balance: {get_user(user_id)['balance']}\n\n"
                f"Check the My IDs button in the bot for full history.",
                parse_mode="Markdown"
            )
            return
        elif action == 'balance':
            user = get_user(user_id)
            await update.message.reply_text(
                f"💳 **Your Balance**\n\n"
                f"🔹 Remaining IDs: `{user['balance']}`\n"
                f"🔹 Total generated: `{user['total_generated']}`\n\n"
                f"Each ID generation costs 1 credit.",
                parse_mode="Markdown"
            )
            return
    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON from webapp: {e}")
        await update.message.reply_text("❌ Invalid data received.")
    except Exception as e:
        logger.error(f"WebApp handler error: {e}", exc_info=True)
        await update.message.reply_text("❌ An error occurred processing your request.")

# ============ WEB PAYMENT CALLBACK ============


async def web_payment_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()
    if data.startswith("web_pay_approve_"):
        parts = data.split("_")
        if len(parts) >= 5:
            tx_id = parts[3]
            credits = int(parts[4])
            payment = get_payment(tx_id)
            if not payment:
                await query.edit_message_text("❌ Payment not found.")
                return
            user_id = payment['user_id']
            lang = get_user_language(user_id)
            mark_payment_approved(tx_id)
            update_balance(user_id, credits)
            text = LANGUAGES[lang]['payment_approved'].format(amount=credits)
            await context.bot.send_message(chat_id=user_id, text=text)
            await query.edit_message_text(
                f"✅ **Approved Web Payment**\n"
                f"User: {user_id}\n"
                f"Tx: {tx_id}\n"
                f"Credits: {credits}\n\n"
                f"Payment processed successfully!",
                parse_mode="Markdown"
            )
        else:
            await query.edit_message_text("❌ Invalid payment data.")
    elif data.startswith("web_pay_reject_"):
        tx_id = data.split("_")[3]
        payment = get_payment(tx_id)
        if not payment:
            await query.edit_message_text("❌ Payment not found.")
            return
        user_id = payment['user_id']
        lang = get_user_language(user_id)
        mark_payment_rejected(tx_id)
        text = LANGUAGES[lang]['payment_rejected']
        await context.bot.send_message(chat_id=user_id, text=text)
        await query.edit_message_text(
            f"❌ **Rejected Web Payment**\n"
            f"User: {user_id}\n"
            f"Tx: {tx_id}\n\n"
            f"Payment rejected.",
            parse_mode="Markdown"
        )

# ============ REGISTER HANDLERS ============

application.add_handler(MessageHandler(
    filters.Regex(UPLOAD_PATTERN), handle_upload_button))
application.add_handler(MessageHandler(
    filters.Regex(MY_IDS_PATTERN), handle_my_ids))
application.add_handler(MessageHandler(
    filters.Regex(WALLET_PATTERN), handle_wallet))
application.add_handler(MessageHandler(
    filters.Regex(TEMPLATES_PATTERN), handle_templates))
application.add_handler(MessageHandler(
    filters.Regex(DEPOSIT_PATTERN), handle_deposit))
application.add_handler(MessageHandler(
    filters.Regex(BULK_PATTERN), handle_bulk_process))
application.add_handler(MessageHandler(
    filters.Regex(SETTINGS_PATTERN), handle_settings))
application.add_handler(MessageHandler(
    filters.Regex(INVITE_PATTERN), handle_invite))
application.add_handler(MessageHandler(
    filters.Regex(DASHBOARD_PATTERN), handle_dashboard))

application.add_handler(ConversationHandler(
    entry_points=[MessageHandler(
        filters.Regex(SUPPORT_PATTERN), handle_support)],
    states={SUPPORT_STATE: [MessageHandler(
        filters.TEXT & ~filters.COMMAND, support_message)]},
    fallbacks=[CommandHandler("cancel", cancel_support)],
))

application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("status", check_status))
application.add_handler(CallbackQueryHandler(
    language_callback, pattern="^lang_"))
application.add_handler(CallbackQueryHandler(
    initial_template_callback, pattern="^set_(?!existing)"))
application.add_handler(CallbackQueryHandler(
    set_existing_template_callback, pattern="^set_existing_"))
application.add_handler(CallbackQueryHandler(
    history_navigation_callback, pattern="^history_"))
application.add_handler(CallbackQueryHandler(
    view_history_web_callback, pattern="^view_history_web$"))

application.add_handler(CallbackQueryHandler(bulk_callback, pattern="^bulk_"))

application.add_handler(CallbackQueryHandler(
    settings_callback, pattern="^settings_"))
application.add_handler(CallbackQueryHandler(
    settings_callback, pattern="^set_format_"))
application.add_handler(CallbackQueryHandler(
    settings_callback, pattern="^set_quality_"))
application.add_handler(CallbackQueryHandler(
    settings_callback, pattern="^set_layout_"))

application.add_handler(CallbackQueryHandler(
    invite_callback, pattern="^invite_"))

application.add_handler(CallbackQueryHandler(
    dashboard_callback, pattern="^dashboard_"))

application.add_handler(CommandHandler("broadcast", broadcast_text))
application.add_handler(ConversationHandler(
    entry_points=[CommandHandler("broadcast_photo", broadcast_photo_start)],
    states={BROADCAST_PHOTO_STATE: [
        MessageHandler(filters.PHOTO, broadcast_photo_receive),
        MessageHandler(filters.TEXT & ~filters.COMMAND, cancel_broadcast)
    ]},
    fallbacks=[CommandHandler("cancel", cancel_broadcast)],
))
application.add_handler(CallbackQueryHandler(
    broadcast_wallet_callback, pattern="^broadcast_wallet$"))
application.add_handler(CallbackQueryHandler(
    broadcast_deposit_callback, pattern="^broadcast_deposit$"))
application.add_handler(CallbackQueryHandler(
    broadcast_templates_callback, pattern="^broadcast_templates$"))

application.add_handler(MessageHandler(
    filters.TEXT & filters.User(user_id=ADMIN_CHAT_ID), admin_reply_handler))

application.add_handler(MessageHandler(filters.Document.PDF, handle_pdf))
application.add_handler(MessageHandler(filters.PHOTO, handle_photo))

application.add_handler(MessageHandler(
    filters.TEXT & ~filters.COMMAND, handle_payment_link))
application.add_handler(CallbackQueryHandler(
    admin_payment_callback, pattern="^pay_"))
application.add_handler(CallbackQueryHandler(
    web_payment_callback, pattern="^web_pay_"))

application.add_handler(CallbackQueryHandler(
    report_error_callback, pattern="^report_error_"))
application.add_handler(CallbackQueryHandler(
    toggle_field_callback, pattern="^toggle_"))
application.add_handler(CallbackQueryHandler(
    correction_done_callback, pattern="^correction_done$"))
application.add_handler(CallbackQueryHandler(
    cancel_correction_callback, pattern="^cancel_correction$"))
application.add_handler(MessageHandler(
    filters.TEXT & ~filters.COMMAND, receive_correction_text), group=1)

application.add_handler(MessageHandler(
    filters.TEXT & ~filters.COMMAND, handle_dashboard_webapp))

application.add_handler(MessageHandler(
    filters.TEXT & ~filters.COMMAND, log_text), group=-1)

# ============ RUN BOT ============

if __name__ == "__main__":
    logger.info("🚀 Starting Telegram Bot in Long Polling mode...")
    logger.info(f"✅ Bot token: {TOKEN[:10]}...")
    logger.info("✅ Press Ctrl+C to stop")
    init_db()
    try:
        conn = get_db_connection()
        c = conn.cursor()
        c.execute(
            "ALTER TABLE users ADD COLUMN layout_mode TEXT DEFAULT 'mirrored'")
        conn.commit()
        conn.close()
        logger.info("✅ Added layout_mode column")
    except Exception as e:
        if "duplicate" not in str(e).lower():
            logger.warning(f"Layout mode column error: {e}")
    application.run_polling(drop_pending_updates=True)
