### Async telegram bot

This bot receives and sends telegram messages using RabbitMQ to order pizza (test-case)

### Reqiurements

[Aio-pika](https://aio-pika.readthedocs.io/en/latest/)

[APScheduler](https://pypi.org/project/APScheduler/)

[Pyrogram](https://github.com/pyrogram/pyrogram)

### Description

The bot receives sends and receives messages and user callbacks to the RabbitMQ queue,
then returns the necessary keyboards and answers to the messenger,
focusing on the service for ordering pizza using the state of the machine in another service.

### Where do we start?

1. Need to get bot-token from @BotFather
2. Get your own Telegram API key (api_id, api_hash) from https://my.telegram.org/apps
3. Set Environment Variables: TELEGRAM_API_TOKEN(bot-token), API_ID, API_HASH.
   You can also set the settings RABBIT_SETTINGS or skip, then the standard ones will be used

### Run service

python telegram_service.py

### Run service in Docker

#### Rabbit
docker run -d --hostname my-rabbit --name some-rabbit -p 8080:15672 -p 5672:5672 rabbitmq:3-management

#### Service
1. docker build --rm --network host -f ./Dockerfile -t async_tbot_service:latest .
2. docker run --network=host --hostname=async_tbot_service -d --name=async_tbot_service -e "RABBIT_SETTINGS=amqp://guest:guest@localhost:5672/" -e "TELEGRAM_API_TOKEN=your" -e "API_ID=your" -e "API_HASH=your" async_tbot_service:latest
