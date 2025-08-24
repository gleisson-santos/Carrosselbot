import os
import logging
import json
import requests
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from threading import Thread, Timer
from telegram import Update, InputMediaPhoto
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from collections import defaultdict
import asyncio

# Configuração de logging para depuração
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Carrega variáveis de ambiente do arquivo .env
load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MAKE_WEBHOOK_URL = os.getenv("MAKE_WEBHOOK_URL")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")

if not TELEGRAM_TOKEN or not MAKE_WEBHOOK_URL or not TELEGRAM_CHANNEL_ID:
    raise ValueError("As variáveis TELEGRAM_TOKEN, MAKE_WEBHOOK_URL e TELEGRAM_CHANNEL_ID devem ser definidas no arquivo .env")

# Dicionários para gerenciar grupos de mídia e temporizadores
media_groups = defaultdict(list)
media_group_timers = {}

# Inicializa a aplicação do Telegram
application = Application.builder().token(TELEGRAM_TOKEN).build()

# --- Servidor HTTP para Webhooks (Opcional, mas bom para Render) ---
class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    pass

class WebhookHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/ping":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Pong! Online")
        else:
            self.send_response(404)
            self.end_headers()

def run_http_server():
    port = int(os.environ.get("PORT", 8080))
    server_address = ("0.0.0.0", port)
    httpd = ThreadingHTTPServer(server_address, WebhookHandler)
    logger.info(f"Servidor HTTP iniciado em http://0.0.0.0:{port}")
    httpd.serve_forever()

# --- Lógica do Bot Telegram ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Olá! Envie uma imagem ou galeria para que eu a processe para o Make.com.")

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    media_group_id = message.media_group_id

    # Se não for parte de uma galeria, processa imediatamente
    if not media_group_id:
        logger.info(f"Imagem única recebida (message_id: {message.message_id})")
        await process_single_image(update, context)
        return

    # Se a galeria já tem um timer, cancela o antigo
    if media_group_id in media_group_timers:
        media_group_timers[media_group_id].cancel()

    # Armazena a imagem no grupo correspondente
    media_groups[media_group_id].append(message)
    logger.info(f"Imagem de galeria recebida (media_group_id: {media_group_id}, message_id: {message.message_id}). Total no grupo: {len(media_groups[media_group_id])}")

    # Cria um novo timer para processar a galeria após um curto período de inatividade
    timer = Timer(2.0, lambda: asyncio.run(process_media_group(media_group_id, context)))
    media_group_timers[media_group_id] = timer
    timer.start()

async def process_media_group(media_group_id: str, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Processando galeria com media_group_id {media_group_id}: {len(media_groups[media_group_id])} imagens recebidas.")

    messages = media_groups[media_group_id]
    if not messages:
        return

    # Usa o caption da primeira mensagem que o tiver
    caption = ""
    for msg in messages:
        if msg.caption:
            caption = msg.caption
            break

    # Pega informações do chat da primeira mensagem
    first_message = messages[0]
    user_id = first_message.from_user.id
    username = first_message.from_user.username
    source_chat_name = first_message.chat.title or first_message.chat.username or "Chat Privado"
    source_chat_id = str(first_message.chat.id)

    file_urls = []
    images_details = []

    for message in messages:
        if message.photo:
            highest_resolution_photo = max(message.photo, key=lambda p: p.width * p.height)
            try:
                file = await context.bot.get_file(highest_resolution_photo.file_id)
                # Constrói a URL completa do arquivo
                full_file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file.file_path}"
                file_urls.append(full_file_url)
                images_details.append({
                    'file_url': full_file_url,
                    'width': highest_resolution_photo.width,
                    'height': highest_resolution_photo.height,
                    'file_size': highest_resolution_photo.file_size
                })
            except Exception as e:
                logger.error(f"Erro ao obter arquivo da imagem {highest_resolution_photo.file_id}: {e}")

    if file_urls:
        await send_to_make(user_id, username, caption, source_chat_name, source_chat_id, file_urls, images_details)

    # Limpa a galeria e o timer
    if media_group_id in media_groups:
        del media_groups[media_group_id]
    if media_group_id in media_group_timers:
        del media_group_timers[media_group_id]
    logger.info(f"Galeria processada e removida: {media_group_id}")

async def process_single_image(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message
    highest_resolution_photo = max(message.photo, key=lambda p: p.width * p.height)
    try:
        file = await context.bot.get_file(highest_resolution_photo.file_id)
        full_file_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file.file_path}"
        await send_to_make(
            update.effective_user.id,
            update.effective_user.username,
            message.caption or "",
            message.chat.title or message.chat.username or "Chat Privado",
            str(message.chat.id),
            [full_file_url], # Envia como lista para manter consistência
            [{
                'file_url': full_file_url,
                'width': highest_resolution_photo.width,
                'height': highest_resolution_photo.height,
                'file_size': highest_resolution_photo.file_size
            }]
        )
    except Exception as e:
        logger.error(f"Erro ao processar imagem única: {e}")

async def send_to_make(user_id, username, caption, source_chat_name, source_chat_id, file_urls, images_details):
    is_carousel = len(file_urls) > 1
    payload = {
        "user_id": user_id,
        "username": username,
        "file_urls": file_urls,
        "images_details": images_details,
        "total_images": len(file_urls),
        "timestamp": datetime.now().isoformat(),
        "caption": caption,
        "source_chat_name": source_chat_name,
        "source_chat_id": source_chat_id,
        "is_carousel": is_carousel
    }

    try:
        response = requests.post(MAKE_WEBHOOK_URL, json=payload, timeout=15)
        response.raise_for_status()
        logger.info(f"Dados enviados ao Make.com com sucesso: {len(file_urls)} imagens, status: {response.status_code}")
    except requests.exceptions.RequestException as e:
        logger.error(f"Erro ao enviar dados para o Make.com: {e}")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Exception while handling an update:", exc_info=context.error)

def main() -> None:
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_error_handler(error_handler)

    # Inicia o servidor HTTP em uma thread separada para o Render
    http_thread = Thread(target=run_http_server, daemon=True)
    http_thread.start()

    logger.info("Bot iniciado, aguardando mensagens...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()


