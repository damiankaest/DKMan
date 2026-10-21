"""Test-only process faults, mounted solely by notes-faults.compose.yaml in disposable CI.

All engine calls and receipts are production implementations. No simulated HTTP results.
Never include this entrypoint or its controls in the production image/Compose overlay.
"""

import json
import os
from pathlib import Path

import uvicorn

from dkman.deployment_adapter.journal import Journal
from dkman.deployment_adapter.main import create_app


def main() -> None:
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("DKMAN_DISPOSABLE_DOCKER_TEST") != "1"
    ):
        raise ValueError("Disposable CI only")
    control = Path("/tmp/dkman-ci-fault.json")

    def fault(stage, operation_id):
        if control.exists():
            requested = json.loads(control.read_text())
            if requested == {"stage": stage, "operation_id": str(operation_id)}:
                control.unlink()  # One shot, even across restart of the real adapter process.
                os._exit(73)

    original_receipt = Journal.record_receipt
    original_finish = Journal.finish

    def record(self, receipt):
        fault("before_receipt", receipt.operation_id)
        return original_receipt(self, receipt)

    def finish(self, result, command, mutating):
        if result.state == "succeeded":
            fault("after_receipt", result.operation_id)
        return original_finish(self, result, command, mutating)

    Journal.record_receipt = record
    Journal.finish = finish
    uvicorn.run(create_app(), host="0.0.0.0", port=8010, access_log=False)


if __name__ == "__main__":
    main()
