import os
import threading
import re
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from google.oauth2 import service_account
from googleapiclient.discovery import build

# --- কনফিগারেশন (এখানে আপনার তথ্য দিন অথবা এনভায়রনমেন্ট ভেরিয়েবল ব্যবহার করুন) ---
BOT_TOKEN = os.environ.get("BOT_TOKEN", "আপনার_নতুন_বট_টোকেন_এখানে_দিন")
API_ID = int(os.environ.get("API_ID", "123456")) # my.telegram.org থেকে পাবেন
API_HASH = os.environ.get("API_HASH", "আপনার_এপিআই_হ্যাশ")
SERVICE_ACCOUNT_FILE = 'service_account.json' # আপনার জেসন ফাইলের নাম

# --- Flask অ্যাপ (Render এ সার্ভিস চালু রাখার জন্য) ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is Running Successfully!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# --- গুগল ড্রাইভ সেটআপ ---
SCOPES = ['https://www.googleapis.com/auth/drive']
def get_drive_service():
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

# --- পাইরোগ্রাম বট সেটআপ ---
bot = Client("my_drive_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ইউজারদের স্টেট বা অবস্থা মনে রাখার জন্য
user_states = {}
user_data = {}

# --- হেল্পার ফাংশন: লিংক থেকে ID বের করা ---
def get_id_from_url(url):
    # খুব সাধারণ রেজেক্স, প্রয়োজনে উন্নত করা যেতে পারে
    match = re.search(r'[-\w]{25,}', url)
    return match.group(0) if match else None

# --- কমান্ড হ্যান্ডলার ---

@bot.on_message(filters.command("start"))
async def start(client, message):
    buttons = ReplyKeyboardMarkup(
        [[KeyboardButton("📂 Copy File")]],
        resize_keyboard=True
    )
    await message.reply_text(
        "স্বাগতম! আমি Google Drive কপি বট।\nনিচের বাটন চেপে কাজ শুরু করুন।",
        reply_markup=buttons
    )

@bot.on_message(filters.regex("📂 Copy File"))
async def start_copy_process(client, message):
    user_id = message.from_user.id
    user_states[user_id] = "WAITING_SOURCE"
    
    cancel_btn = ReplyKeyboardMarkup(
        [[KeyboardButton("❌ Cancel")]],
        resize_keyboard=True
    )
    
    await message.reply_text(
        "অনুগ্রহ করে **Source Google Drive Link** টি দিন (যে ফাইলটি কপি করবেন):",
        reply_markup=cancel_btn
    )

@bot.on_message(filters.regex("❌ Cancel"))
async def cancel_process(client, message):
    user_id = message.from_user.id
    if user_id in user_states:
        del user_states[user_id]
    if user_id in user_data:
        del user_data[user_id]
        
    buttons = ReplyKeyboardMarkup(
        [[KeyboardButton("📂 Copy File")]],
        resize_keyboard=True
    )
    await message.reply_text("প্রসেস বাতিল করা হয়েছে।", reply_markup=buttons)

@bot.on_message(filters.text & ~filters.command("start"))
async def handle_inputs(client, message):
    user_id = message.from_user.id
    state = user_states.get(user_id)
    text = message.text

    if not state:
        return

    # ১. সোর্স লিংক হ্যান্ডেল করা
    if state == "WAITING_SOURCE":
        file_id = get_id_from_url(text)
        if not file_id:
            await message.reply_text("ভুল লিংক! দয়া করে সঠিক গুগল ড্রাইভ লিংক দিন।")
            return
            
        user_data[user_id] = {'source_id': file_id}
        user_states[user_id] = "WAITING_DEST"
        await message.reply_text("লিংক পেয়েছি। ✅\n\nএবার **Destination Folder Link** টি দিন (যেখানে আপলোড হবে):")

    # ২. ডেস্টিনেশন লিংক হ্যান্ডেল করা ও কপি শুরু
    elif state == "WAITING_DEST":
        folder_id = get_id_from_url(text)
        if not folder_id:
            await message.reply_text("ভুল ফোল্ডার লিংক! আবার চেষ্টা করুন।")
            return

        source_id = user_data[user_id]['source_id']
        
        # প্রসেস শুরু
        status_msg = await message.reply_text("🔄 প্রসেসিং হচ্ছে... দয়া করে অপেক্ষা করুন।")
        
        try:
            drive_service = get_drive_service()
            
            # ফাইলের নাম বের করা
            source_file = drive_service.files().get(fileId=source_id).execute()
            file_name = source_file.get('name')
            
            await status_msg.edit_text(f"📥 কপি হচ্ছে: `{file_name}`\nবট সার্ভার সাইড কপি ব্যবহার করছে (দ্রুত গতির জন্য)...")

            # কপি কমান্ড (Server Side Copy)
            file_metadata = {
                'name': file_name,
                'parents': [folder_id]
            }
            drive_service.files().copy(
                fileId=source_id,
                body=file_metadata
            ).execute()

            # সাকসেস মেসেজ
            buttons = ReplyKeyboardMarkup(
                [[KeyboardButton("📂 Copy File")]],
                resize_keyboard=True
            )
            await status_msg.delete()
            await message.reply_text(
                f"✅ সফলভাবে কপি হয়েছে!\n\n📂 **ফাইল:** `{file_name}`",
                reply_markup=buttons
            )

        except Exception as e:
            await status_msg.edit_text(f"❌ এরর হয়েছে: {str(e)}")
            # কমন এরর: পারমিশন না থাকা
            if "File not found" in str(e) or "Permission" in str(e):
                await message.reply_text("⚠️ টিপস: আপনি যে ফোল্ডারে বা ফাইল কপি করতে চান, সেখানে আপনার Service Account ইমেইলটিকে 'Editor' পারমিশন দিতে হবে।")

        # স্টেট ক্লিয়ার
        del user_states[user_id]
        del user_data[user_id]

# --- মেইন রানার ---
if __name__ == "__main__":
    # ফ্লাস্ক সার্ভার আলাদা থ্রেডে রান হবে
    t = threading.Thread(target=run_flask)
    t.daemon = True
    t.start()
    
    # বট রান হবে
    print("Bot Started...")
    bot.run()
.
