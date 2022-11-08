import ast
import asyncio
import logging
import os
import zlib
from datetime import datetime

import aio_pika
from aio_pika.abc import AbstractChannel, AbstractRobustConnection
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from pyrogram.types.bots_and_keyboards.callback_query import CallbackQuery
from pyrogram.types.messages_and_media.message import Message


logging.basicConfig(format='%(processName)s - [%(asctime)s: %(levelname)s] %(message)s')
logger = logging.getLogger("fs")
logger.setLevel(logging.INFO)
logger.info("Start service")

que_first_service = 'que_first_service'
que_second_service = 'que_second_service'

TELEGRAM_API_TOKEN = os.getenv('TELEGRAM_API_TOKEN')
API_ID = os.getenv('API_ID')
API_HASH = os.getenv('API_HASH')
RABBIT_SETTINGS = os.getenv('RABBIT_SETTINGS', 'amqp://guest:guest@localhost:5672/')

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
                if response['flag'] == 1:
                    await app.send_message(chat_id=response['chat'], text='Начните новый заказ с команды /start')
                elif response['flag'] == 2:
                    await app.send_message(chat_id=response['chat'], text=response['list_order'])
                else:
                    text, reply_markup = get_keyboard_answer(response['state'])
                    await app.send_message(chat_id=response['chat'], text=text, reply_markup=reply_markup)

                logger.info("The message was sent to client telegram")

                if queue.name in mes.decode():
                    break
    try:
        logger.info('start consuming')
        channel.start_consuming()
    except KeyboardInterrupt:
        channel.stop_consuming()
        exit()


def get_keyboard_answer(current_state: str) -> tuple[str, InlineKeyboardMarkup]:
    """We return a response to the
    user based on the state FSM.
    Each state has its own set of keyboards and questions"""

    if '>>' in current_state:
        size, payment = current_state.split('>>')
        dist_assoc = {current_state: ['Да', 'Отменить', f'Вы хотите {size.lower()} пиццу, оплата - {payment.lower()}?']}

    elif current_state == 'full':
        return 'Спасибо за заказ!\nДля просмотра заказов команда /hist', None

    elif current_state == 'cancel':
        return 'Заказ отменен!', None
    else:
        dist_assoc = {'empty': ['Большую', 'Маленькую', 'Создание заказа:\nКакую вы хотите пиццу?\nБольшую или маленькую?'],
                      'Большую': ['Наличкой', 'Картой', 'Как вы будете платить?'],
                      'Маленькую': ['Наличкой', 'Картой', 'Как вы будете платить?']}

    inline_btn_1 = InlineKeyboardButton(dist_assoc[current_state][0], callback_data=dist_assoc[current_state][0])
    inline_btn_2 = InlineKeyboardButton(dist_assoc[current_state][1], callback_data=dist_assoc[current_state][1])
    inline_kb = InlineKeyboardMarkup([[inline_btn_1, inline_btn_2]])
    answer = dist_assoc[current_state][2]
    return answer, inline_kb


@app.on_message((filters.command(commands=['start', 'hist'])) & filters.private)
async def start(client: Client, message: Message) -> None:
    await send_to_amqp({'type_message': 'command', 'chat': message.chat.id, 'val': message.text}, que_first_service)


@app.on_callback_query()
async def answer(client: Client, callback_query: CallbackQuery):
    await send_to_amqp({'type_message': 'callback', 'chat': callback_query.message.chat.id, 'val': callback_query.data},
                       que_first_service)


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
