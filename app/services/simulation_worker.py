import asyncio
from app.services.schedule_service import run_due_schedules

_task: asyncio.Task | None = None


async def _loop() -> None:
    from app.db.mongodb import mongodb
    from app.services.simulation_service import advance_running_simulations

    while True:
        try:
            if mongodb.db is not None:
                await advance_running_simulations()
                await run_due_schedules()
        except Exception as exc:
            print(f"[simulation] worker error: {exc}")
        await asyncio.sleep(5)


def start_simulation_worker() -> None:
    global _task
    if _task is not None and not _task.done():
        return
    _task = asyncio.create_task(_loop())
    print("Simulation worker started")


async def stop_simulation_worker() -> None:
    global _task
    if _task is None:
        return
    _task.cancel()
    try:
        await _task
    except asyncio.CancelledError:
        pass
    _task = None
    print("Simulation worker stopped")