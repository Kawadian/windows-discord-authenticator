"""Windows Service entry point. Run as LocalSystem only."""
from __future__ import annotations

import asyncio
import threading

import servicemanager
import win32event
import win32service
import win32serviceutil

from .runner import run


class ApprovalService(win32serviceutil.ServiceFramework):
    _svc_name_ = "UacApprovalService"
    _svc_display_name_ = "UAC Approval Discord Agent"
    _svc_description_ = "Sends UAC approval requests and rotates temporary local credentials"

    def __init__(self, args):
        super().__init__(args)
        self.stop_event = threading.Event()
        self.hWaitStop = win32event.CreateEvent(None, 0, 0, None)

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self.stop_event.set()
        win32event.SetEvent(self.hWaitStop)

    def SvcDoRun(self):
        servicemanager.LogInfoMsg("UacApprovalService starting")
        try:
            asyncio.run(run(self.stop_event))
        except Exception as exc:
            servicemanager.LogErrorMsg(f"UacApprovalService stopped: {type(exc).__name__}: {exc}")
            raise


if __name__ == "__main__":
    win32serviceutil.HandleCommandLine(ApprovalService)
