from datetime import datetime, timezone
from threading import Lock
from typing import Optional

_lock = Lock()

USERS: dict[int, dict] = {
    1: {"id": 1, "name": "Alice", "email": "alice@example.com"},
    2: {"id": 2, "name": "Bob", "email": "bob@example.com"},
    3: {"id": 3, "name": "Charlie", "email": "charlie@example.com"},
}

ORDERS: dict[int, dict] = {
    1: {"id": 1, "user_id": 1, "amount": 99.9, "status": "paid"},
    2: {"id": 2, "user_id": 2, "amount": 15.0, "status": "pending"},
}

_user_seq = 3
_order_seq = 2


def list_users() -> list[dict]:
    with _lock:
        return list(USERS.values())


def get_user(user_id: int) -> Optional[dict]:
    with _lock:
        return USERS.get(user_id)


def create_user(name: str, email: str) -> dict:
    global _user_seq
    with _lock:
        _user_seq += 1
        user = {
            "id": _user_seq,
            "name": name,
            "email": email,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        USERS[_user_seq] = user
        return user


def list_orders() -> list[dict]:
    with _lock:
        return list(ORDERS.values())


def get_order(order_id: int) -> Optional[dict]:
    with _lock:
        return ORDERS.get(order_id)


def create_order(user_id: int, amount: float) -> dict:
    global _order_seq
    with _lock:
        _order_seq += 1
        order = {
            "id": _order_seq,
            "user_id": user_id,
            "amount": amount,
            "status": "pending",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        ORDERS[_order_seq] = order
        return order


def counts() -> tuple[int, int]:
    with _lock:
        return len(USERS), len(ORDERS)