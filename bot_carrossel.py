import os
import logging
import json
import requests
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
from threading import Thread
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
logger.info("Tentando carregar o arquivo .env...")
load_dotenv()
logger.info("Arquivo .env carregado com sucesso.")

# Verifica o caminho do arquivo .env
env_path = Path(".") / ".env"
logger.info(f"Procurando o arquivo .env em: {env_path.resolve()}")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
MAKE_WEBHOOK_URL = os.getenv("MAKE_WEBHOOK_URL")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")

# Verifica se as variáveis de ambiente estão definidas
if not TELEGRAM_TOKEN or not MAKE_WEBHOOK_URL or not TELEGRAM_CHANNEL_ID:
    logger.error("As variáveis TELEGRAM_TOKEN, MAKE_WEBHOOK_URL e TELEGRAM_CHANNEL_ID não foram encontradas.")
    logger.error(f"TELEGRAM_TOKEN: {TELEGRAM_TOKEN}")
    logger.error(f"MAKE_WEBHOOK_URL: {MAKE_WEBHOOK_URL}")
    logger.error(f"TELEGRAM_CHANNEL_ID: {TELEGRAM_CHANNEL_ID}")
    raise ValueError("As variáveis TELEGRAM_TOKEN, MAKE_WEBHOOK_URL e TELEGRAM_CHANNEL_ID devem ser definidas no arquivo .env")
logger.info("Variáveis TELEGRAM_TOKEN, MAKE_WEBHOOK_URL e TELEGRAM_CHANNEL_ID carregadas com sucesso.")

# Diretório para armazenar imagens temporariamente
IMAGE_DIR = Path("images")
IMAGE_DIR.mkdir(exist_ok=True)

# Inicializa a aplicação do Telegram
application = Application.builder().token(TELEGRAM_TOKEN).build()

# Dicionário para armazenar imagens de uma galeria por media_group_id
media_groups = defaultdict(list)
processed_media_groups = set()

# Classe para o servidor HTTP
class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
    """Classe que permite lidar com requisições em threads separadas."""
    pass

# Manipulador de requisições HTTP
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
            
    def do_POST(self):
        if self.path != "/webhook":
            self.send_response(404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "error", "message": "Endpoint não encontrado"}).encode("utf-8"))
            return

        try:
            # Lê o corpo da requisição
            content_length = int(self.headers["Content-Length"])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode("utf-8"))

            # Verifica se é uma lista de URLs (carrossel) ou uma única URL
            if "file_urls" in data:
                # Carrossel - múltiplas imagens
                file_urls = data["file_urls"]
                caption = data.get("caption", "Carrossel processado e enviado pelo bot.")
                source_chat_name = data.get("source_chat_name", "Desconhecido")
                source_chat_id = data.get("source_chat_id", "Desconhecido")
                logger.info("Recebido carrossel do Make.com com %d imagens", len(file_urls))

                # Envia as imagens como um grupo de mídia para o canal do Telegram
                loop = asyncio.get_event_loop()
                
                # Prepara a lista de InputMediaPhoto para o carrossel
                media_list = []
                for i, url in enumerate(file_urls):
                    if i == 0:
                        # Primeira imagem recebe o caption
                        media_list.append(InputMediaPhoto(media=url, caption=caption))
                    else:
                        # Demais imagens sem caption
                        media_list.append(InputMediaPhoto(media=url))
                
                send_media_group_coro = application.bot.send_media_group(
                    chat_id=TELEGRAM_CHANNEL_ID,
                    media=media_list
                )
                asyncio.run_coroutine_threadsafe(send_media_group_coro, loop).result()
                logger.info("Carrossel enviado para o canal %s com %d imagens", TELEGRAM_CHANNEL_ID, len(file_urls))

            elif "file_url" in data:
                # Imagem única (compatibilidade com versão anterior)
                file_url = data["file_url"]
                caption = data.get("caption", "Imagem processada e enviada pelo bot.")
                source_chat_name = data.get("source_chat_name", "Desconhecido")
                source_chat_id = data.get("source_chat_id", "Desconhecido")
                logger.info("Recebido file_url único do Make.com: %s", file_url)

                # Envia a imagem para o canal do Telegram com o caption original
                loop = asyncio.get_event_loop()
                send_photo_coro = application.bot.send_photo(
                    chat_id=TELEGRAM_CHANNEL_ID,
                    photo=file_url,
                    caption=caption
                )
                asyncio.run_coroutine_threadsafe(send_photo_coro, loop).result()
                logger.info("Imagem única enviada para o canal %s", TELEGRAM_CHANNEL_ID)
            else:
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": "file_url ou file_urls não fornecido"}).encode("utf-8"))
                return

            # Responde com sucesso
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "success", "message": "Mídia enviada ao canal"}).encode("utf-8"))

        except Exception as e:
            logger.error("Erro ao processar requisição do Make.com: %s", str(e))
            self.send_response(500)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode("utf-8"))

# Função para rodar o servidor HTTP em uma thread separada
def run_http_server():
    port = int(os.environ.get("PORT", 5000))  # Pega a porta definida pelo Render
    server_address = ("0.0.0.0", port)
    httpd = ThreadingHTTPServer(server_address, WebhookHandler)
    logger.info(f"Servidor HTTP iniciado em http://0.0.0.0:{port}")
    httpd.serve_forever()


# Função para o comando /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("Comando /start recebido de %s", update.effective_user.id)
    await update.message.reply_text("Olá! Envie uma imagem ou galeria para que eu a processe.")

# Função para processar imagens (incluindo galerias)
async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    message = update.message
    media_group_id = message.media_group_id
    chat_id = message.chat_id
    message_id = message.message_id

    # Captura o caption da mensagem
    caption = message.caption if message.caption else ""
    logger.info("Caption da mensagem: %s", caption)

    # Determina o chat de origem (se a mensagem foi encaminhada, usa forward_from_chat; caso contrário, usa o chat atual)
    source_chat_name = ""
    source_chat_id = ""
    # Verifica se a mensagem foi encaminhada usando forward_date ou forward_from
    if hasattr(message, "forward_date") and message.forward_date:
        if hasattr(message, "forward_from_chat") and message.forward_from_chat:
            source_chat_name = message.forward_from_chat.title if message.forward_from_chat.title else (message.forward_from_chat.username or "Chat Desconhecido")
            source_chat_id = str(message.forward_from_chat.id)
            logger.info("Mensagem encaminhada - Chat de Origem - Nome: %s, ID: %s", source_chat_name, source_chat_id)
        else:
            source_chat_name = "Chat Desconhecido (Encaminhado)"
            source_chat_id = "Desconhecido"
            logger.info("Mensagem encaminhada, mas forward_from_chat não disponível")
    else:
        source_chat_name = message.chat.title if message.chat.title else (message.chat.username or message.chat.first_name or "Chat Privado")
        source_chat_id = str(chat_id)
        logger.info("Mensagem não encaminhada - Chat de Origem - Nome: %s, ID: %s", source_chat_name, source_chat_id)

    # Se não for parte de uma galeria, processa imediatamente
    if not media_group_id:
        logger.info("Imagem única recebida de %s (message_id: %s)", update.effective_user.id, message_id)
        await process_single_image(update, context, caption, source_chat_name, source_chat_id)
        return

    # Se for parte de uma galeria, agrupa as imagens
    logger.info("Imagem de galeria recebida de %s (media_group_id: %s, message_id: %s)", update.effective_user.id, media_group_id, message_id)

    # Verifica se a galeria já foi processada
    if media_group_id in processed_media_groups:
        logger.info("Galeria já processada, ignorando: %s", media_group_id)
        return

    # Armazena as imagens da galeria junto com o caption, source_chat_name e source_chat_id
    media_groups[media_group_id].append((update, caption, source_chat_name, source_chat_id))

    # Aguarda brevemente para garantir que todas as imagens da galeria foram recebidas
    await asyncio.sleep(2)  # Ajuste o tempo conforme necessário

    # Verifica se é a última imagem da galeria
    if media_group_id in media_groups:
        updates_with_metadata = media_groups[media_group_id]
        logger.info("Processando galeria com media_group_id %s: %d imagens recebidas", media_group_id, len(updates_with_metadata))

        # NOVA LÓGICA: Seleciona a imagem de maior resolução de CADA imagem da galeria
        selected_images = []
        selected_caption = None
        selected_source_chat_name = None
        selected_source_chat_id = None

        for i, (u, cap, name, cid) in enumerate(updates_with_metadata):
            # Para cada imagem da galeria, seleciona a de maior resolução
            highest_resolution_photo = max(
                u.message.photo,
                key=lambda photo: photo.width * photo.height
            )
            
            # Obtém a URL da imagem
            file = await context.bot.get_file(highest_resolution_photo.file_id)
            file_url = file.file_path
            
            selected_images.append({
                "file_url": file_url,
                "width": highest_resolution_photo.width,
                "height": highest_resolution_photo.height,
                "file_size": highest_resolution_photo.file_size
            })
            
            # Usa os metadados da primeira imagem para o caption e origem
            if i == 0:
                selected_caption = cap
                selected_source_chat_name = name
                selected_source_chat_id = cid

        if selected_images:
            logger.info("Selecionadas %d imagens de maior resolução para media_group_id %s", len(selected_images), media_group_id)
            await process_carousel_images(selected_images, update, context, selected_caption, selected_source_chat_name, selected_source_chat_id)

        # Marca a galeria como processada e limpa o dicionário
        processed_media_groups.add(media_group_id)
        del media_groups[media_group_id]
        logger.info("Galeria processada e removida: %s", media_group_id)

# Função para processar uma única imagem (usada para imagens avulsas)
async def process_single_image(update: Update, context: ContextTypes.DEFAULT_TYPE, caption: str, source_chat_name: str, source_chat_id: str) -> None:
    try:
        # Verifica se a mensagem contém uma foto
        if not update.message.photo:
            await update.message.reply_text("Por favor, envie uma imagem válida.")
            return

        # Seleciona a imagem de maior resolução
        highest_resolution_photo = max(
            update.message.photo,
            key=lambda photo: photo.width * photo.height
        )
        file_id = highest_resolution_photo.file_id
        file = await context.bot.get_file(file_id)

        # Gera um nome de arquivo único baseado no timestamp e ID do usuário
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        user_id = update.effective_user.id
        file_name = f"image_{user_id}_{timestamp}.jpg"
        file_path = IMAGE_DIR / file_name

        # Baixa a imagem
        await file.download_to_drive(file_path)
        logger.info("Imagem de maior resolução baixada com sucesso: %s", file_path)

        # Envia os dados para o Make.com (formato original para compatibilidade)
        await send_single_to_make(file.file_path, file_path, update, context, caption, source_chat_name, source_chat_id)

    except Exception as e:
        logger.error("Erro ao processar a imagem: %s", str(e))
        await update.message.reply_text("Ocorreu um erro ao processar a imagem. Tente novamente mais tarde.")

# NOVA FUNÇÃO: Processa múltiplas imagens para carrossel
async def process_carousel_images(selected_images: list, update: Update, context: ContextTypes.DEFAULT_TYPE, caption: str, source_chat_name: str, source_chat_id: str) -> None:
    try:
        # Extrai apenas as URLs das imagens
        file_urls = [img["file_url"] for img in selected_images]
        
        # Envia os dados para o Make.com no novo formato de carrossel
        await send_carousel_to_make(file_urls, selected_images, update, context, caption, source_chat_name, source_chat_id)

    except Exception as e:
        logger.error("Erro ao processar o carrossel de imagens: %s", str(e))
        await update.message.reply_text("Ocorreu um erro ao processar o carrossel de imagens. Tente novamente mais tarde.")

# Função para enviar dados de imagem única ao Make.com (compatibilidade)
async def send_single_to_make(file_url: str, file_path: Path, update: Update, context: ContextTypes.DEFAULT_TYPE, caption: str, source_chat_name: str, source_chat_id: str) -> None:
    try:
        # Prepara os dados para enviar ao Make.com (formato original)
        payload = {
            "user_id": update.effective_user.id,
            "username": update.effective_user.username,
            "file_url": file_url,  # URL da imagem no Telegram
            "timestamp": datetime.now().isoformat(),
            "caption": caption,  # Inclui o caption da mensagem original
            "source_chat_name": source_chat_name,  # Inclui o nome do chat de origem
            "source_chat_id": source_chat_id  # Inclui o ID do chat de origem
        }

        # Envia a requisição para o webhook do Make.com
        response = requests.post(MAKE_WEBHOOK_URL, json=payload, timeout=10)
        response.raise_for_status()  # Levanta uma exceção se a requisição falhar
        logger.info("Dados de imagem única enviados ao Make.com com sucesso: %s", response.status_code)

    except requests.exceptions.RequestException as e:
        logger.error("Erro ao enviar dados para o Make.com: %s", str(e))
        await update.message.reply_text("Erro ao enviar os dados para o Make.com. Tente novamente mais tarde.")
    finally:
        # Remove o arquivo temporário após o envio
        if file_path.exists():
            file_path.unlink()
            logger.info("Arquivo temporário removido: %s", file_path)

# NOVA FUNÇÃO: Envia dados de carrossel ao Make.com
async def send_carousel_to_make(file_urls: list, selected_images: list, update: Update, context: ContextTypes.DEFAULT_TYPE, caption: str, source_chat_name: str, source_chat_id: str) -> None:
    try:
        # Prepara os dados para enviar ao Make.com no novo formato de carrossel
        payload = {
            "user_id": update.effective_user.id,
            "username": update.effective_user.username,
            "file_urls": file_urls,  # Lista de URLs das imagens
            "images_details": selected_images,  # Detalhes de cada imagem (resolução, tamanho, etc.)
            "total_images": len(file_urls),
            "timestamp": datetime.now().isoformat(),
            "caption": caption,  # Inclui o caption da mensagem original
            "source_chat_name": source_chat_name,  # Inclui o nome do chat de origem
            "source_chat_id": source_chat_id,  # Inclui o ID do chat de origem
            "is_carousel": True  # Flag para identificar que é um carrossel
        }

        # Envia a requisição para o webhook do Make.com
        response = requests.post(MAKE_WEBHOOK_URL, json=payload, timeout=10)
        response.raise_for_status()  # Levanta uma exceção se a requisição falhar
        logger.info("Dados de carrossel enviados ao Make.com com sucesso: %s imagens, status: %s", len(file_urls), response.status_code)

    except requests.exceptions.RequestException as e:
        logger.error("Erro ao enviar dados de carrossel para o Make.com: %s", str(e))
        await update.message.reply_text("Erro ao enviar os dados do carrossel para o Make.com. Tente novamente mais tarde.")

# Função para lidar com erros do bot
async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Erro no bot: %s", context.error)
    if update and update.message:
        await update.message.reply_text("Ocorreu um erro interno. Por favor, tente novamente.")

# Função principal
def main() -> None:
    # Adiciona os handlers do Telegram
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_error_handler(error_handler)

    logger.info("Bot iniciado, aguardando mensagens...")
    # Inicia o bot do Telegram
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    # Inicia o servidor HTTP em uma thread separada
    http_thread = Thread(target=run_http_server)
    http_thread.start()
    main()

