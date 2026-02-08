"""
Shared SQLAlchemy Declarative Base for Convonet models.

Some parts of the codebase (team dashboard, todo service, WebRTC transfer stack)
expect to import ``Base`` from ``convonet.models.base``. This module provides the
shared base definition so every model can inherit from the same metadata object.
"""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase, declared_attr


class Base(DeclarativeBase):
    """Central declarative base class for all Convonet SQLAlchemy models."""

    __abstract__ = True

    @declared_attr.directive
    def __tablename__(cls) -> str:  # type: ignore[misc]
        """
        Provide a sensible default table name.

        Individual models can still override ``__tablename__`` explicitly. For
        any models that omit it, this keeps naming consistent.
        """

        return cls.__name__.lower()


__all__ = ["Base"]
