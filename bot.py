import os
import logging
import zipfile
import py7zr
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    ConversationHandler,
)

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Constants
AUTHORIZED_USERS = {7821276186}  # Add your Telegram user ID here
DOWNLOAD_DIR = "downloads"
ZIP_DIR = "zips"
MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2GB

# Conversation states
SELECT_COMPRESSION, SET_PASSWORD, SET_NAME, CONFIRM = range(4)

# Store user data
user_data = {}

# Command: /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in AUTHORIZED_USERS:
        await update.message.reply_text("🚫 You are not authorized to use this bot.")
        return

    await update.message.reply_text(
        "📤 Send me files (images, videos, or documents) to zip. When done, type /done.",
        reply_markup=ReplyKeyboardMarkup([["/done"]]),
    )

# Command: /done
async def done(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in AUTHORIZED_USERS:
        await update.message.reply_text("🚫 You are not authorized to use this bot.")
        return

    if user_id not in user_data or not user_data[user_id].get("files"):
        await update.message.reply_text("📭 No files received. Send files first.")
        return

    await update.message.reply_text(
        "🗜️ Choose compression type:",
        reply_markup=ReplyKeyboardMarkup([["zip", "7z"]]),
    )
    return SELECT_COMPRESSION

# Handle compression type selection
async def select_compression(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    compression_type = update.message.text.lower()
    if compression_type not in ["zip", "7z"]:
        await update.message.reply_text("❌ Invalid option. Choose 'zip' or '7z'.")
        return SELECT_COMPRESSION

    user_data[user_id]["compression"] = compression_type
    await update.message.reply_text("🔒 Set a password for the archive (or type 'none' for no password):")
    return SET_PASSWORD

# Handle password setting
async def set_password(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    password = update.message.text
    if password.lower() == "none":
        password = None

    user_data[user_id]["password"] = password
    await update.message.reply_text("📝 Set a custom name for the archive (without extension):")
    return SET_NAME

# Handle custom name setting
async def set_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    custom_name = update.message.text
    user_data[user_id]["custom_name"] = custom_name

    # Create the archive
    await create_archive(update, user_id)
    return ConversationHandler.END

# Create the archive
async def create_archive(update: Update, user_id: int):
    files = user_data[user_id]["files"]
    compression = user_data[user_id]["compression"]
    password = user_data[user_id].get("password")
    custom_name = user_data[user_id].get("custom_name", "archive")

    archive_path = os.path.join(ZIP_DIR, f"{custom_name}.{compression}")

    try:
        if compression == "zip":
            with zipfile.ZipFile(archive_path, "w") as zipf:
                for file_path in files:
                    zipf.write(file_path, arcname=os.path.basename(file_path))
                if password:
                    zipf.setpassword(password.encode())
        elif compression == "7z":
            with py7zr.SevenZipFile(archive_path, "w", password=password) as seven_zipf:
                for file_path in files:
                    seven_zipf.write(file_path, arcname=os.path.basename(file_path))

        # Calculate size
        archive_size = os.path.getsize(archive_path)
        await update.message.reply_text(f"📦 Archive created! Size: {archive_size / 1024 / 1024:.2f} MB")

        # Send the archive
        await update.message.reply_document(document=open(archive_path, "rb"))

    except Exception as e:
        await update.message.reply_text(f"❌ Error creating archive: {e}")
    finally:
        # Clean up
        for file_path in files:
            os.remove(file_path)
        os.remove(archive_path)
        user_data.pop(user_id, None)

# Handle incoming files (images, videos, documents)
async def handle_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    if user_id not in AUTHORIZED_USERS:
        await update.message.reply_text("🚫 You are not authorized to use this bot.")
        return

    # Check if the message contains a document, photo, or video
    if update.message.document:
        file = update.message.document
    elif update.message.photo:
        file = update.message.photo[-1]  # Get the highest resolution photo
    elif update.message.video:
        file = update.message.video
    else:
        await update.message.reply_text("❌ Unsupported file type.")
        return

    # Download the file
    file_path = os.path.join(DOWNLOAD_DIR, f"{file.file_id}_{file.file_name if hasattr(file, 'file_name') else file.file_unique_id}.dat")
    await file.get_file().download_to_drive(file_path)

    # Store file path
    if user_id not in user_data:
        user_data[user_id] = {"files": []}
    user_data[user_id]["files"].append(file_path)

    await update.message.reply_text(f"🗃️ File received: {file.file_name if hasattr(file, 'file_name') else 'file'}")

# Main function
def main():
    # Get the bot token from environment variables
    bot_token = os.getenv("BOT_TOKEN")
    if not bot_token:
        raise ValueError("Please set the BOT_TOKEN environment variable.")

    # Create necessary directories
    os.makedirs(DOWNLOAD_DIR, exist_ok=True)
    os.makedirs(ZIP_DIR, exist_ok=True)

    # Build the application
    application = ApplicationBuilder().token(bot_token).build()

    # Conversation handler
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("done", done)],
        states={
            SELECT_COMPRESSION: [MessageHandler(filters.TEXT & ~filters.COMMAND, select_compression)],
            SET_PASSWORD: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_password)],
            SET_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_name)],
        },
        fallbacks=[],
    )

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(conv_handler)
    application.add_handler(MessageHandler(filters.Document.ALL | filters.PHOTO | filters.VIDEO, handle_file))

    # Start the bot
    application.run_polling()

if __name__ == "__main__":
    main()
