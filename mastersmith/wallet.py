"""Spend ledger (SQLite). A build RESERVES its worst-case credits before the first paid call and SETTLES to the
actual charge afterwards. By default the balance is only a running score of what your own keys spent (it goes
negative); with MASTERSMITH_ENFORCE_CREDITS=1 a user cannot start a build the balance does not cover."""
import functools
import os
import sqlite3
import threading
import time

from . import config


class InsufficientCredits(Exception):
    def __init__(self, needed, balance):
        super().__init__("needs %d credits, balance is %d" % (needed, balance))
        self.needed, self.balance = needed, balance


def _locked(fn):
    @functools.wraps(fn)
    def inner(self, *a, **k):
        with self._lock:
            return fn(self, *a, **k)
    return inner


class Wallet:
    def __init__(self, path=None):
        self.path = str(path or config.DB_PATH)
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        # one connection shared across the service's threads, serialised by a lock (SQLite is fine with that)
        self.db = sqlite3.connect(self.path, check_same_thread=False, timeout=30)
        self._lock = threading.RLock()
        self.db.execute("CREATE TABLE IF NOT EXISTS users (name TEXT PRIMARY KEY, balance INTEGER NOT NULL DEFAULT 0)")
        self.db.execute("""CREATE TABLE IF NOT EXISTS ledger (id INTEGER PRIMARY KEY AUTOINCREMENT, user TEXT NOT NULL,
                           ts REAL NOT NULL, kind TEXT NOT NULL, credits INTEGER NOT NULL, usd_cost REAL, note TEXT,
                           settled INTEGER NOT NULL DEFAULT 1)""")
        self.db.commit()

    @_locked
    def ensure(self, user):
        self.db.execute("INSERT OR IGNORE INTO users(name, balance) VALUES (?, 0)", (user,))
        self.db.commit()

    @_locked
    def balance(self, user):
        self.ensure(user)
        return self.db.execute("SELECT balance FROM users WHERE name=?", (user,)).fetchone()[0]

    @_locked
    def add(self, user, credits, note="top-up"):
        self.ensure(user)
        self.db.execute("UPDATE users SET balance = balance + ? WHERE name=?", (credits, user))
        self.db.execute("INSERT INTO ledger(user, ts, kind, credits, usd_cost, note) VALUES (?,?,?,?,?,?)",
                        (user, time.time(), "add", credits, None, note))
        self.db.commit()
        return self.balance(user)

    @_locked
    def reserve(self, user, credits, note):
        """Hold `credits` against a job; raises when the balance cannot cover it. Returns the hold id."""
        bal = self.balance(user)
        if config.ENFORCE_CREDITS and credits > bal:
            raise InsufficientCredits(credits, bal)
        self.db.execute("UPDATE users SET balance = balance - ? WHERE name=?", (credits, user))
        cur = self.db.execute("INSERT INTO ledger(user, ts, kind, credits, usd_cost, note, settled) VALUES (?,?,?,?,?,?,0)",
                              (user, time.time(), "reserve", -credits, None, note))
        self.db.commit()
        return cur.lastrowid

    @_locked
    def settle(self, hold_id, usd_cost, note=""):
        """Turn a hold into the real charge for `usd_cost`; the unused part goes back to the user."""
        row = self.db.execute("SELECT user, credits, settled FROM ledger WHERE id=?", (hold_id,)).fetchone()
        if not row or row[2]:
            raise ValueError("hold %s unknown or already settled" % hold_id)
        user, held = row[0], -row[1]
        charge = min(config.credits_for_usd(usd_cost), held)
        refund = held - charge
        if refund:
            self.db.execute("UPDATE users SET balance = balance + ? WHERE name=?", (refund, user))
        self.db.execute("UPDATE ledger SET kind='charge', credits=?, usd_cost=?, note=?, settled=1 WHERE id=?",
                        (-charge, usd_cost, note, hold_id))
        self.db.commit()
        return {"charged": charge, "refunded": refund, "balance": self.balance(user)}

    @_locked
    def release(self, hold_id, note="released"):
        """Give a hold back untouched (the job never reached a paid call)."""
        return self.settle(hold_id, 0.0, note)

    def close(self):
        self.db.close()

    @_locked
    def history(self, user, limit=20):
        return self.db.execute("SELECT ts, kind, credits, usd_cost, note FROM ledger WHERE user=? ORDER BY id DESC LIMIT ?",
                               (user, limit)).fetchall()
