import sys
import servicemanager
import win32serviceutil
from approval_agent.service import ApprovalService

if __name__ == '__main__':
    if '--smoke-test' in sys.argv:
        import approval_agent.runner
    elif '--watchdog' in sys.argv:
        from approval_agent.watchdog import main
        main()
    elif len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(ApprovalService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(ApprovalService)
