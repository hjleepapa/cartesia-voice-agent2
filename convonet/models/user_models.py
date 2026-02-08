"""
User and Team Models for Convonet
Database models for authentication and team collaboration
"""

from sqlalchemy import Column, String, DateTime, Boolean, ForeignKey, Text
from sqlalchemy.orm import relationship
from sqlalchemy.dialects.postgresql import UUID
from datetime import datetime, timezone
from enum import Enum as PyEnum
import uuid

from convonet.models.base import Base


class UserRole(PyEnum):
    ADMIN = "admin"
    MANAGER = "manager"
    MEMBER = "member"
    VIEWER = "viewer"


class TeamRole(str, PyEnum):
    """Team role enum - values stored in database as lowercase"""

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"

    @classmethod
    def _missing_(cls, value):
        """Handle case-insensitive lookup"""
        if isinstance(value, str):
            for member in cls:
                if member.name == value.upper():
                    return member
                if member.value == value.lower():
                    return member
        return None


class User(Base):
    __tablename__ = "users_anthropic"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=False)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)

    voice_pin = Column(String(10), unique=True, nullable=True, index=True)

    is_active = Column(Boolean, default=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    last_login_at = Column(DateTime(timezone=True), nullable=True)

    team_memberships = relationship("TeamMembership", back_populates="user")

    def __repr__(self):
        return f"<User(id={self.id}, email={self.email}, username={self.username})>"

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    def get_team_roles(self):
        return {membership.team_id: membership.role for membership in self.team_memberships}


class Team(Base):
    __tablename__ = "teams_anthropic"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)

    is_active = Column(Boolean, default=True, nullable=False)

    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    members = relationship("TeamMembership", back_populates="team")

    def __repr__(self):
        return f"<Team(id={self.id}, name={self.name})>"

    def get_members(self):
        return [(membership.user, membership.role) for membership in self.members]

    def get_admins(self):
        return [
            membership.user
            for membership in self.members
            if membership.role in [TeamRole.OWNER, TeamRole.ADMIN]
        ]


class TeamMembership(Base):
    __tablename__ = "team_memberships_anthropic"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    team_id = Column(UUID(as_uuid=True), ForeignKey("teams_anthropic.id"), nullable=False)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users_anthropic.id"), nullable=False)
    role = Column(String(20), default="member", nullable=False)

    joined_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    team = relationship("Team", back_populates="members")
    user = relationship("User", back_populates="team_memberships")

    def __repr__(self):
        return f"<TeamMembership(team_id={self.team_id}, user_id={self.user_id}, role={self.role})>"
