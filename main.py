import logging
import random
import datetime
import jwt
import pika
from fastapi import Depends
from fastapi import Depends, Header, HTTPException
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.staticfiles import StaticFiles
from jwt import PyJWTError
from pydantic import BaseModel
from pymongo import MongoClient
from starlette.status import HTTP_401_UNAUTHORIZED

app = FastAPI()

SECRET_KEY = 'nekaSkrivnost'
ALGORITHM = 'HS256'
security = HTTPBearer()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")


def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="FastAPI Swagger",
        version="1.0.0",
        description="This is a sample FastAPI application with Swagger documentation.",
        routes=app.routes,
    )
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi


def verify_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail='Signature expired. Please log in again.')
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail='Invalid token. Please log in again.')


def login_required(token: str = Header(...)) -> dict:
    try:
        data = verify_token(token)
        return data
    except PyJWTError:
        raise HTTPException(status_code=HTTP_401_UNAUTHORIZED, detail='Token is invalid!')


client = MongoClient("mongodb://mongo:27017/notification-service")
db = client["notification-service"]
notifications_collection = db["notifications"]
subscriptions_collection = db["subscriptions"]
counter_collection = db['counters']

app_name = 'notification-service'

amqp_url = 'amqp://student:student123@studentdocker.informatika.uni-mb.si:5672/'
exchange_name = 'UPP-2'
queue_name = 'UPP-2'


def get_next_sequence_value(sequence_name):
    counter = counter_collection.find_one_and_update(
        {'_id': sequence_name},
        {'$inc': {'value': 1}},
        upsert=True,
        return_document=True
    )
    return counter['value']


class NotificationCreate(BaseModel):
    title: str
    message: str


class SubscriptionCreate(BaseModel):
    user_id: str


class NotificationDelete(BaseModel):
    notification_id: str


@app.get("notifications/protected")
def protected_route(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        token = credentials.credentials
        data = verify_token(token)
        user_id = data.get('sub')
        name = data.get('name')
        return {'message': 'Access granted', 'user_id': user_id, 'name': name}
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail='Internal server error')


@app.post("/notifications/users/{id}")
def send_notification_to_user(id: str, notification: NotificationCreate, request: Request):
    correlation_id = str(random.randint(1, 99999))
    notification_data = {
        "id": get_next_sequence_value("notification_id"),
        "title": notification.title,
        "message": notification.message,
        "status": "unread",
        "user_id": id
    }
    result = notifications_collection.insert_one(notification_data)

    if result.inserted_id:
        message = ('%s INFO %s Correlation: %s [%s] - <%s>' % (
            datetime.datetime.now(), request.url, correlation_id, app_name,
            '*Klic storitve POST notification for user*'))
        connection = pika.BlockingConnection(pika.URLParameters(amqp_url))
        channel = connection.channel()

        channel.exchange_declare(exchange=exchange_name, exchange_type='direct')
        channel.queue_declare(queue=queue_name)
        channel.queue_bind(exchange=exchange_name, queue=queue_name, routing_key=queue_name)

        channel.basic_publish(exchange=exchange_name, routing_key=queue_name, body=message)

        connection.close()
        return {"message": "Notification sent successfully"}
    else:
        raise HTTPException(status_code=500, detail="Failed to send notification")


@app.post("/notifications/users")
def send_notification_to_users(users: list[str], notification: NotificationCreate, request: Request):
    notifications = []
    correlation_id = str(random.randint(1, 99999))

    for user_id in users:
        notification_data = {
            "title": notification.title,
            "message": notification.message,
            "status": "unread",
            "user_id": user_id
        }
        notifications.append(notification_data)
    result = notifications_collection.insert_many(notifications)

    if result.inserted_ids:
        message = ('%s INFO %s Correlation: %s [%s] - <%s>' % (
            datetime.datetime.now(), request.url, correlation_id, app_name,
            '*Klic storitve POST notification for users*'))
        connection = pika.BlockingConnection(pika.URLParameters(amqp_url))
        channel = connection.channel()

        channel.exchange_declare(exchange=exchange_name, exchange_type='direct')
        channel.queue_declare(queue=queue_name)
        channel.queue_bind(exchange=exchange_name, queue=queue_name, routing_key=queue_name)

        channel.basic_publish(exchange=exchange_name, routing_key=queue_name, body=message)

        connection.close()
        return {"message": "Notifications sent successfully"}
    else:
        raise HTTPException(status_code=500, detail="Failed to send notifications")


@app.post("/notifications/subscribe")
def subscribe_to_notifications(subscription: SubscriptionCreate, request: Request):
    correlation_id = str(random.randint(1, 99999))
    subscription_data = {
        "user_id": subscription.user_id
    }
    result = subscriptions_collection.insert_one(subscription_data)

    if result.inserted_id:
        message = ('%s INFO %s Correlation: %s [%s] - <%s>' % (
            datetime.datetime.now(), request.url, correlation_id, app_name, '*Klic storitve POST subscribe*'))
        connection = pika.BlockingConnection(pika.URLParameters(amqp_url))
        channel = connection.channel()

        channel.exchange_declare(exchange=exchange_name, exchange_type='direct')
        channel.queue_declare(queue=queue_name)
        channel.queue_bind(exchange=exchange_name, queue=queue_name, routing_key=queue_name)

        channel.basic_publish(exchange=exchange_name, routing_key=queue_name, body=message)

        connection.close()
        return {"message": "Subscribed to notifications successfully"}
    else:
        raise HTTPException(status_code=500, detail="Failed to subscribe to notifications")


@app.delete("/notifications/unsubscribe")
def unsubscribe_from_notifications(subscription: SubscriptionCreate, request: Request):
    correlation_id = str(random.randint(1, 99999))
    subscription_data = {
        "user_id": subscription.user_id
    }
    result = subscriptions_collection.delete_one(subscription_data)

    if result.deleted_count:
        message = ('%s INFO %s Correlation: %s [%s] - <%s>' % (
            datetime.datetime.now(), request.url, correlation_id, app_name, '*Klic storitve DELETE unsubscribe*'))
        connection = pika.BlockingConnection(pika.URLParameters(amqp_url))
        channel = connection.channel()

        channel.exchange_declare(exchange=exchange_name, exchange_type='direct')
        channel.queue_declare(queue=queue_name)
        channel.queue_bind(exchange=exchange_name, queue=queue_name, routing_key=queue_name)

        channel.basic_publish(exchange=exchange_name, routing_key=queue_name, body=message)

        connection.close()
        return {"message": "Unsubscribed from notifications successfully"}
    else:
        raise HTTPException(status_code=500, detail="Failed to unsubscribe from notifications")


@app.get("/notifications/users/{id}/history")
def get_notification_history(id: str, request: Request):
    correlation_id = str(random.randint(1, 99999))
    user_id = int(id)
    notifications = list(notifications_collection.find({"user_id": str(user_id)}))

    for notification in notifications:
        notification["_id"] = str(notification["_id"])
        message = ('%s INFO %s Correlation: %s [%s] - <%s>' % (
            datetime.datetime.now(), request.url, correlation_id, app_name, '*Klic storitve GET history*'))
        connection = pika.BlockingConnection(pika.URLParameters(amqp_url))
        channel = connection.channel()

        channel.exchange_declare(exchange=exchange_name, exchange_type='direct')
        channel.queue_declare(queue=queue_name)
        channel.queue_bind(exchange=exchange_name, queue=queue_name, routing_key=queue_name)

        channel.basic_publish(exchange=exchange_name, routing_key=queue_name, body=message)

        connection.close()
    return {"notifications": notifications}


@app.get("/notifications")
def get_notifications(user_id: str, request: Request):
    correlation_id = request.headers.get('X-Correlation-ID')
    user_id1 = int(user_id)
    user_notifications = list(notifications_collection.find({"user_id": str(user_id1)}))
    for notification in user_notifications:
        notification["_id"] = str(notification["_id"])
        message = ('%s INFO %s Correlation: %s [%s] - <%s>' % (
            datetime.datetime.now(), request.url, correlation_id, app_name, '*Klic storitve GET notifications*'))
        connection = pika.BlockingConnection(pika.URLParameters(amqp_url))
        channel = connection.channel()

        channel.exchange_declare(exchange=exchange_name, exchange_type='direct')
        channel.queue_declare(queue=queue_name)
        channel.queue_bind(exchange=exchange_name, queue=queue_name, routing_key=queue_name)

        channel.basic_publish(exchange=exchange_name, routing_key=queue_name, body=message)

        connection.close()
    return {"notifications": user_notifications}


@app.put("/notifications/{id}/read")
def mark_notification_as_read(id, request: Request):
    correlation_id = str(random.randint(1, 99999))
    result = notifications_collection.update_one({"id": int(id)}, {"$set": {"status": "read"}})

    if result.modified_count:
        message = ('%s INFO %s Correlation: %s [%s] - <%s>' % (
            datetime.datetime.now(), request.url, correlation_id, app_name, '*Klic storitve PUT read*'))
        connection = pika.BlockingConnection(pika.URLParameters(amqp_url))
        channel = connection.channel()

        channel.exchange_declare(exchange=exchange_name, exchange_type='direct')
        channel.queue_declare(queue=queue_name)
        channel.queue_bind(exchange=exchange_name, queue=queue_name, routing_key=queue_name)

        channel.basic_publish(exchange=exchange_name, routing_key=queue_name, body=message)

        connection.close()
        return {"message": "Notification marked as read"}
    else:
        logger.error("An error occurred: %s", response.status_code)
        raise HTTPException(status_code=404, detail="Notification not found")


@app.put("/notifications/{id}/unread")
def mark_notification_as_unread(id, request: Request):
    correlation_id = str(random.randint(1, 99999))
    result = notifications_collection.update_one({"id": int(id)}, {"$set": {"status": "unread"}})

    if result.modified_count:
        message = ('%s INFO %s Correlation: %s [%s] - <%s>' % (
            datetime.datetime.now(), request.url, correlation_id, app_name, '*Klic storitve PUT unread*'))
        connection = pika.BlockingConnection(pika.URLParameters(amqp_url))
        channel = connection.channel()

        channel.exchange_declare(exchange=exchange_name, exchange_type='direct')
        channel.queue_declare(queue=queue_name)
        channel.queue_bind(exchange=exchange_name, queue=queue_name, routing_key=queue_name)

        channel.basic_publish(exchange=exchange_name, routing_key=queue_name, body=message)

        connection.close()
        return {"message": "Notification marked as unread"}
    else:
        logger.error("An error occurred: %s", response.status_code)
        raise HTTPException(status_code=404, detail="Notification not found")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7000)
