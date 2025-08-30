import os
import logging
import json
import requests
import asyncio
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from threading import Thread, Timer
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from collections import defaultdict

# Configuração de logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Carrega variáveis de ambiente
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MAKE_WEBHOOK_URL = os.getenv("MAKE_WEBHOOK_URL")

if not TELEGRAM_TOKEN or not MAKE_WEBHOOK_URL:
    raise ValueError("TELEGRAM_TOKEN e MAKE_WEBHOOK_URL devem ser definidos.")

# Dicionários para gerenciar grupos de mídia
media_groups = defaultdict(list)
media_group_timers = {}

# --- Lógica do Bot Telegram ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Olá! Envie uma imagem ou galeria para processamento.")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    media_group_id = message.media_group_id
    loop = asyncio.get_running_loop()

    if not media_group_id:
        logger.info(f"Imagem única recebida (message_id: {message.message_id})")
        await process_single_image(update, context)
        return

    if media_group_id in media_group_timers:
        media_group_timers[media_group_id].cancel()

    media_groups[media_group_id].append(message)
    logger.info(
        f"Imagem de galeria recebida (media_group_id: {media_group_id}, message_id: {message.message_id}). "
        f"Total no grupo: {len(media_groups[media_group_id])}"
    )

    # CORREÇÃO: Usar asyncio.run_coroutine_threadsafe para chamar a coroutine de uma thread
    timer = Timer(
        2.0, lambda: asyncio.run_coroutine_threadsafe(process_media_group(media_group_id, context), loop)
    )
    media_group_timers[media_group_id] = timer
    timer.start()

async def process_media_group(media_group_id: str, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Processando galeria com media_group_id {media_group_id}: {len(media_groups[media_group_id])} imagens.")
    messages = media_groups.pop(media_group_id, [])
    if media_group_id in media_group_timers:
        del media_group_timers[media_group_id]

    if not messages:
        return

    caption = next((msg.caption for msg in messages if msg.caption), "")
    first_message = messages[0]

    file_urls = []
    images_details = []

    for message in messages:
        if message.photo:
            photo = max(message.photo, key=lambda p: p.width * p.height)
            try:
                file = await context.bot.get_file(photo.file_id)
                full_file_url = file.file_path
                if not full_file_url.startswith("https://"):
                     full_file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file.file_path}"

                file_urls.append(full_file_url)
                images_details.append({
                    'image_url': full_file_url,
                    'width': photo.width,
                    'height': photo.height,
                    'file_size': photo.file_size,
                    'media_type': 'IMAGE'
                    
                })
            except Exception as e:
                logger.error(f"Erro ao obter arquivo da imagem {photo.file_id}: {e}")

    if file_urls:
        await send_to_make(first_message, file_urls, images_details, caption)

async def process_single_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    photo = max(message.photo, key=lambda p: p.width * p.height)
    try:
        file = await context.bot.get_file(photo.file_id)
        full_file_url = file.file_path
        if not full_file_url.startswith("https://"):
            full_file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file.file_path}"
        
        await send_to_make(message, [full_file_url], [{
            'file_url': full_file_url,
            'width': photo.width,
            'height': photo.height,
            'file_size': photo.file_size
        }], message.caption or "")
    except Exception as e:
        logger.error(f"Erro ao processar imagem única: {e}")

async def send_to_make(message: Update, file_urls: list, images_details: list, caption: str):
    payload = {
        "user_id": message.from_user.id,
        "username": message.from_user.username,
        "file_urls": file_urls,
        "images_details": images_details,
        "total_images": len(file_urls),
        "timestamp": datetime.now().isoformat(),
        "caption": caption,
        "source_chat_name": message.chat.title or message.chat.username or "Chat Privado",
        "source_chat_id": str(message.chat.id),
        "is_carousel": len(file_urls) > 1
    }
    try:
        response = requests.post(MAKE_WEBHOOK_URL, json=payload, timeout=15)
        response.raise_for_status()
        logger.info(f"Dados enviados ao Make.com: {len(file_urls)} imagens, status: {response.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Erro ao enviar dados para o Make.com: {e}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)

# --- Servidor HTTP e Função Principal ---

class PingHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Bot is running")
        else:
            self.send_response(404)
            self.end_headers()

def run_http_server():
    port = int(os.environ.get("PORT", 8080))
    server_address = ("0.0.0.0", port)
    httpd = HTTPServer(server_address, PingHandler)
    logger.info(f"Servidor HTTP iniciado na porta {port}")
    httpd.serve_forever()

def main() -> None:
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_error_handler(error_handler)

    # Inicia o servidor HTTP em uma thread separada
    http_thread = Thread(target=run_http_server, daemon=True)
    http_thread.start()

    logger.info("Bot iniciado, aguardando mensagens...")
    application.run_polling()

if __name__ == "__main__":
    main()


