# 🤖 Carrosselbot (Telegram Media Handler)

Este bot do Telegram atua como um intermediário inteligente para ingestão de imagens e galerias (carrosséis). Ele escuta mensagens contendo fotos, agrupa mídias enviadas em sequência (álbuns) e encaminha os dados consolidados para um Webhook do **Make.com** (antigo Integromat).

Ideal para automatizar postagens em redes sociais onde a entrada de dados inicia-se pelo envio de fotos em um chat do Telegram.

![Telegram Bot API](https://img.shields.io/badge/Telegram-Bot%20API-blue)
![Python](https://img.shields.io/badge/Python-Asyncio-yellow)
![Make](https://img.shields.io/badge/Integration-Make.com-purple)

## ⚙️ Funcionalidades

*   **Processamento de Imagem Única**: Detecta e reencaminha fotos individuais.
*   **Suporte a Álbuns (Media Groups)**: Agrupa automaticamente múltiplas fotos enviadas como um álbum (galeria) no Telegram em um único payload JSON.
*   **Buffer Inteligente**: Utiliza um timer para aguardar o recebimento completo de todas as imagens de um grupo antes do disparo.
*   **Health Check HTTP**: Inclui um servidor HTTP simples para manter o bot ativo em plataformas de cloud (ex: Render, Railway) que exigem uma porta aberta.
*   **Logs Detalhados**: Registro de todas as operações para fácil debug.

## 📦 Payload Enviado ao Make

Quando o bot envia dados para o webhook, o JSON possui a seguinte estrutura:

```json
{
  "user_id": 123456789,
  "username": "usuario_telegram",
  "file_urls": ["https://api.telegram.org/file/...", "..."],
  "images_details": [
    {
      "image_url": "...",
      "width": 1080,
      "height": 1080,
      "file_size": 102400,
      "media_type": "IMAGE"
    }
  ],
  "total_images": 2,
  "timestamp": "2023-10-27T10:00:00",
  "caption": "Legenda da foto",
  "source_chat_name": "Nome do Chat",
  "is_carousel": true
}
```

## 🛠️ Configuração e Instalação

### Pré-requisitos
*   Python 3.8+
*   Token do Bot (via @BotFather)
*   URL do Webhook do Make.com

### Variáveis de Ambiente
Crie um arquivo `.env` na raiz ou configure no seu painel de hospedagem:

```env
TELEGRAM_TOKEN=seu_token_aqui
MAKE_WEBHOOK_URL=sua_url_webhook_aqui
PORT=8080 (opcional, padrão 8080)
```

### Execução Local

1.  Instale as dependências:
    ```bash
    pip install -r requirements.txt
    ```
2.  Inicie o bot:
    ```bash
    python bot_carrossel.py
    ```

## 📝 Licença

Desenvolvido por [Gleisson Santos](https://github.com/gleisson-santos).
