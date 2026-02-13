import asyncio
import sqlite3
import os
import sys
import re
import time
import shutil
from pyrogram.errors import FloodWait, Forbidden, RPCError, PeerIdInvalid, BadRequest, MessageNotModified
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, Message, CallbackQuery

# -------------------------------------------
# CONFIGURATION & DELAY SETTINGS
# -------------------------------------------
API_ID = 38361726
API_HASH = "d5e41c77e0f53e73aa6ba0c5e4890b01"
BOT_TOKEN = "8564823023:AAF8hdcufaCOilggs9Ura0QKZOat5UU_m0c"
USER_SESSION_STRING = "BQJJWn4AkLEQahBkALf26KkBsGRvUf4oGBoYwndg7KOXYjNAe-Yj9jzUZYH39o_ZwADvgSFVvKPFay_n8Msd_Ydn2zb1SXnzp_k8_xSCiFaO8Ljq44ZXOZ4t2cP_9unJkatQjookpKz4LHNdDREoB2z-o1IgOgotTU9EtWuuN-bzPF-0qWnLTf-pSdYnZPZ8PCRRKaD7PT0wlPI4fOzfeP6DRkvX0JIccjsoGBuwy9kHONwlzTf7YD9TMtEywjKgrPrmwoGBhz10JlToBrFYp6DeueQ_XoV8xevefWHrOHbRvMf1YX_mGtak_VNFYmwQbHl0H6cEzGgiuRiyqjJtf-d7_e0dpAAAAAGNRPFXAA"

MAX_FILE_SIZE = 30 * 1024 * 1024  # 30 MB Limit 
DB_FILE = os.path.abspath("bot_data.db")

# 🔥 কাস্টম টাইমিং সেটিংস
BATCH_SIZE = 20          
BATCH_READ_DELAY = 5     
NORMAL_COPY_DELAY = 5    
PROTECTED_DL_DELAY = 3   
PROTECTED_THUMB_DELAY = 3 
PROTECTED_UP_DELAY = 3   
LONG_BREAK_COUNT = 150   
LONG_BREAK_TIME = 300    

# -------------------------------------------
# DATABASE
# -------------------------------------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS config (media_type TEXT PRIMARY KEY, channel_id INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS progress (source_id INTEGER PRIMARY KEY, last_msg_id INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS media_history (unique_id TEXT PRIMARY KEY)''')
    conn.commit()
    conn.close()

def set_config(media_type, channel_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO config (media_type, channel_id) VALUES (?, ?)", (media_type, channel_id))
    conn.commit()
    conn.close()

def get_config():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT media_type, channel_id FROM config")
    rows = c.fetchall()
    conn.close()
    return {row[0]: row[1] for row in rows}

def get_last_msg(source_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT last_msg_id FROM progress WHERE source_id=?", (source_id,))
    res = c.fetchone()
    conn.close()
    return res[0] if res else 0

def get_all_progress():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT source_id, last_msg_id FROM progress")
    rows = c.fetchall()
    conn.close()
    return rows

def update_last_msg(source_id, msg_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO progress (source_id, last_msg_id) VALUES (?, ?)", (source_id, msg_id))
    conn.commit()
    conn.close()

def delete_progress(source_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("DELETE FROM progress WHERE source_id=?", (source_id,))
    conn.commit()
    conn.close()

def is_duplicate(unique_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("SELECT 1 FROM media_history WHERE unique_id=?", (unique_id,))
    exists = c.fetchone()
    conn.close()
    return exists is not None

def save_media_id(unique_id):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO media_history (unique_id) VALUES (?)", (unique_id,))
    conn.commit()
    conn.close()

if not os.path.exists(DB_FILE):
    init_db()

# -------------------------------------------
# CLIENT SETUP
# -------------------------------------------
user_app = Client("my_userbot", api_id=API_ID, api_hash=API_HASH, session_string=USER_SESSION_STRING)
bot_app = Client("my_bot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

user_states = {}
temp_data = {}
is_copying = False
stop_signal = False

# -------------------------------------------
# HELPERS
# -------------------------------------------
def get_source_id(text):
    text = text.strip()
    if text.lstrip("-").isdigit(): return int(text)
    match = re.search(r"t\.me/c/(\d+)", text)
    if match: return int("-100" + match.group(1))
    match = re.search(r"t\.me/([\w\d_]+)", text)
    if match: return match.group(1)
    return text

def create_progress_bar(current, total, length=10):
    try:
        percent = current / total
        filled_length = int(length * percent)
        bar = '▰' * filled_length + '▱' * (length - filled_length)
        return f"{bar} {int(percent * 100)}%"
    except: return "▱▱▱▱▱▱▱▱▱▱ 0%"

# -------------------------------------------
# UI MENUS
# -------------------------------------------
def main_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🚀 স্টার্ট কপি", callback_data="start_copy"), InlineKeyboardButton("🛑 থামান", callback_data="stop_copy")],
        [InlineKeyboardButton("⚙️ সেটআপ", callback_data="setup_menu"), InlineKeyboardButton("📝 প্রগ্রেস", callback_data="manage_progress")],
        [InlineKeyboardButton("🗄️ ডাটাবেস", callback_data="db_menu"), InlineKeyboardButton("🔄 সেটিংস", callback_data="check_settings")]
    ])

def copy_mode_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Start Over (From 0)", callback_data="mode_start_over")],
        [InlineKeyboardButton("▶️ Continue", callback_data="mode_continue")],
        [InlineKeyboardButton("🔢 Custom Start", callback_data="mode_custom")],
        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]
    ])

def db_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📤 ব্যাকআপ", callback_data="backup_db"), InlineKeyboardButton("📥 রিস্টোর", callback_data="restore_db")],
        [InlineKeyboardButton("🔙 ফিরে যান", callback_data="back_main")]
    ])

def setup_menu():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📸 Photo", callback_data="set_photo"), InlineKeyboardButton("🎥 Video", callback_data="set_video")],
        [InlineKeyboardButton("🎵 Audio", callback_data="set_audio"), InlineKeyboardButton("📂 File/GIF", callback_data="set_doc")],
        [InlineKeyboardButton("🔙 ফিরে যান", callback_data="back_main")]
    ])

def cancel_btn():
    return InlineKeyboardMarkup([[InlineKeyboardButton("❌ Cancel", callback_data="cancel_action")]])

# -------------------------------------------
# HANDLERS
# -------------------------------------------
@bot_app.on_message(filters.command("start"))
async def start(client, message):
    print("✅ Command Received: /start")
    await message.reply_text("**🛡️ Logging Enabled!**\n\nTerminal e sob dekhte paben.", reply_markup=main_menu())

@bot_app.on_callback_query()
async def callback_handler(client, query: CallbackQuery):
    global is_copying, stop_signal
    data = query.data
    user_id = query.from_user.id
    msg = query.message

    try:
        if data == "back_main":
            if user_id in user_states: del user_states[user_id]
            await msg.edit_text("**🤖 মেইন মেনু:**", reply_markup=main_menu())
        
        elif data == "cancel_action":
            if user_id in user_states: del user_states[user_id]
            await msg.edit_text("❌ অপারেশন বাতিল।", reply_markup=main_menu())

        elif data == "db_menu":
            await msg.edit_text("🗄️ **ডাটাবেস অপশন:**", reply_markup=db_menu())

        elif data == "backup_db":
            if os.path.exists(DB_FILE): await msg.reply_document(DB_FILE, caption="📦 ব্যাকআপ ফাইল।")
            else: await query.answer("ডাটাবেস খালি!", show_alert=True)

        elif data == "restore_db":
            if is_copying: return await query.answer("কাজ চলাকালীন সম্ভব না!", show_alert=True)
            user_states[user_id] = "wait_db_file"
            try:
                await msg.edit_text("📥 `.db` ফাইলটি পাঠান:\n⚠️ **সতর্কতা:** রিস্টোর করার পর বট রিস্টার্ট হবে।", reply_markup=cancel_btn())
            except MessageNotModified: pass 

        elif data == "setup_menu":
            await msg.edit_text("⚙️ **মিডিয়া সেটআপ:**", reply_markup=setup_menu())
        
        elif data.startswith("set_"):
            m_type = data.split("_")[1]
            user_states[user_id] = f"wait_id_{m_type}"
            await msg.edit_text(f"👇 **{m_type.upper()}** আইডি পাঠান:", reply_markup=cancel_btn())

        elif data == "check_settings":
            conf = get_config()
            text = "**📊 সেটিংস:**\n"
            for k, v in conf.items(): text += f"- {k}: `{v}`\n"
            await msg.edit_text(text if conf else "খালি!", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="back_main")]]))

        elif data == "manage_progress":
            rows = get_all_progress()
            if not rows: return await query.answer("ডাটা নেই!", show_alert=True)
            btns = [[InlineKeyboardButton(f"ID: {r[0]} | Last: {r[1]}", callback_data=f"edit_prog_{r[0]}")] for r in rows]
            btns.append([InlineKeyboardButton("🔙 Back", callback_data="back_main")])
            await msg.edit_text("📝 **এডিট করুন:**", reply_markup=InlineKeyboardMarkup(btns))

        elif data.startswith("edit_prog_"):
            src_id = int(data.split("_")[2])
            temp_data[user_id] = src_id 
            btns = [
                [InlineKeyboardButton("✏️ সেট আইডি", callback_data="set_manual_id")],
                [InlineKeyboardButton("🔄 রিসেট", callback_data="reset_prog"), InlineKeyboardButton("🗑️ ডিলিট", callback_data="del_prog")],
                [InlineKeyboardButton("🔙 Back", callback_data="manage_progress")]
            ]
            await msg.edit_text(f"📝 Source: `{src_id}`", reply_markup=InlineKeyboardMarkup(btns))

        elif data == "set_manual_id":
            user_states[user_id] = "wait_manual_val"
            await msg.edit_text("👇 সংখ্যা পাঠান:", reply_markup=cancel_btn())

        elif data == "reset_prog":
            if temp_data.get(user_id): update_last_msg(temp_data[user_id], 0); await msg.edit_text("✅ রিসেট!", reply_markup=main_menu())

        elif data == "del_prog":
            if temp_data.get(user_id): delete_progress(temp_data[user_id]); await msg.edit_text("✅ ডিলিট!", reply_markup=main_menu())

        elif data == "start_copy":
            if is_copying: return await query.answer("কাজ চলছে!", show_alert=True)
            user_states[user_id] = "wait_source_id"
            await msg.edit_text("📥 **সোর্স আইডি/লিংক দিন:**", reply_markup=cancel_btn())
        
        elif data == "stop_copy":
            if is_copying:
                stop_signal = True
                print("🛑 Stop Signal Received!")
                await query.answer("থামানো হচ্ছে...", show_alert=True)
                await msg.edit_text("🛑 থামানো হচ্ছে...")
            else: await query.answer("কাজ চলছে না।", show_alert=True)

        elif data == "mode_start_over":
            source_input = temp_data.get(user_id, {}).get('source_input')
            if not source_input: return await msg.edit_text("❌ সেশন এক্সপায়ার্ড। আবার শুরু করুন।", reply_markup=main_menu())
            await msg.edit_text("🔄 **রিসেট হচ্ছে...**")
            status = await msg.reply("🔄 রিসেট করে শুরু হচ্ছে...", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛑 Stop", callback_data="stop_copy")]]))
            del user_states[user_id]
            asyncio.create_task(run_copy_process(source_input, status, start_mode="reset"))

        elif data == "mode_continue":
            source_input = temp_data.get(user_id, {}).get('source_input')
            if not source_input: return await msg.edit_text("❌ সেশন এক্সপায়ার্ড।", reply_markup=main_menu())
            status = await msg.reply("🔄 প্রগ্রেস চেক করা হচ্ছে...", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛑 Stop", callback_data="stop_copy")]]))
            del user_states[user_id]
            asyncio.create_task(run_copy_process(source_input, status, start_mode="continue"))

        elif data == "mode_custom":
            user_states[user_id] = "wait_custom_start_num"
            await msg.edit_text("🔢 **কত নম্বর মেসেজ থেকে শুরু করবেন?** (সংখ্যা লিখুন):", reply_markup=cancel_btn())

    except MessageNotModified:
        pass
    except Exception as e:
        print(f"❌ Callback Error: {e}")

# 🔥 পাওয়ারফুল ডাটাবেস রিস্টোর ফাংশন
@bot_app.on_message(filters.document & filters.private)
async def db_restore(client, message: Message):
    if user_states.get(message.from_user.id) == "wait_db_file" and message.document.file_name.endswith(".db"):
        status = await message.reply("⏳ **ফাইল প্রসেসিং হচ্ছে...**")
        try:
            for ext in ['', '-wal', '-shm']:
                f_path = DB_FILE + ext
                if os.path.exists(f_path):
                    try: os.remove(f_path)
                    except: pass
            
            print("📥 Downloading new DB...")
            await message.download(file_name=DB_FILE)
            
            if os.path.exists(DB_FILE):
                new_size = os.path.getsize(DB_FILE)
                print(f"✅ New DB Size: {new_size} bytes")
                
                del user_states[message.from_user.id]
                await status.edit_text(f"✅ **রিস্টোর সফল!**\n📦 সাইজ: `{new_size / 1024:.2f} KB`\n🔄 ৩ সেকেন্ডের মধ্যে রিস্টার্ট হবে...")
                
                await asyncio.sleep(3)
                
                print("🔄 Stopping clients before restart...")
                try:
                    if user_app.is_connected: await user_app.stop()
                    if bot_app.is_connected: await bot_app.stop()
                except: pass

                print("🔄 RESTARTING PROCESS NOW...")
                os.execl(sys.executable, sys.executable, *sys.argv)
            else:
                await status.edit_text("❌ ডাউনলোড ব্যর্থ হয়েছে!")
            
        except Exception as e:
            await status.edit_text(f"❌ মারাত্মক এরর: {e}")
            print(f"❌ Critical Restore Error: {e}")

@bot_app.on_message(filters.text & ~filters.command("start"))
async def input_handler(client, message: Message):
    user_id = message.from_user.id
    state = user_states.get(user_id)
    if not state: return

    if state == "wait_manual_val":
        try:
            update_last_msg(temp_data[user_id], int(message.text))
            await message.reply("✅ আপডেট হয়েছে!", reply_markup=main_menu())
            del user_states[user_id]
        except: await message.reply("❌ সংখ্যা দিন।", reply_markup=cancel_btn())

    elif state.startswith("wait_id_"):
        try:
            set_config(state.split("_")[2], int(message.text))
            await message.reply("✅ সেভ হয়েছে!", reply_markup=setup_menu())
            del user_states[user_id]
        except: await message.reply("❌ ভুল আইডি।", reply_markup=cancel_btn())

    elif state == "wait_source_id":
        temp_data[user_id] = {'source_input': message.text}
        user_states[user_id] = "wait_copy_mode"
        await message.reply(
            f"🔗 **সোর্স:** `{message.text}`\n\nকিভাবে শুরু করতে চান?",
            reply_markup=copy_mode_menu()
        )

    elif state == "wait_custom_start_num":
        try:
            custom_id = int(message.text)
            source_input = temp_data.get(user_id, {}).get('source_input')
            if not source_input: 
                del user_states[user_id]
                return await message.reply("❌ এরর! আবার শুরু করুন।", reply_markup=main_menu())
            
            del user_states[user_id]
            status = await message.reply(f"🚀 **Custom Start: {custom_id}**...", reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛑 Stop", callback_data="stop_copy")]]))
            asyncio.create_task(run_copy_process(source_input, status, start_mode="custom", custom_id=custom_id))
        except ValueError:
            await message.reply("❌ দয়া করে ইংরেজি সংখ্যা দিন।", reply_markup=cancel_btn())

# -------------------------------------------
# LOGIC
# -------------------------------------------
async def manual_copy(client, message, dest_id):
    path = None
    thumb_path = None
    try:
        print(f"📥 Downloading Protected File: {message.id}...")
        path = await message.download()
        
        await asyncio.sleep(PROTECTED_DL_DELAY)

        if not path or not os.path.exists(path) or os.path.getsize(path) == 0:
            print("❌ Download Failed: 0 Byte File")
            return False

        if message.video and message.video.thumbs:
            print("📥 Downloading Thumbnail...")
            thumb_path = await client.download_media(message.video.thumbs[0].file_id)
            await asyncio.sleep(PROTECTED_THUMB_DELAY)

        print(f"📤 Uploading Protected File: {message.id}...")
        cap = message.caption or ""

        if message.photo: 
            await client.send_photo(dest_id, path, caption=cap)
        elif message.video: 
            width = getattr(message.video, 'width', 0)
            height = getattr(message.video, 'height', 0)
            duration = getattr(message.video, 'duration', 0)
            await client.send_video(dest_id, path, caption=cap, supports_streaming=True, width=width, height=height, duration=duration, thumb=thumb_path)
        elif message.audio: 
            await client.send_audio(dest_id, path, caption=cap)
        elif message.document: 
            await client.send_document(dest_id, path, caption=cap)
        
        print(f"✅ Uploaded {message.id}, Waiting {PROTECTED_UP_DELAY}s...")
        await asyncio.sleep(PROTECTED_UP_DELAY)

        if path and os.path.exists(path): os.remove(path)
        if thumb_path and os.path.exists(thumb_path): os.remove(thumb_path)

        print("✅ Manual Copy Success!")
        return True
    except FloodWait as e:
        print(f"⚠️ Manual Copy FloodWait: {e.value}s. Stopping Task...")
        raise e  
    except Exception as e:
        print(f"❌ Manual Copy Failed: {e}")
        if path and os.path.exists(path): os.remove(path)
        if thumb_path and os.path.exists(thumb_path): os.remove(thumb_path)
        return False

def get_file_info(msg):
    if msg.photo: return msg.photo.file_unique_id, msg.photo.file_size
    if msg.video: return msg.video.file_unique_id, msg.video.file_size
    if msg.audio: return msg.audio.file_unique_id, msg.audio.file_size
    if msg.document: return msg.document.file_unique_id, msg.document.file_size
    return None, 0

async def run_copy_process(source_input, status_msg, start_mode="continue", custom_id=0):
    global is_copying, stop_signal
    is_copying = True
    stop_signal = False
    config = get_config()
    
    if not config: await status_msg.edit_text("❌ সেটআপ করা নেই!", reply_markup=main_menu()); is_copying = False; return

    # 🔥 FIX: Source ID Resolution
    try:
        raw_source = get_source_id(source_input)
        try: 
            chat = await user_app.get_chat(raw_source)
            source_id = chat.id
        except (KeyError, ValueError, BadRequest):
            # 🔥 যদি ডাইরেক্ট না পায়, তাহলে ডায়ালগ স্ক্যান করবে (Auto Fix)
            print(f"⚠️ ID {raw_source} not found in cache. Scanning dialogs...")
            found = False
            async for dialog in user_app.get_dialogs():
                if dialog.chat.id == raw_source or str(dialog.chat.id) == str(raw_source):
                    source_id = dialog.chat.id
                    found = True
                    print(f"✅ Found chat in dialogs: {dialog.chat.title} ({source_id})")
                    break
            if not found:
                await status_msg.edit_text("❌ সোর্স চ্যানেলটি খুঁজে পাওয়া যাচ্ছে না।\nঅনুগ্রহ করে নিশ্চিত করুন যে আপনার Userbot ওই চ্যানেলে জয়েন আছে এবং চ্যানেলের কোনো মেসেজ রিসেন্টলি ভিজিট করেছেন।", reply_markup=main_menu())
                is_copying = False
                return

        for ch_id in config.values():
            try: await user_app.get_chat(ch_id)
            except: pass

        if start_mode == "reset":
            update_last_msg(source_id, 0)
            last_id = 0
        elif start_mode == "custom":
            update_last_msg(source_id, custom_id - 1)
            last_id = custom_id - 1
        else: 
            last_id = get_last_msg(source_id)

        max_id = 0
        async for m in user_app.get_chat_history(source_id, limit=1): max_id = m.id

        await status_msg.edit_text(f"🚀 **Copy Started**\n📌 Source: `{source_id}`\n▶️ Start: `{last_id + 1}`\n⏳ Target: `{max_id}`")

        stats = {'copied': 0, 'skipped': 0, 'links': 0}
        curr = last_id + 1
        
        while curr <= max_id:
            if stop_signal: break
            end = min(curr + BATCH_SIZE, max_id + 1)
            ids = list(range(curr, end))
            if not ids: break

            try:
                print(f"😴 Resting {BATCH_READ_DELAY}s before reading batch {curr}-{end}...")
                await asyncio.sleep(BATCH_READ_DELAY)
                
                msgs = await user_app.get_messages(source_id, ids)
                if not isinstance(msgs, list): msgs = [msgs]
                
                for msg in msgs:
                    if stop_signal: break
                    if not msg or msg.empty: 
                        update_last_msg(source_id, curr); curr += 1; continue
                    
                    update_last_msg(source_id, msg.id); curr = msg.id + 1
                    
                    if not msg.media: continue

                    uid, size = get_file_info(msg)
                    if uid and is_duplicate(uid): 
                        print(f"⏩ Duplicate: {msg.id}")
                        stats['skipped'] += 1; continue

                    dest_id = None
                    if msg.photo: dest_id = config.get('photo')
                    elif msg.video: dest_id = config.get('video')
                    elif msg.audio: dest_id = config.get('audio')
                    elif msg.document: dest_id = config.get('doc')

                    if dest_id:
                        if stats['copied'] > 0 and stats['copied'] % LONG_BREAK_COUNT == 0:
                            print(f"☕ Long Break: {LONG_BREAK_TIME}s...")
                            await status_msg.edit_text(f"😴 **Long Break:** 5 Minutes...\n✅ Total Copied: {stats['copied']}")
                            await asyncio.sleep(LONG_BREAK_TIME)
                            await status_msg.edit_text(f"🚀 **Resuming...**")

                        if size > MAX_FILE_SIZE:
                            try:
                                link = msg.link or f"t.me/c/{str(source_id)[4:]}/{msg.id}"
                                await bot_app.send_message(dest_id, f"⚠️ **Large File**\n🔗 {link}")
                                if uid: save_media_id(uid)
                                stats['links'] += 1
                            except: pass
                        else:
                            is_success = False
                            try:
                                await msg.copy(dest_id)
                                is_success = True
                                stats['copied'] += 1
                                print(f"✅ Copied {msg.id}")
                                await asyncio.sleep(NORMAL_COPY_DELAY)
                            except FloodWait as e:
                                print(f"⚠️ FloodWait Detected: {e.value}s")
                                await status_msg.edit_text(
                                    f"⚠️ **FloodWait Detected!**\n⏳ Wait: `{e.value}` seconds.\n🛑 **কাজ থামানো হয়েছে।**\nনিচের বাটনে চাপ দিয়ে আবার শুরু করুন।",
                                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("▶️ Continue", callback_data="mode_continue")]])
                                )
                                stop_signal = True 
                                return 
                            except (Forbidden, PeerIdInvalid, BadRequest):
                                if await manual_copy(user_app, msg, dest_id): 
                                    is_success = True
                                    stats['copied'] += 1
                            except Exception as e: print(f"❌ Copy Error {msg.id}: {e}")
                            
                            if uid and is_success: save_media_id(uid)

                    if (stats['copied'] + stats['skipped']) % 5 == 0:
                        try:
                            bar = create_progress_bar(msg.id, max_id)
                            txt = f"🛡️ **Working...**\n{bar}\n🆔 Process: `{msg.id}`\n🎯 Target: `{max_id}`\n✅ Copied: **{stats['copied']}**\n⏭️ Skipped: **{stats['skipped']}**"
                            await status_msg.edit_text(txt, reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🛑 Stop", callback_data="stop_copy")]]))
                        except: pass
            
            except FloodWait as e:
                print(f"⚠️ Batch Read FloodWait: {e.value}s")
                await status_msg.edit_text(
                    f"⚠️ **FloodWait Reading!**\n⏳ Wait: `{e.value}` seconds.\n🛑 **কাজ থামানো হয়েছে।**\nনিচের বাটনে চাপ দিয়ে আবার শুরু করুন।",
                    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("▶️ Continue", callback_data="mode_continue")]])
                )
                stop_signal = True
                return
            except Exception as e: 
                print(f"❌ Batch Error: {e}"); await asyncio.sleep(5)
            
            curr = end

        if not stop_signal:
            await status_msg.edit_text(f"✅ **শেষ!**\nমোট কপি: {stats['copied']}", reply_markup=main_menu())
    except Exception as e: 
        await status_msg.edit_text(f"❌ Error: {e}")
        print(f"❌ Critical Error: {e}")
    finally: is_copying = False

async def main():
    print("🚀 Services Starting...")
    await user_app.start()
    await bot_app.start()
    print("✅ Bot Ready!")
    await idle()
    await user_app.stop()
    await bot_app.stop()

if __name__ == "__main__":
    user_app.run(main())
