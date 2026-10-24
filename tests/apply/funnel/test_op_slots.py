"""Batches running side by side share each kind's slots evenly (`op_slots`)."""

from __future__ import annotations

import threading
import time

from resume_tailor.apply.funnel import op_slots


def _never() -> bool:
    return False


def _until(check, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while not check():
        assert time.monotonic() < deadline
        time.sleep(0.01)


def _contend(pool: op_slots.SlotPool, owners: dict[str, int], capacity: int) -> list[threading.Thread]:
    """Start ``count`` workers per owner, each taking one slot and keeping it."""
    threads = [
        threading.Thread(target=pool.acquire, args=(owner, capacity, _never), daemon=True)
        for owner, count in owners.items()
        for _ in range(count)
    ]
    for thread in threads:
        thread.start()
    return threads


def _busy(pool: op_slots.SlotPool, owner: str, count: int, capacity: int) -> None:
    """``owner`` already fills ``count`` tabs (a batch that started alone)."""
    for _ in range(count):
        assert pool.acquire(owner, capacity, _never)


def test_a_batch_started_later_gets_freed_slots_until_both_hold_half():
    pool = op_slots.SlotPool()
    _busy(pool, "a", 4, capacity=4)
    _contend(pool, {"b": 4, "a": 4}, capacity=4)  # both still have work queued
    time.sleep(0.05)
    assert (pool.held("a"), pool.held("b")) == (4, 0)  # a running fill is never cut
    for expected in ((3, 1), (2, 2), (2, 2)):
        pool.release("a")  # one of a's fills finishes
        _until(lambda: pool.held("a") + pool.held("b") == 4)
        assert (pool.held("a"), pool.held("b")) == expected


def test_a_batch_with_little_work_leaves_its_share_to_the_other():
    pool = op_slots.SlotPool()
    _busy(pool, "a", 4, capacity=4)
    _contend(pool, {"b": 1, "a": 4}, capacity=4)
    time.sleep(0.05)
    for _ in range(2):
        pool.release("a")
        _until(lambda: pool.held("a") + pool.held("b") == 4)
    assert (pool.held("a"), pool.held("b")) == (3, 1)


def test_a_freed_slot_goes_to_the_batch_holding_fewest():
    pool = op_slots.SlotPool()
    assert pool.acquire("a", 2, _never) and pool.acquire("a", 2, _never)
    _contend(pool, {"a": 1, "b": 1}, capacity=2)
    time.sleep(0.05)
    pool.release("a")
    _until(lambda: pool.held("b") == 1)
    assert pool.held("a") == 1


def test_one_slot_alternates_between_batches():
    pool = op_slots.SlotPool()
    order: list[str] = []
    lock = threading.Lock()

    def worker(owner: str) -> None:
        for _ in range(3):
            assert pool.acquire(owner, 1, _never)
            with lock:
                order.append(owner)
            time.sleep(0.02)
            pool.release(owner)

    threads = [threading.Thread(target=worker, args=(owner,)) for owner in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
    assert sorted(order) == ["a", "a", "a", "b", "b", "b"]
    # Never three in a row: a release with the other batch waiting hands the slot over.
    assert all(order[i : i + 3] not in (["a"] * 3, ["b"] * 3) for i in range(len(order) - 2))


def test_stop_ends_the_wait_without_a_slot():
    pool = op_slots.SlotPool()
    assert pool.acquire("a", 1, _never)
    stop = threading.Event()
    got: list[bool] = []
    waiter = threading.Thread(target=lambda: got.append(pool.acquire("b", 1, stop.is_set)))
    waiter.start()
    time.sleep(0.05)
    stop.set()
    waiter.join(3)
    assert got == [False]
    assert pool.held("b") == 0
    pool.release("a")
    assert pool.acquire("c", 1, _never)  # the stopped waiter left nothing behind
