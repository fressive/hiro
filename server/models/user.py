"""User ORM model."""

from sqlalchemy import Column, Integer, String

from server.db import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(150), unique=True, index=True, nullable=False)
    email = Column(String(255), nullable=True)
    hashed_password = Column(String(255), nullable=False)
