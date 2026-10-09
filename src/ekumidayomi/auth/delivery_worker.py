import argparse
import asyncio
import json
import logging
import signal
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

import httpx
import sqlalchemy as sa

from ekumidayomi.auth.email_handler import CHALLENGE_EMAIL_EVENT, AuthChallengeEmailHandler
from ekumidayomi.core.settings import get_settings
from ekumidayomi.db.session import Database
from ekumidayomi.db.uow import SqlAlchemyUnitOfWork, UnitOfWork
from ekumidayomi.email.resend import ResendEmailSender
from ekumidayomi.outbox.leased_worker import LeasedOutboxWorker
from ekumidayomi.outbox.operations import RecoveryReason, health, replay, resume


async def run(
    *,
    command: str,
    once: bool = False,
    message_id: UUID | None = None,
    reason: RecoveryReason | None = None,
) -> int:
    settings = get_settings()
    if settings.resend is None:
        raise RuntimeError("Resend settings are required; SMTP fallback is disabled")
    database = Database(settings)
    stopping = asyncio.Event()
    loop = asyncio.get_running_loop()
    previous_signals = {}
    for name in (signal.SIGINT, signal.SIGTERM):
        previous_signals[name] = signal.getsignal(name)
        signal.signal(name, lambda *_: loop.call_soon_threadsafe(stopping.set))
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    @asynccontextmanager
    async def factory() -> AsyncIterator[UnitOfWork]:
        async with asyncio.timeout(15):
            async with SqlAlchemyUnitOfWork(database.session_factory) as uow:
                await uow.session.execute(sa.text("SET LOCAL statement_timeout = '10s'"))
                await uow.session.execute(sa.text("SET LOCAL lock_timeout = '2s'"))
                yield uow

    try:
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False) as client:
            sender = ResendEmailSender(settings.resend, client)
            handlers: dict[str, AuthChallengeEmailHandler] = {
                CHALLENGE_EMAIL_EVENT: AuthChallengeEmailHandler(sender, settings.auth)
            }
            if command == "run":
                await LeasedOutboxWorker(
                    uow_factory=factory, handlers=handlers, settings=settings.outbox_worker
                ).run(once=once, stop=stopping)
                return 0
            async with factory() as uow:
                if command == "status":
                    report = await health(uow, "auth_email", tuple(handlers))
                    print(json.dumps(report))
                    return 0 if report["healthy"] else 1
                if command == "replay":
                    if message_id is None or reason is None:
                        raise ValueError("replay requires message ID and reason")
                    await replay(uow, message_id, reason, handlers)
                elif command == "resume":
                    await resume(uow, "auth_email")
                else:
                    raise ValueError("unsupported command")
                await uow.commit()
                return 0
    finally:
        for name, previous in previous_signals.items():
            signal.signal(name, previous)
        await database.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Auth email worker and privileged recovery.")
    parser.add_argument("command", choices=("run", "status", "replay", "resume"))
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--message-id", type=UUID)
    parser.add_argument("--reason", type=RecoveryReason, choices=list(RecoveryReason))
    args = parser.parse_args()
    try:
        code = asyncio.run(
            run(
                command=args.command, once=args.once, message_id=args.message_id, reason=args.reason
            )
        )
    except Exception:
        logging.getLogger(__name__).error("worker_stopped")
        code = 1
    raise SystemExit(code)


if __name__ == "__main__":
    main()
