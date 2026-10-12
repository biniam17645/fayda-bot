import os
import json
import uuid
import asyncio
from fastapi import FastAPI, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn
import libsql
from dotenv import load_dotenv
from telegram import Bot

load_dotenv()

# ============ CONFIG ============
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "8131225823"))

# ============ DATABASE ============


def get_db_connection():
    url = os.getenv("TURSO_DATABASE_URL")
    token = os.getenv("TURSO_AUTH_TOKEN")
    if not url or not token:
        raise RuntimeError("Turso credentials missing")
    return libsql.connect(url, auth_token=token)


def get_user(user_id: int):
    conn = get_db_connection()
    row = conn.execute(
        "SELECT balance, total_generated, default_template, language FROM users WHERE user_id = ?",
        (user_id,)
    ).fetchone()
    conn.close()
    if row:
        return {"balance": row[0], "total_generated": row[1], "default_template": row[2], "language": row[3]}
    else:
        conn = get_db_connection()
        conn.execute(
            "INSERT INTO users (user_id, balance, total_generated, default_template, language) VALUES (?, 0, 0, 'temp1_color', 'en')",
            (user_id,)
        )
        conn.commit()
        conn.close()
        return {"balance": 0, "total_generated": 0, "default_template": "temp1_color", "language": "en"}


def get_user_history(user_id, limit=20):
    conn = get_db_connection()
    rows = conn.execute("""
        SELECT en_name, am_name, fcn, fin, generated_at, template_used, file_path
        FROM id_history
        WHERE user_id = ?
        ORDER BY generated_at DESC
        LIMIT ?
    """, (user_id, limit)).fetchall()
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

# ============ TELEGRAM NOTIFICATION ============


async def send_admin_notification(message):
    """Send notification to admin via Telegram"""
    try:
        bot = Bot(token=BOT_TOKEN)
        await bot.send_message(chat_id=ADMIN_CHAT_ID, text=message, parse_mode="Markdown")
    except Exception as e:
        print(f"Failed to send admin notification: {e}")

# ============ FASTAPI APP ============
app = FastAPI(title="Fayda ID Dashboard API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ============ ROOT ============


@app.get("/")
async def root():
    return {"message": "Fayda ID Dashboard API", "version": "1.0"}

# ============ DASHBOARD ENDPOINTS ============


@app.get("/api/dashboard")
async def get_dashboard_data(x_user_id: int = Header(None)):
    if not x_user_id:
        return {"error": "User ID required"}

    user = get_user(x_user_id)
    stats = get_user_stats(x_user_id)

    return {
        "balance": user['balance'],
        "total_generated": user['total_generated'],
        "template": user['default_template'],
        "today": stats['today']
    }


@app.get("/api/history")
async def get_history(x_user_id: int = Header(None)):
    if not x_user_id:
        return {"error": "User ID required"}

    history = get_user_history(x_user_id, 50)
    return [
        {
            "en_name": row[0] or "Unknown",
            "am_name": row[1] or "",
            "fcn": row[2] or "",
            "fin": row[3] or "",
            "generated_at": row[4],
            "file_path": row[6] or ""
        }
        for row in history
    ]


@app.get("/api/stats")
async def get_stats(x_user_id: int = Header(None)):
    if not x_user_id:
        return {"error": "User ID required"}

    stats = get_user_stats(x_user_id)
    user = get_user(x_user_id)

    return {
        "total": stats['total'],
        "today": stats['today'],
        "balance": user['balance']
    }

# ============ USER TEMPLATE ============


@app.get("/api/user/template")
async def get_user_template(x_user_id: int = Header(None)):
    if not x_user_id:
        return {"error": "User ID required"}

    user = get_user(x_user_id)
    return {"template": user['default_template']}


@app.post("/api/user/template")
async def update_user_template(request: Request, x_user_id: int = Header(None)):
    if not x_user_id:
        return {"error": "User ID required"}

    data = await request.json()
    template = data.get('template', 'temp1_color')

    conn = get_db_connection()
    conn.execute(
        "UPDATE users SET default_template = ? WHERE user_id = ?",
        (template, x_user_id)
    )
    conn.commit()
    conn.close()

    return {"status": "success", "template": template}

# ============ REFERRAL ============


@app.get("/api/referral")
async def get_referral_data(x_user_id: int = Header(None)):
    if not x_user_id:
        return {"error": "User ID required"}

    conn = get_db_connection()
    referrals = 0  # Placeholder until referred_by column exists
    conn.close()

    return {
        "referrals": referrals,
        "bonus": referrals * 2,
        "referral_link": f"https://t.me/FAYDA_ID_C_BOT?start=ref_{x_user_id}"
    }

# ============ PACKAGES ============


@app.get("/api/packages")
async def get_packages():
    return [
        {"id": 1, "credits": 1, "price": 20, "save": 0, "save_percent": 0},
        {"id": 2, "credits": 3, "price": 50, "save": 10, "save_percent": 17},
        {"id": 3, "credits": 5, "price": 80, "save": 20, "save_percent": 20},
        {"id": 4, "credits": 10, "price": 150, "save": 50, "save_percent": 25},
        {"id": 5, "credits": 30, "price": 499, "save": 101, "save_percent": 17}
    ]

# ============ SUBMIT PAYMENT ============


@app.post("/api/submit-payment")
async def submit_payment(request: Request, x_user_id: int = Header(None)):
    if not x_user_id:
        return {"error": "User ID required"}

    data = await request.json()
    credits = data.get('credits', 0)
    amount = data.get('amount', 0)
    method = data.get('method', 'telebirr')
    transaction = data.get('transaction', '')

    if not transaction:
        return {"error": "Transaction ID required"}

    # Create payment record
    tx_id = str(uuid.uuid4())[:8]
    conn = get_db_connection()
    conn.execute(
        "INSERT INTO payments (tx_id, user_id, amount, status) VALUES (?, ?, ?, 'pending')",
        (tx_id, x_user_id, amount)
    )
    conn.commit()
    conn.close()

    # Send notification to admin
    admin_message = f"""💰 **New Payment Request**

👤 User: `{x_user_id}`
💳 Credits: {credits}
💵 Amount: {amount} ETB
📱 Method: {method}
🆔 Transaction: `{transaction}`
📋 TX ID: `{tx_id}`

Please verify and approve in the bot."""

    asyncio.create_task(send_admin_notification(admin_message))

    return {
        "status": "pending",
        "message": "Payment submitted for admin approval",
        "tx_id": tx_id
    }

# ============ PAYMENT HISTORY ============


@app.get("/api/payments")
async def get_payment_history(x_user_id: int = Header(None)):
    if not x_user_id:
        return {"error": "User ID required"}

    conn = get_db_connection()
    rows = conn.execute("""
        SELECT tx_id, amount, status, created_at
        FROM payments
        WHERE user_id = ?
        ORDER BY created_at DESC
        LIMIT 20
    """, (x_user_id,)).fetchall()
    conn.close()

    return [
        {
            "tx_id": row[0],
            "amount": row[1],
            "status": row[2],
            "created_at": row[3]
        }
        for row in rows
    ]

# ============ SETTINGS ============


@app.post("/api/settings")
async def save_settings(request: Request, x_user_id: int = Header(None)):
    if not x_user_id:
        return {"error": "User ID required"}

    data = await request.json()
    return {"status": "success", "message": "Settings saved"}

if __name__ == "__main__":
    print("🚀 Starting Dashboard API Server on http://localhost:8000")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
