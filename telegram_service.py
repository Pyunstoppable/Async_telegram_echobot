import logging
import os
from pyrogram import Client, filters
import zlib
import aio_pika
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime
import json
import ast
import asyncio
from aio_pika.abc import AbstractRobustConnection, AbstractChannel
from pyrogram.types.messages_and_media.message import Message

que_first_service = 'que_first_service'
que_second_service = 'que_second_service'

TELEGRAM_API_TOKEN = os.getenv('TELEGRAM_API_TOKEN')
API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')
RABBIT_SETTINGS = os.getenv('RABBIT_SETTINGS', 'amqp://guest:guest@localhost:5672/')

logging.basicConfig(format='%(processName)s - [%(asctime)s: %(levelname)s] %(message)s')
logger = logging.getLogger("fs")
logger.setLevel(logging.INFO)
logger.info("Start service")

app = Client("tg_assist", bot_token=TELEGRAM_API_TOKEN, api_id=API_ID, api_hash=API_HASH)


async def amqp_connection() -> tuple[AbstractRobustConnection, AbstractChannel]:
    """Connecting to RabbitMQ"""
    connection = await aio_pika.connect_robust(RABBIT_SETTINGS)
    channel = await connection.channel()
    return connection, channel


async def send_to_amqp(mes: str, q: str) -> None:
    """Send messages to RabbitMQ"""
    logger.info(f" [x] Sent mess {mes}")
    mes = str(mes).encode('utf-8')
    logger.info(f"Size before compress: {len(mes)}")
    # compress message
    mes = zlib.compress(mes, level=-1)
    logger.info(f"Size after compress: {len(mes)}")
    connection, channel = await amqp_connection()
    await channel.declare_queue(q, durable=True)
    await channel.default_exchange.publish(aio_pika.Message(body=mes), routing_key=q)


async def receive_from_amqp(q: str) -> None:
    """Receive messages from RabbitMQ"""
    connection, channel = await amqp_connection()
    logger.info(' [*] Waiting for messages. To exit press CTRL+C')
    await channel.set_qos(prefetch_count=1)
    # Declaring queue
    queue = await channel.declare_queue(q, durable=True)
    async with queue.iterator() as queue_iter:
        async for message in queue_iter:
            async with message.process():
                # decompress message
                mes = zlib.decompress(message.body)
                response = ast.literal_eval(mes.decode('utf-8'))
                logger.info(f'The message was received to RabbitMQ, queue={q}')
                # send content to telegramm
                if response['type_message'] == 'text':
                    await app.send_message(chat_id=response['chat'],
                                           text=response['val'],
                                           reply_to_message_id=response['reply_id'])
                elif response['type_message'] == 'media':
                    await app.send_cached_media(chat_id=response['chat'], file_id=response['val'], reply_to_message_id=response['reply_id'])
                logger.info('The message was sent to client telegram')

                if queue.name in mes.decode():
                    break
    try:
        logger.info('start consuming')
        channel.start_consuming()
    except KeyboardInterrupt:
        channel.stop_consuming()
        exit()


@app.on_message((filters.text | filters.media) & filters.private)
async def echo(client: Client, message: Message) -> None:
    """Send/Receive telegram-messages. The media filter takes into account content such as voice,
       audio, video, photos, etc."""
    # We pack in a dictionary user-chat_id, message_id for a specific response to the same message
    if message.text:
        logger.info(f"Get text-message from user id={message.chat.id}")
        await send_to_amqp({'type_message': 'text', 'chat': message.chat.id, 'reply_id': message.id, 'val': message.text},
                           que_first_service)
    elif message.media:
        logger.info(f"Get media-message from user id={message.chat.id}")
        media_info = json.loads(str(getattr(message, message.media.value)))
        await send_to_amqp({'type_message': 'media', 'chat': message.chat.id, 'reply_id': message.id, 'val': media_info['file_id']},
                           que_first_service)

    logger.info(f'The message was sent to RabbitMQ, queue={que_first_service}')


async def start_consume() -> None:
    # We are waiting for the bot to connect
    while not app.is_connected:
        await asyncio.sleep(1)
    await receive_from_amqp(que_second_service)


if __name__ == "__main__":
    try:
        # Start consumer, start telegram
        scheduler = AsyncIOScheduler()
        scheduler.add_job(start_consume, coalesce=True, next_run_time=datetime.now(), misfire_grace_time=60)
        scheduler.start()
        app.run()
    except KeyboardInterrupt:
        pass
