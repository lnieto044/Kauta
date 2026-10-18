"""Conexión a la base de datos (SQLAlchemy 2.0). SQLite en demo; PostgreSQL en producción."""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .config import CONFIG

_es_sqlite = CONFIG.url_bd.startswith("sqlite")
motor_bd = create_engine(
    CONFIG.url_bd,
    connect_args={"check_same_thread": False} if _es_sqlite else {},
    pool_pre_ping=True,
    future=True,
)

if _es_sqlite:
    @event.listens_for(motor_bd, "connect")
    def _pragmas(conexion, _):  # integridad referencial y escritura concurrente segura
        cur = conexion.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA synchronous=NORMAL")
        cur.close()

SesionBD = sessionmaker(bind=motor_bd, expire_on_commit=False, autoflush=False)


class Base(DeclarativeBase):
    pass


def obtener_bd() -> Iterator[Session]:
    with SesionBD() as bd:
        yield bd
