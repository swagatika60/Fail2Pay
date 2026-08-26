from fastapi import APIRouter, HTTPException

from app.schemas.payment import (
    CreateOrderRequest,
    CreateOrderResponse,
    PaymentResponse,
    VerifyPaymentRequest,
    VerifyPaymentResponse,
)
from app.services.razorpay import (
    create_order,
    get_payment,
    verify_payment_signature,
)

router = APIRouter(prefix="/api/payments", tags=["payments"])


# create a new razorpay order
@router.post("/orders", response_model=CreateOrderResponse)
def create_payment_order(request: CreateOrderRequest) -> CreateOrderResponse:
    try:
        order = create_order(
            amount=request.amount,
            currency=request.currency,
            receipt=request.receipt,
        )
        return CreateOrderResponse(
            order_id=order["id"],
            amount=order["amount"],
            currency=order["currency"],
            receipt=order.get("receipt", ""),
            status=order.get("status", "created"),
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


# get payment details by id
@router.get("/{payment_id}", response_model=PaymentResponse)
def get_payment_details(payment_id: str) -> PaymentResponse:
    try:
        payment = get_payment(payment_id)
        return PaymentResponse(
            payment_id=payment["id"],
            order_id=payment.get("order_id"),
            amount=payment["amount"],
            currency=payment.get("currency", "INR"),
            status=payment.get("status", "unknown"),
            method=payment.get("method"),
            description=payment.get("description"),
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))


# verify payment signature
@router.post("/verify", response_model=VerifyPaymentResponse)
def verify_payment(request: VerifyPaymentRequest) -> VerifyPaymentResponse:
    is_valid = verify_payment_signature(
        razorpay_order_id=request.razorpay_order_id,
        razorpay_payment_id=request.razorpay_payment_id,
        razorpay_signature=request.razorpay_signature,
    )
    if is_valid:
        return VerifyPaymentResponse(verified=True, message="Payment verified successfully")
    else:
        return VerifyPaymentResponse(verified=False, message="Invalid payment signature")
