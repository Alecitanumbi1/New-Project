#!/usr/bin/env python3
"""Reconciliador multiusuario de cuentas bancarias y contables.

Permite:
- Gestionar tenants (empresas) y usuarios.
- Crear cuentas de tipo banco o contable.
- Registrar movimientos.
- Sugerir conciliaciones entre dos cuentas.
- Confirmar conciliaciones.
"""

from __future__ import annotations

import argparse
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable


@dataclass
class Suggestion:
    tx_a_id: int
    tx_b_id: int
    amount_a: float
    amount_b: float
    date_a: str
    date_b: str
    days_apart: int


class ReconciliadorDB:
    def __init__(self, db_path: str = "reconciliador.db") -> None:
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_db(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                PRAGMA foreign_keys = ON;

                CREATE TABLE IF NOT EXISTS tenants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT NOT NULL UNIQUE,
                    full_name TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tenant_users (
                    tenant_id INTEGER NOT NULL,
                    user_id INTEGER NOT NULL,
                    role TEXT NOT NULL DEFAULT 'member',
                    PRIMARY KEY (tenant_id, user_id),
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
                    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS accounts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    account_type TEXT NOT NULL CHECK(account_type IN ('bank','ledger')),
                    currency TEXT NOT NULL DEFAULT 'USD',
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id INTEGER NOT NULL,
                    account_id INTEGER NOT NULL,
                    txn_date TEXT NOT NULL,
                    amount REAL NOT NULL,
                    reference TEXT,
                    description TEXT,
                    created_by INTEGER,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
                    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
                    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
                );

                CREATE TABLE IF NOT EXISTS reconciliations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id INTEGER NOT NULL,
                    tx_a_id INTEGER NOT NULL,
                    tx_b_id INTEGER NOT NULL,
                    note TEXT,
                    created_by INTEGER,
                    created_at TEXT NOT NULL,
                    UNIQUE(tx_a_id, tx_b_id),
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
                    FOREIGN KEY (tx_a_id) REFERENCES transactions(id) ON DELETE CASCADE,
                    FOREIGN KEY (tx_b_id) REFERENCES transactions(id) ON DELETE CASCADE,
                    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
                );
                """
            )

    def add_tenant(self, name: str) -> int:
        now = datetime.utcnow().isoformat()
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO tenants(name, created_at) VALUES (?, ?)",
                (name, now),
            )
            return int(cur.lastrowid)

    def add_user(self, email: str, full_name: str) -> int:
        now = datetime.utcnow().isoformat()
        with self.connect() as conn:
            cur = conn.execute(
                "INSERT INTO users(email, full_name, created_at) VALUES (?, ?, ?)",
                (email, full_name, now),
            )
            return int(cur.lastrowid)

    def assign_user(self, tenant_id: int, user_id: int, role: str = "member") -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO tenant_users(tenant_id, user_id, role) VALUES (?, ?, ?)",
                (tenant_id, user_id, role),
            )

    def add_account(self, tenant_id: int, name: str, account_type: str, currency: str = "USD") -> int:
        now = datetime.utcnow().isoformat()
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO accounts(tenant_id, name, account_type, currency, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (tenant_id, name, account_type, currency, now),
            )
            return int(cur.lastrowid)

    def add_transaction(
        self,
        tenant_id: int,
        account_id: int,
        txn_date: str,
        amount: float,
        reference: str | None,
        description: str | None,
        created_by: int | None,
    ) -> int:
        now = datetime.utcnow().isoformat()
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO transactions
                (tenant_id, account_id, txn_date, amount, reference, description, created_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (tenant_id, account_id, txn_date, amount, reference, description, created_by, now),
            )
            return int(cur.lastrowid)

    def unreconciled_transactions(self, tenant_id: int, account_id: int) -> list[sqlite3.Row]:
        with self.connect() as conn:
            return conn.execute(
                """
                SELECT t.*
                FROM transactions t
                WHERE t.tenant_id = ?
                  AND t.account_id = ?
                  AND t.id NOT IN (
                      SELECT tx_a_id FROM reconciliations
                      UNION
                      SELECT tx_b_id FROM reconciliations
                  )
                ORDER BY t.txn_date, t.id
                """,
                (tenant_id, account_id),
            ).fetchall()

    def suggest_matches(
        self,
        tenant_id: int,
        account_a: int,
        account_b: int,
        max_days: int = 3,
        tolerance: float = 0.01,
    ) -> list[Suggestion]:
        a_rows = self.unreconciled_transactions(tenant_id, account_a)
        b_rows = self.unreconciled_transactions(tenant_id, account_b)
        suggestions: list[Suggestion] = []

        for a in a_rows:
            date_a = datetime.fromisoformat(a["txn_date"]).date()
            for b in b_rows:
                date_b = datetime.fromisoformat(b["txn_date"]).date()
                days_apart = abs((date_a - date_b).days)
                if days_apart > max_days:
                    continue

                # Regla base: montos opuestos (banco vs libro) o iguales (cuenta vs cuenta)
                opposite = abs(a["amount"] + b["amount"]) <= tolerance
                equal = abs(a["amount"] - b["amount"]) <= tolerance
                if opposite or equal:
                    suggestions.append(
                        Suggestion(
                            tx_a_id=int(a["id"]),
                            tx_b_id=int(b["id"]),
                            amount_a=float(a["amount"]),
                            amount_b=float(b["amount"]),
                            date_a=a["txn_date"],
                            date_b=b["txn_date"],
                            days_apart=days_apart,
                        )
                    )

        suggestions.sort(key=lambda s: (s.days_apart, abs(abs(s.amount_a) - abs(s.amount_b))))
        return suggestions

    def confirm_match(self, tenant_id: int, tx_a_id: int, tx_b_id: int, note: str | None, created_by: int | None) -> int:
        now = datetime.utcnow().isoformat()
        with self.connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO reconciliations(tenant_id, tx_a_id, tx_b_id, note, created_by, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (tenant_id, tx_a_id, tx_b_id, note, created_by, now),
            )
            return int(cur.lastrowid)


def print_table(rows: Iterable[sqlite3.Row]) -> None:
    rows = list(rows)
    if not rows:
        print("(sin resultados)")
        return
    columns = rows[0].keys()
    print(" | ".join(columns))
    print("-" * 80)
    for row in rows:
        print(" | ".join(str(row[col]) for col in columns))


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Conciliador de cuentas multiusuario")
    p.add_argument("--db", default="reconciliador.db", help="Ruta al archivo sqlite")
    sp = p.add_subparsers(dest="command", required=True)

    sp.add_parser("init-db")

    t = sp.add_parser("add-tenant")
    t.add_argument("name")

    u = sp.add_parser("add-user")
    u.add_argument("email")
    u.add_argument("full_name")

    au = sp.add_parser("assign-user")
    au.add_argument("tenant_id", type=int)
    au.add_argument("user_id", type=int)
    au.add_argument("--role", default="member")

    a = sp.add_parser("add-account")
    a.add_argument("tenant_id", type=int)
    a.add_argument("name")
    a.add_argument("account_type", choices=["bank", "ledger"])
    a.add_argument("--currency", default="USD")

    m = sp.add_parser("add-txn")
    m.add_argument("tenant_id", type=int)
    m.add_argument("account_id", type=int)
    m.add_argument("txn_date", help="YYYY-MM-DD")
    m.add_argument("amount", type=float)
    m.add_argument("--reference")
    m.add_argument("--description")
    m.add_argument("--created-by", type=int)

    s = sp.add_parser("suggest")
    s.add_argument("tenant_id", type=int)
    s.add_argument("account_a", type=int)
    s.add_argument("account_b", type=int)
    s.add_argument("--days", type=int, default=3)
    s.add_argument("--tolerance", type=float, default=0.01)

    c = sp.add_parser("confirm")
    c.add_argument("tenant_id", type=int)
    c.add_argument("tx_a_id", type=int)
    c.add_argument("tx_b_id", type=int)
    c.add_argument("--note")
    c.add_argument("--created-by", type=int)

    l = sp.add_parser("list-unreconciled")
    l.add_argument("tenant_id", type=int)
    l.add_argument("account_id", type=int)

    return p


def validate_date(date_str: str) -> None:
    try:
        datetime.fromisoformat(date_str)
    except ValueError as exc:
        raise SystemExit(f"Fecha inválida '{date_str}'. Usa YYYY-MM-DD") from exc


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    db = ReconciliadorDB(args.db)

    if args.command == "init-db":
        db.init_db()
        print(f"Base creada: {Path(args.db).resolve()}")

    elif args.command == "add-tenant":
        tenant_id = db.add_tenant(args.name)
        print(f"tenant_id={tenant_id}")

    elif args.command == "add-user":
        user_id = db.add_user(args.email, args.full_name)
        print(f"user_id={user_id}")

    elif args.command == "assign-user":
        db.assign_user(args.tenant_id, args.user_id, args.role)
        print("ok")

    elif args.command == "add-account":
        account_id = db.add_account(args.tenant_id, args.name, args.account_type, args.currency)
        print(f"account_id={account_id}")

    elif args.command == "add-txn":
        validate_date(args.txn_date)
        tx_id = db.add_transaction(
            args.tenant_id,
            args.account_id,
            args.txn_date,
            args.amount,
            args.reference,
            args.description,
            args.created_by,
        )
        print(f"tx_id={tx_id}")

    elif args.command == "suggest":
        suggestions = db.suggest_matches(
            args.tenant_id,
            args.account_a,
            args.account_b,
            args.days,
            args.tolerance,
        )
        if not suggestions:
            print("No hay sugerencias")
            return
        for s in suggestions:
            print(
                f"tx_a={s.tx_a_id} ({s.amount_a}, {s.date_a}) <-> "
                f"tx_b={s.tx_b_id} ({s.amount_b}, {s.date_b}) | diff_dias={s.days_apart}"
            )

    elif args.command == "confirm":
        rec_id = db.confirm_match(args.tenant_id, args.tx_a_id, args.tx_b_id, args.note, args.created_by)
        print(f"reconciliation_id={rec_id}")

    elif args.command == "list-unreconciled":
        rows = db.unreconciled_transactions(args.tenant_id, args.account_id)
        print_table(rows)


if __name__ == "__main__":
    main()
