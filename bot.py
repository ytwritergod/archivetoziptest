import os
import logging
import shutil
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Updater, CommandHandler, MessageHandler, Filters,
    CallbackQueryHandler, ConversationHandler, CallbackContext
)
from py7zr import SevenZipFile
import pyminizip
from pysplit import Splitter
from dotenv import load_dotenv

# Load Environment Variables
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
AUTHORIZED_USERS = set(map(int, os.getenv("AUTHORIZED_USERS", "").split(',')))

# Logging Setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot States
RECEIVING_FILES, COMPRESS_TYPE, PASSWORD, ARCHIVE_NAME = range(4)
TEMP_DIR = "temp_files"
MAX_SIZE = 2 * 1024 * 1024 * 1024  # 2GB

# Helper Functions
def clean_user_data(user_id):
    user_dir = os.path.join(TEMP_DIR, str(user_id))
    if os.path.exists(user_dir):
        shutil.rmtree(user_dir)

def get_user_dir(user_id):
    user_dir = os.path.join(TEMP_DIR, str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    return user_dir

# Start Command
async def start(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    if user_id not in AUTHORIZED_USERS:
        await update.message.reply_text("🚫 You are not authorized!")
        return ConversationHandler.END
    
    clean_user_data(user_id)
    await update.message.reply_text(
        "📁 Send me files to compress. Click /done when finished!",
        reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("Done ✅", callback_data='done')]])
    )
    return RECEIVING_FILES

# File Handler
async def receive_file(update: Update, context: CallbackContext) -> None:
    user_id = update.effective_user.id
    if user_id not in AUTHORIZED_USERS:
        return

    user_dir = get_user_dir(user_id)
    file = await update.message.document.get_file()
    file_path = os.path.join(user_dir, update.message.document.file_name)
    await file.download_to_drive(file_path)
    
    await update.message.reply_text(f"🗂 File saved! Total files: {len(os.listdir(user_dir))}")

# Compression Type Selection
async def choose_compress_type(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("ZIP 🗃", callback_data='zip'),
         InlineKeyboardButton("7Z 🗜", callback_data='7z')]
    ]
    await query.edit_message_text("📦 Choose compression format:", reply_markup=InlineKeyboardMarkup(keyboard))
    return COMPRESS_TYPE

# Password Handling
async def ask_password(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['compress_type'] = query.data
    await query.edit_message_text("🔒 Enter password for archive:")
    return PASSWORD

# Archive Name Handling
async def ask_archive_name(update: Update, context: CallbackContext) -> int:
    context.user_data['password'] = update.message.text
    await update.message.reply_text("✏️ Enter archive name (without extension):")
    return ARCHIVE_NAME

# File Splitting Function
def split_large_file(file_path):
    splitter = Splitter(file_path)
    split_prefix = f"{file_path}.part"
    splitter.split(MAX_SIZE, split_prefix=split_prefix)
    return sorted([f for f in os.listdir(os.path.dirname(file_path)) if f.startswith(os.path.basename(split_prefix))])

# Compress & Send
async def compress_and_send(update: Update, context: CallbackContext) -> int:
    user_id = update.effective_user.id
    user_dir = get_user_dir(user_id)
    files = [os.path.join(user_dir, f) for f in os.listdir(user_dir)]
    
    archive_name = f"{update.message.text}.{context.user_data['compress_type']}"
    password = context.user_data['password']
    archive_path = os.path.join(user_dir, archive_name)

    try:
        # Create Archive
        if context.user_data['compress_type'] == 'zip':
            pyminizip.compress_multiple(files, [], archive_path, password, 5)
        elif context.user_data['compress_type'] == '7z':
            with SevenZipFile(archive_path, 'w', password=password) as archive:
                for file in files:
                    archive.write(file, os.path.basename(file))

        # Split and Send
        if os.path.getsize(archive_path) > MAX_SIZE:
            parts = split_large_file(archive_path)
            for part in parts:
                part_path = os.path.join(user_dir, part)
                with open(part_path, 'rb') as f:
                    await update.message.reply_document(document=f, caption=f"📤 Part: {part}")
                os.remove(part_path)
            os.remove(archive_path)
        else:
            with open(archive_path, 'rb') as f:
                await update.message.reply_document(document=f, caption="📤 Your compressed file!")
            os.remove(archive_path)

    except Exception as e:
        logger.error(f"Compression error: {str(e)}")
        await update.message.reply_text("❌ Error processing files. Please try again.")
    finally:
        clean_user_data(user_id)
    
    return ConversationHandler.END

def main() -> None:
    updater = Updater(TOKEN)
    dp = updater.dispatcher

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            RECEIVING_FILES: [
                MessageHandler(Filters.document, receive_file),
                CallbackQueryHandler(choose_compress_type, pattern='done')
            ],
            COMPRESS_TYPE: [CallbackQueryHandler(ask_password)],
            PASSWORD: [MessageHandler(Filters.text & ~Filters.command, ask_archive_name)],
            ARCHIVE_NAME: [MessageHandler(Filters.text & ~Filters.command, compress_and_send)]
        },
        fallbacks=[]
    )

    dp.add_handler(conv_handler)
    updater.start_polling()
    updater.idle()

if __name__ == '__main__':
    main()
