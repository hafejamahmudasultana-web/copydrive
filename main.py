import os
import threading
import re
from flask import Flask
from pyrogram import Client, filters
from pyrogram.types import ReplyKeyboardMarkup, KeyboardButton
from google.oauth2 import service_account
from googleapiclient.discovery import build

# --- কনফিগারেশন ---
# কোড এখন সরাসরি Render এর Environment Variable থেকে তথ্য নেবে
BOT_TOKEN = os.environ.get("BOT_TOKEN")
# API_ID ইন্টিজার হতে হয়, তাই int() ব্যবহার করা হয়েছে। ডিফল্ট হিসেবে 0 দেওয়া হলো যাতে ক্র্যাশ না করে।
API_ID = int(os.environ.get("API_ID", 0)) 
API_HASH = os.environ.get("API_HASH")
SERVICE_ACCOUNT_FILE = 'service_account.json' 

# --- ভেরিয়েবল চেক (লগে এরর দেখানোর জন্য) ---
if not BOT_TOKEN or not API_HASH:
    print("Error: BOT_TOKEN, API_ID, or API_HASH is missing in Environment Variables!")

# --- Flask অ্যাপ ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is Running Successfully!"

def run_flask():
    # Render অটোমেটিক PORT অ্যাসাইন করে
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# --- গুগল ড্রাইভ সেটআপ ---
SCOPES = ['https://www.googleapis.com/auth/drive']
def get_drive_service():
    if not os.path.exists(SERVICE_ACCOUNT_FILE):
        print("Service Account File Not Found!")
        return None
    creds = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return build('drive', 'v3', credentials=creds)

# --- পাইরোগ্রাম বট সেটআপ ---
bot = Client("my_drive_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

user_states = {}
user_data = {}

def get_id_from_url(url):
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
        "অনুগ্রহ করে **Source Google Drive Link** টি দিন:",
        reply_markup=cancel_btn
    )

@bot.on_message(filters.regex("❌ Cancel"))
async def cancel_process(client, message):
    user_id = message.from_user.id
    if user_id in user_states: del user_states[user_id]
    if user_id in user_data: del user_data[user_id]
        
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

    if state == "WAITING_SOURCE":
        file_id = get_id_from_url(text)
        if not file_id:
            await message.reply_text("ভুল লিংক! দয়া করে সঠিক গুগল ড্রাইভ লিংক দিন।")
            return
            
        user_data[user_id] = {'source_id': file_id}
        user_states[user_id] = "WAITING_DEST"
        await message.reply_text("লিংক পেয়েছি। ✅\n\nএবার **Destination Folder Link** টি দিন:")

    elif state == "WAITING_DEST":
        folder_id = get_id_from_url(text)
        if not folder_id:
            await message.reply_text("ভুল ফোল্ডার লিংক! আবার চেষ্টা করুন।")
            return

        source_id = user_data[user_id]['source_id']
        status_msg = await message.reply_text("🔄 প্রসেসিং হচ্ছে...")
        
        try:
            drive_service = get_drive_service()
            if not drive_service:
                await status_msg.edit_text("❌ Service Account ফাইল পাওয়া যায়নি।")
                return

            # ফাইলের নাম বের করা
            source_file = drive_service.files().get(fileId=source_id).execute()
            file_name = source_file.get('name')
            
            await status_msg.edit_text(f"📥 কপি হচ্ছে: `{file_name}`...")

            # কপি অপারেশন
            file_metadata = {
                'name': file_name,
                'parents': [folder_id]
            }
            drive_service.files().copy(
                fileId=source_id,
                body=file_metadata
            ).execute()

            buttons = ReplyKeyboardMarkup(
                [[KeyboardButton("📂 Copy File")]],
                resize_keyboard=True
            )
            await status_msg.delete()
            await message.reply_text(f"✅ সফল! ফাইল: `{file_name}`", reply_markup=buttons)

        except Exception as e:
            await status_msg.edit_text(f"❌ এরর: {str(e)}")
        
        # প্রসেস শেষে স্টেট ক্লিয়ার
        if user_id in user_states: del user_states[user_id]
        if user_id in user_data: del user_data[user_id]

if __name__ == "__main__":
    t = threading.Thread(target=run_flask)
    t.daemon = True
    t.start()
    bot.run()
