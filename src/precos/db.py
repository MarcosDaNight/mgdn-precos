from __future__ import annotations

import sqlite3
import statistics
from datetime import datetime, timedelta

from .models import Offer

SCHEMA = """
CREATE TABLE IF NOT EXISTS offer (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, product_id TEXT NOT NULL, store TEXT NOT NULL, url TEXT NOT NULL,
  title TEXT, seller TEXT, available INTEGER NOT NULL, accepted INTEGER NOT NULL, reject_reason TEXT,
  price_pix REAL, price_card REAL, installments INTEGER, installment_amount REAL,
  interest_free INTEGER, free_shipping INTEGER, best_price REAL);
CREATE INDEX IF NOT EXISTS offer_product_ts ON offer(product_id, ts);
CREATE TABLE IF NOT EXISTS alert (
  id INTEGER PRIMARY KEY, ts TEXT NOT NULL, product_id TEXT NOT NULL, store TEXT NOT NULL,
  price REAL NOT NULL, reasons TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS alert_product_store ON alert(product_id, store, ts);
CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS failure (
  key TEXT PRIMARY KEY, consecutive INTEGER NOT NULL, last_error TEXT, notified INTEGER NOT NULL DEFAULT 0);
"""
# "Histórico" = ofertas aceitas pelos filtros, em estoque e com preço.
_HIST = "product_id = ? AND accepted = 1 AND available = 1 AND best_price IS NOT NULL"


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


class DB:
    def __init__(self, path: str = ":memory:"):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.executescript(SCHEMA)

    # --- ofertas -------------------------------------------------------------------------
    def insert_offer(self, o: Offer, accepted: bool, reject_reason: str | None = None) -> None:
        self.conn.execute(
            "INSERT INTO offer(ts, product_id, store, url, title, seller, available, accepted, reject_reason,"
            " price_pix, price_card, installments, installment_amount, interest_free, free_shipping, best_price)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (_iso(o.fetched_at), o.product_id, o.store, o.url, o.title, o.seller, int(o.available), int(accepted),
             reject_reason, o.price_pix, o.price_card, o.installments, o.installment_amount, int(o.interest_free),
             None if o.free_shipping is None else int(o.free_shipping), o.best_price),
        )
        self.conn.commit()

    def last_offer_for_url(self, url: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM offer WHERE url = ? ORDER BY ts DESC, id DESC LIMIT 1", (url,)
        ).fetchone()

    def history_count(self, product_id: str) -> int:
        return self.conn.execute(f"SELECT COUNT(*) FROM offer WHERE {_HIST}", (product_id,)).fetchone()[0]

    def history_min(self, product_id: str) -> float | None:
        return self.conn.execute(f"SELECT MIN(best_price) FROM offer WHERE {_HIST}", (product_id,)).fetchone()[0]

    def recent_prices(self, product_id: str, since: datetime) -> list[float]:
        rows = self.conn.execute(
            f"SELECT best_price FROM offer WHERE {_HIST} AND ts >= ?", (product_id, _iso(since))
        ).fetchall()
        return [r[0] for r in rows]

    def median_since(self, product_id: str, since: datetime, min_obs: int) -> float | None:
        prices = self.recent_prices(product_id, since)
        return statistics.median(prices) if len(prices) >= min_obs else None

    def latest_by_store(self, product_id: str, since: datetime) -> list[sqlite3.Row]:
        """Última oferta aceita e em estoque de cada loja desde `since` (para o resumo)."""
        return self.conn.execute(
            f"SELECT o.* FROM offer o JOIN (SELECT store, MAX(ts) AS ts FROM offer WHERE {_HIST} AND ts >= ?"
            " GROUP BY store) m ON o.store = m.store AND o.ts = m.ts WHERE o.product_id = ? AND o.accepted = 1"
            " AND o.available = 1 AND o.best_price IS NOT NULL ORDER BY o.best_price",
            (product_id, _iso(since), product_id),
        ).fetchall()

    # --- alertas -------------------------------------------------------------------------
    def last_alert(self, product_id: str, store: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT * FROM alert WHERE product_id = ? AND store = ? ORDER BY ts DESC, id DESC LIMIT 1",
            (product_id, store),
        ).fetchone()

    def record_alert(self, ts: datetime, product_id: str, store: str, price: float, reasons: list[str]) -> None:
        self.conn.execute(
            "INSERT INTO alert(ts, product_id, store, price, reasons) VALUES (?,?,?,?,?)",
            (_iso(ts), product_id, store, price, ",".join(reasons)),
        )
        self.conn.commit()

    # --- estado (agenda, lojas desativadas) ------------------------------------------------
    def get_state(self, key: str) -> str | None:
        row = self.conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None

    def set_state(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO state(key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
        self.conn.commit()

    def del_state(self, key: str) -> None:
        self.conn.execute("DELETE FROM state WHERE key = ?", (key,))
        self.conn.commit()

    # --- falhas consecutivas ----------------------------------------------------------------
    def record_failure(self, key: str, error: str) -> tuple[int, bool]:
        """Soma uma falha e devolve (consecutivas, já_avisado)."""
        self.conn.execute(
            "INSERT INTO failure(key, consecutive, last_error, notified) VALUES (?, 1, ?, 0)"
            " ON CONFLICT(key) DO UPDATE SET consecutive = consecutive + 1, last_error = excluded.last_error",
            (key, error[:300]),
        )
        self.conn.commit()
        row = self.conn.execute("SELECT consecutive, notified FROM failure WHERE key = ?", (key,)).fetchone()
        return row["consecutive"], bool(row["notified"])

    def mark_failure_notified(self, key: str) -> None:
        self.conn.execute("UPDATE failure SET notified = 1 WHERE key = ?", (key,))
        self.conn.commit()

    def clear_failure(self, key: str) -> None:
        self.conn.execute("DELETE FROM failure WHERE key = ?", (key,))
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


def window_start(now: datetime, days: int) -> datetime:
    return now - timedelta(days=days)
