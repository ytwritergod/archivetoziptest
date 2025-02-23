import os
import logging
import shutil
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters
)
from py7zr import SevenZipFile
import pyminizip
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
CHUNK_SIZE = 2 * 1024 * 1024 * 1024  # 2GB

# Helper Functions
def clean_user_data(user_id):
    user_dir = os.path.join(TEMP_DIR, str(user_id))
    if os.path.exists(user_dir):
        shutil.rmtree(user_dir)

def get_user_dir(user_id):
    user_dir = os.path.join(TEMP_DIR, str(user_id))
    os.makedirs(user_dir, exist_ok=True)
    return user_dir

def split_file(file_path):
    part_number = 1
    base_name = os.path.basename(file_path)
    directory = os.path.dirname(file_path)
    
    with open(file_path, 'rb') as f:
        while True:
            chunk = f.read(CHUNK_SIZE)
            if not chunk:
                break
            part_name = f"{base_name}.part{part_number:03d}"
            part_path = os.path.join(directory, part_name)
            with open(part_path, 'wb') as chunk_file:
                chunk_file.write(chunk)
            yield part_path
            part_number += 1
    os.remove(file_path)

# Start Command
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
async def receive_file(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if user_id not in AUTHORIZED_USERS:
        return

    user_dir = get_user_dir(user_id)
    file = await update.message.document.get_file()
    file_path = os.path.join(user_dir, update.message.document.file_name)
    await file.download_to_drive(file_path)
    
    await update.message.reply_text(f"🗂 File saved! Total files: {len(os.listdir(user_dir))}")

# Compression Type Selection
async def choose_compress_type(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    keyboard = [
        [InlineKeyboardButton("ZIP 🗃", callback_data='zip'),
         InlineKeyboardButton("7Z 🗜", callback_data='7z')]
    ]
    await query.edit_message_text("📦 Choose compression format:", reply_markup=InlineKeyboardMarkup(keyboard))
    return COMPRESS_TYPE

# Password Handling
async def ask_password(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    context.user_data['compress_type'] = query.data
    await query.edit_message_text("🔒 Enter password for archive:")
    return PASSWORD

# Archive Name Handling
async def ask_archive_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['password'] = update.message.text
    await update.message.reply_text("✏️ Enter archive name (without extension):")
    return ARCHIVE_NAME

# Compress & Send
async def compress_and_send(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
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
        if os.path.getsize(archive_path) > CHUNK_SIZE:
            for part_path in split_file(archive_path):
                with open(part_path, 'rb') as f:
                    await update.message.reply_document(
                        document=f,
                        caption=f"📤 Part: {os.path.basename(part_path)}"
                    )
        else:
            with open(archive_path, 'rb') as f:
                await update.message.reply_document(
                    document=f,
                    caption="📤 Your compressed file!"
                )
            os.remove(archive_path)

    except Exception as e:
        logger.error(f"Error: {str(e)}")
        await update.message.reply_text("❌ Processing failed. Please try again.")
    finally:
        clean_user_data(user_id)
    
    return ConversationHandler.END

def main() -> None:
    application = ApplicationBuilder().token(TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start)],
        states={
            RECEIVING_FILES: [
                MessageHandler(filters.Document.ALL, receive_file),
                CallbackQueryHandler(choose_compress_type, pattern='^done$')
            ],
            COMPRESS_TYPE: [CallbackQueryHandler(ask_password)],
            PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_archive_name)],
            ARCHIVE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, compress_and_send)]
        },
        fallbacks=[]
    )

    application.add_handler(conv_handler)
    application.run_polling()

if __name__ == '__main__':
    main()
