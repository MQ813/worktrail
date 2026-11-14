import multiprocessing

if __name__ == "__main__":
    multiprocessing.freeze_support()
    from mail_jira_assistant.desktop import run

    run()
