from pydantic import BaseModel


# request to create an order
class CreateOrderRequest(BaseModel):
    amount: int  # in paise
    currency: str = "INR"
    receipt: str  # unique id for this order


# response when order is created
class CreateOrderResponse(BaseModel):
    order_id: str
    amount: int
    currency: str
    receipt: str
    status: str


# response for payment details
class PaymentResponse(BaseModel):
    payment_id: str
    order_id: str | None
    amount: int
    currency: str
    status: str
    method: str | None
    description: str | None


# request to verify payment
class VerifyPaymentRequest(BaseModel):
    razorpay_order_id: str
    razorpay_payment_id: str
    razorpay_signature: str


# response for verification
class VerifyPaymentResponse(BaseModel):
    verified: bool
    message: str
