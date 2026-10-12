
import libsql
import os
from dotenv import load_dotenv
load_dotenv()

url = os.getenv('TURSO_DATABASE_URL')
token = os.getenv('TURSO_AUTH_TOKEN')
conn = libsql.connect(url, auth_token=token)
c = conn.cursor()
try:
    c.execute('ALTER TABLE users ADD COLUMN layout_mode TEXT DEFAULT \"mirrored\"')
    conn.commit()
    print('✅ Added layout_mode column')
except Exception as e:
    print(f'⚠️ {e}')
conn.close()
