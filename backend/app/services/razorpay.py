import razorpay
from razorpay.errors import BadRequestError, ServerError

from app.config import get_settings


# razorpay client - uses test mode keys from env
def get_razorpay_client() -> razorpay.Client:
    settings = get_settings()
    if not settings.razorpay_key_id or not settings.razorpay_key_secret:
        raise RuntimeError("Razorpay keys not configured")
    return razorpay.Client(auth=(settings.razorpay_key_id, settings.razorpay_key_secret))


# create a new order
def create_order(amount: int, currency: str, receipt: str) -> dict:
    """create razorpay order. amount is in paise."""
    client = get_razorpay_client()
    try:
        order = client.order.create({
            "amount": amount,
            "currency": currency,
            "receipt": receipt,
        })
        return order
    except BadRequestError as e:
        raise ValueError(f"Razorpay bad request: {e}") from e
    except ServerError as e:
        raise RuntimeError(f"Razorpay server error: {e}") from e


# get payment details by id
def get_payment(payment_id: str) -> dict:
    """retrieve payment details from razorpay."""
    client = get_razorpay_client()
    try:
        payment = client.payment.fetch(payment_id)
        return payment
    except BadRequestError as e:
        raise ValueError(f"Payment not found: {e}") from e
    except ServerError as e:
        raise RuntimeError(f"Razorpay server error: {e}") from e


# get order details by id
def get_order(order_id: str) -> dict:
    """retrieve order details from razorpay."""
    client = get_razorpay_client()
    try:
        order = client.order.fetch(order_id)
        return order
    except BadRequestError as e:
        raise ValueError(f"Order not found: {e}") from e
    except ServerError as e:
        raise RuntimeError(f"Razorpay server error: {e}") from e


# verify payment signature - important for security
def verify_payment_signature(razorpay_order_id: str, razorpay_payment_id: str, razorpay_signature: str) -> bool:
    """verify that payment signature is valid."""
    client = get_razorpay_client()
    try:
        client.utility.verify_payment_signature({
            "razorpay_order_id": razorpay_order_id,
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_signature": razorpay_signature,
        })
        return True
    except Exception:
        return False


# get payment status - simple helper
def get_payment_status(payment_id: str) -> str:
    """get status of a payment. returns 'captured', 'authorized', 'failed', etc."""
    payment = get_payment(payment_id)
    return payment.get("status", "unknown")
