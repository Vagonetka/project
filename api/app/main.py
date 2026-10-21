import logging
import random
import time

from fastapi import FastAPI, HTTPException, Request, Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from . import data
from .logging_config import setup_logging
from .metrics import (
    REGISTRY,
    RESOURCE_VIEWS_TOTAL,
    ORDERS_CREATED_TOTAL,
    USERS_COUNT,
    ORDERS_COUNT,
)
from .middleware import MetricsMiddleware
from .models import (
    User,
    UserCreate,
    Order,
    OrderCreate,
    HealthResponse,
)

APP_VERSION = "1.0.0"

setup_logging()
log = logging.getLogger("client-api")

app = FastAPI(title="Client API", version=APP_VERSION)
app.add_middleware(MetricsMiddleware)

@app.get("/health", response_model=HealthResponse, tags=["system"])
def health():
    return {"status": "ok", "version": APP_VERSION}


@app.get("/metrics", tags=["system"])
def metrics():
    users, orders = data.counts()
    USERS_COUNT.set(users)
    ORDERS_COUNT.set(orders)
    return Response(generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)

@app.get("/api/users", response_model=list[User], tags=["users"])
def get_users():
    RESOURCE_VIEWS_TOTAL.labels(resource="users_list").inc()
    users = data.list_users()
    log.info(
        "list users",
        extra={"extra_fields": {"endpoint": "/api/users", "count": len(users)}},
    )
    return users

@app.get("/api/users/{user_id}", response_model=User, tags=["users"])
def get_user(user_id: int):
    RESOURCE_VIEWS_TOTAL.labels(resource="user_detail").inc()
    user = data.get_user(user_id)
    if not user:
        log.warning(
            "user not found",
            extra={"extra_fields": {"endpoint": "/api/users/{id}", "user_id": user_id}},
        )
        raise HTTPException(status_code=404, detail="User not found")
    log.info(
        "get user",
        extra={"extra_fields": {"endpoint": "/api/users/{id}", "user_id": user_id}},
    )
    return user

@app.post("/api/users", response_model=User, status_code=201, tags=["users"])
def create_user(payload: UserCreate):
    time.sleep(random.uniform(0.01, 0.08))
    user = data.create_user(payload.name, payload.email)
    log.info(
        "user created",
        extra={"extra_fields": {
            "endpoint": "/api/users",
            "user_id": user["id"],
            "email": payload.email,
        }},
    )
    return user

@app.get("/api/orders", response_model=list[Order], tags=["orders"])
def get_orders():
    RESOURCE_VIEWS_TOTAL.labels(resource="orders_list").inc()
    orders = data.list_orders()
    log.info(
        "list orders",
        extra={"extra_fields": {"endpoint": "/api/orders", "count": len(orders)}},
    )
    return orders

@app.get("/api/orders/{order_id}", response_model=Order, tags=["orders"])
def get_order(order_id: int):
    RESOURCE_VIEWS_TOTAL.labels(resource="order_detail").inc()
    order = data.get_order(order_id)
    if not order:
        log.warning(
            "order not found",
            extra={"extra_fields": {"endpoint": "/api/orders/{id}", "order_id": order_id}},
        )
        raise HTTPException(status_code=404, detail="Order not found")
    log.info(
        "get order",
        extra={"extra_fields": {"endpoint": "/api/orders/{id}", "order_id": order_id}},
    )
    return order

@app.post("/api/orders", response_model=Order, status_code=201, tags=["orders"])
def create_order(payload: OrderCreate):
    if not data.get_user(payload.user_id):
        log.warning(
            "order rejected: user does not exist",
            extra={"extra_fields": {
                "endpoint": "/api/orders",
                "user_id": payload.user_id,
                "amount": payload.amount,
            }},
        )
        raise HTTPException(status_code=400, detail="User does not exist")
    time.sleep(random.uniform(0.02, 0.15))
    order = data.create_order(payload.user_id, payload.amount)
    ORDERS_CREATED_TOTAL.inc()
    log.info(
        "order created",
        extra={"extra_fields": {
            "endpoint": "/api/orders",
            "order_id": order["id"],
            "user_id": payload.user_id,
            "amount": payload.amount,
        }},
    )
    return order

@app.get("/api/slow", tags=["debug"])
def slow_endpoint():
    time.sleep(random.uniform(0.5, 2.0))
    if random.random() < 0.2:
        log.error(
            "failure on slow endpoint",
            extra={"extra_fields": {"endpoint": "/api/slow"}},
        )
        raise HTTPException(status_code=500, detail="Simulated failure")
    log.info("slow endpoint ok", extra={"extra_fields": {"endpoint": "/api/slow"}})
    return {"status": "slow but ok"}