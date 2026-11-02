"""Single background worker, cooperative cancellation and persistent result retrieval."""

from concurrent.futures import ThreadPoolExecutor
from threading import Lock, Event
from uuid import uuid4
from core.simulation import simulate
from core.storage import Repository


class Jobs:
    def __init__(self):
        self.executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="vpp-simulation"
        )
        self.jobs = {}
        self.runs = {}
        self.repository = Repository()
        self.lock = Lock()

    def submit(self, config):
        identifier = str(uuid4())
        cancel = Event()
        job = dict(
            id=identifier,
            status="queued",
            progress=0.0,
            message="Preparing real cached inputs",
            cancel=cancel,
            run_id=None,
        )
        with self.lock:
            self.jobs[identifier] = job

        def report(fraction, message):
            with self.lock:
                job.update(progress=fraction, message=message)

        def execute():
            with self.lock:
                job["status"] = "running"
            try:
                run = simulate(config, report, cancel.is_set)
                self.repository.save(run)
                with self.lock:
                    self.runs[run.id] = run
                    # Bound in-memory run cache; older results remain on disk.
                    while len(self.runs) > 5:
                        self.runs.pop(next(iter(self.runs)))
                    job.update(
                        status="done", run_id=run.id, message=run.status, progress=1.0
                    )
            except Exception as exc:
                with self.lock:
                    job.update(status="failed", message=f"{type(exc).__name__}: {exc}")

        self.executor.submit(execute)
        return identifier

    def get(self, identifier):
        with self.lock:
            job = self.jobs.get(identifier)
            return {k: v for k, v in job.items() if k != "cancel"} if job else None

    def cancel(self, identifier):
        with self.lock:
            if identifier in self.jobs:
                self.jobs[identifier]["cancel"].set()

    def result(self, identifier):
        if identifier in self.runs:
            return self.runs[identifier]
        run = self.repository.load(identifier)
        self.runs[identifier] = run
        return run
