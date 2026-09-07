import os
import subprocess
import logging
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

load_dotenv('/root/.env')

BOT_TOKEN = os.getenv('BOT_TOKEN')
DOWNLOAD_DIR = '/tmp/downloads'
OUTPUT_DIR = '/tmp/outputs'

os.makedirs(DOWNLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

encoding_in_progress = False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 שלח קובץ טורנט ואני אקודד אותו!"
    )

async def handle_torrent(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global encoding_in_progress
    
    if encoding_in_progress:
        await update.message.reply_text("⏳ כבר מקודד קובץ, חכה...")
        return
    
    encoding_in_progress = True
    
    try:
        await update.message.reply_text("⬇️ מוריד קובץ מהטורנט...")
        
        # הורד קובץ הטורנט
        torrent_file = os.path.join(DOWNLOAD_DIR, "temp.torrent")
        torrent_doc = update.message.document
        file = await context.bot.get_file(torrent_doc.file_id)
        await file.download_to_drive(torrent_file)
        
        # הורד דרך aria2c
        output_file = os.path.join(DOWNLOAD_DIR, "video.mkv")
        subprocess.run(['aria2c', torrent_file, '-d', DOWNLOAD_DIR], check=True)
        
        await update.message.reply_text("🎬 מתחיל קידוד...")
        
        # קידוד
        encoded_file = os.path.join(OUTPUT_DIR, "encoded.mp4")
        cmd = [
            'ffmpeg', '-i', output_file,
            '-c:v', 'libx265', '-crf', '20',
            '-c:a', 'aac', '-b:a', '128k',
            encoded_file
        ]
        subprocess.run(cmd, check=True)
        
        file_size = os.path.getsize(encoded_file) / (1024**3)
        
        if file_size <= 4:
            await update.message.reply_text("✅ שולח לטלגרם...")
            with open(encoded_file, 'rb') as f:
                await context.bot.send_document(chat_id=update.effective_chat.id, document=f)
        else:
            await update.message.reply_text(f"📥 הקובץ גדול ({file_size:.2f}GB)")
        
        os.remove(torrent_file)
        
    except Exception as e:
        await update.message.reply_text(f"❌ שגיאה: {str(e)}")
    
    finally:
        encoding_in_progress = False

def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_torrent))
    logger.info("🚀 הבוט התחיל!")
    app.run_polling()

if __name__ == '__main__':
    main()
