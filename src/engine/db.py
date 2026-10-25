"""Postgres access: one IAM-authenticated connection per Lambda container (ADR 0021)."""

import ssl
import time
from collections.abc import Iterator
from contextlib import contextmanager

import boto3
import pg8000.native

from engine import config

_conn: pg8000.native.Connection | None = None


def connect(user: str) -> pg8000.native.Connection:
    """Open a TLS connection through the Aurora internet access gateway.

    The password is an IAM auth token: signed locally from the caller's role (`rds-db:connect`),
    valid 15 minutes for opening connections only. There is no stored password anywhere.
    """
    # Created here, not at import: tests import this module without an AWS Region.
    token = boto3.client("rds").generate_db_auth_token(config.DB_HOST, 5432, user)
    # A paused cluster (0 ACU) resumes on the first connection, ~15 s; give it a minute.
    for _ in range(5):
        try:
            return _open(user, token)
        except (pg8000.native.InterfaceError, OSError) as error:
            print(f"connect retry in 10 s: {error}")
            time.sleep(10)
    return _open(user, token)


def _open(user: str, token: str) -> pg8000.native.Connection:
    return pg8000.native.Connection(
        user,
        host=config.DB_HOST,
        database=config.DB_NAME,
        password=token,
        ssl_context=ssl.create_default_context(),
        timeout=30,
    )


def run(sql: str, **params) -> list[list]:
    """Run one statement as the app user. Values only as `:name` parameters, never formatted in.

    The connection is reused across invocations of a warm container. If it died (the cluster
    paused, an idle timeout), reconnect once and retry. ponytail: if the socket broke after the
    server ran a write, the retry runs it again, so writes must be idempotent (upsert by key).
    """
    global _conn
    if _conn is None:
        _conn = connect(config.DB_USER)
    try:
        return _conn.run(sql, **params)
    except pg8000.native.InterfaceError:
        _conn = connect(config.DB_USER)
        return _conn.run(sql, **params)


@contextmanager
def transaction() -> Iterator[pg8000.native.Connection]:
    """Run the statements of a `with` block in one transaction on the shared connection.

    Inside the block use only the yielded connection (`conn.run`), never `run()`: its retry would
    send the statement on a new connection, outside the transaction. A dead connection is
    replaced only at BEGIN, where nothing has been sent yet; inside the block nothing is retried.
    Success commits; any error rolls back and re-raises, so the caller reruns the whole unit
    (for ingest: the Lambda retry reruns the shard, and `index.upsert` skips what is stored).
    """
    global _conn
    if _conn is None:
        _conn = connect(config.DB_USER)
    try:
        _conn.run("BEGIN")
    except pg8000.native.InterfaceError:
        _conn = connect(config.DB_USER)
        _conn.run("BEGIN")
    try:
        yield _conn
        _conn.run("COMMIT")
    except BaseException:
        try:
            _conn.run("ROLLBACK")
        except pg8000.native.InterfaceError:
            _conn = None  # the socket is gone; the server rolls back an orphaned transaction
        raise
