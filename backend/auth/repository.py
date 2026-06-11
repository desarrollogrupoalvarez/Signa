from sqlalchemy.orm import Session, joinedload
from models.role import Role
from models.user import User


class AuthRepository:
    def __init__(self, db: Session):
        self._db = db

    def _user_q(self):
        return self._db.query(User).options(
            joinedload(User.role).joinedload(Role.permissions),
            joinedload(User.apartados),
            joinedload(User.areas),
        )

    def get_by_username(self, username: str) -> User | None:
        return self._user_q().filter(User.username == username).first()

    def get_by_id(self, user_id: int) -> User | None:
        return self._user_q().filter(User.id == user_id).first()
