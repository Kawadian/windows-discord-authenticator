import sys

if __name__ == '__main__':
    if '--smoke-test' in sys.argv:
        import approval_agent.desktop_ui
        import approval_agent.settings_ui
    elif '--configure' in sys.argv:
        from approval_agent.settings_ui import main
        main()
    else:
        from approval_agent.desktop_ui import main
        main()
