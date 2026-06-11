from sqlalchemy.orm import Session

from models.permission import Permission
from models.role import Role
from models.user import User


class UsersRepository:
    def __init__(self, db: Session):
        self._db = db

    def list_all(self) -> list[User]:
        return self._db.query(User).order_by(User.username).all()

    def get_by_id(self, user_id: int) -> User | None:
        return self._db.query(User).filter(User.id == user_id).first()

    def get_by_username(self, username: str) -> User | None:
        return self._db.query(User).filter(User.username == username).first()

    def get_role_by_name(self, name: str) -> Role | None:
        return self._db.query(Role).filter(Role.name == name).first()

    def get_role_by_id(self, role_id: int) -> Role | None:
        return self._db.query(Role).filter(Role.id == role_id).first()

    def list_roles(self) -> list[Role]:
        return self._db.query(Role).order_by(Role.name).all()

    def list_permissions(self) -> list[Permission]:
        return self._db.query(Permission).order_by(Permission.resource, Permission.action, Permission.name).all()

    def get_permission_by_name(self, name: str) -> Permission | None:
        return self._db.query(Permission).filter(Permission.name == name).first()

    def create_role(self, name: str, description: str) -> Role:
        role = Role(name=name, description=description)
        self._db.add(role)
        self._db.flush()
        self._db.refresh(role)
        return role

    def update_role(self, role: Role, **fields) -> Role:
        for key, value in fields.items():
            setattr(role, key, value)
        self._db.flush()
        self._db.refresh(role)
        return role

    def delete_role(self, role: Role) -> None:
        self._db.delete(role)
        self._db.flush()

    def create(self, username: str, password_hash: str, role_id: int) -> User:
        user = User(username=username, password_hash=password_hash, role_id=role_id)
        self._db.add(user)
        self._db.flush()
        self._db.refresh(user)
        return user

    def update(self, user: User, **fields) -> User:
        for key, value in fields.items():
            setattr(user, key, value)
        self._db.flush()
        self._db.refresh(user)
        return user

    def delete(self, user: User) -> None:
        self._db.delete(user)
        self._db.flush()
