from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.customer import Customer
from app.schemas.customer import CustomerCreate


# get customer by id
def get_customer(db: Session, customer_id: UUID) -> Customer | None:
    return db.execute(select(Customer).where(Customer.id == customer_id)).scalar_one_or_none()


# get customer by razorpay id
def get_customer_by_external_id(db: Session, external_id: str) -> Customer | None:
    return db.execute(select(Customer).where(Customer.external_id == external_id)).scalar_one_or_none()


# get all customers with pagination
def get_customers(db: Session, skip: int = 0, limit: int = 100) -> list[Customer]:
    return list(db.execute(select(Customer).offset(skip).limit(limit)).scalars().all())


# create new customer
def create_customer(db: Session, data: CustomerCreate) -> Customer:
    customer = Customer(**data.model_dump())
    db.add(customer)
    db.commit()
    db.refresh(customer)  # refresh to get id and defaults
    return customer
