# Project Map (auto-generated)

- Generated: 2025-08-30 10:08:53 UTC
- Branch: local

## Structure (depth=4)

```text
.
├── ...43534.py
├── .DS_Store
├── .env
├── .gitignore
├── README.md
├── REVERT-commit-3249799e1d55ab6707d5298fa360d53a7231fc8d.txt
├── app
│   ├── .DS_Store
│   ├── __init__.py
│   ├── __pycache__
│   │   ├── __init__.cpython-310.pyc
│   │   ├── config.cpython-310.pyc
│   │   ├── logging_json.cpython-310.pyc
│   │   └── telethon_client.cpython-310.pyc
│   ├── config.py
│   ├── flows
│   │   └── batch_links
│   │       ├── __init__.py
│   │       ├── common.py
│   │       ├── process_links.py
│   │       └── queue_worker.py
│   ├── logging_json.py
│   ├── plugins
│   │   ├── .DS_Store
│   │   ├── __init__.py
│   │   ├── __pycache__
│   │   │   ├── __init__.cpython-310.pyc
│   │   │   ├── batch_links.cpython-310.pyc
│   │   │   ├── help_and_ping.cpython-310.pyc
│   │   │   ├── metrics_watch.cpython-310.pyc
│   │   │   ├── needle_reply.cpython-310.pyc
│   │   │   ├── post_templates.cpython-310.pyc
│   │   │   └── progress_live.cpython-310.pyc
│   │   ├── batch_links.py
│   │   ├── batch_links.py.zip
│   │   ├── help_and_ping.py
│   │   ├── metrics_watch.py
│   │   ├── needle_reply.py
│   │   ├── post_templates.py
│   │   └── progress_live.py
│   ├── services
│   │   ├── __init__.py
│   │   ├── __pycache__
│   │   │   ├── __init__.cpython-310.pyc
│   │   │   ├── account_pool.cpython-310.pyc
│   │   │   ├── boot_gate.cpython-310.pyc
│   │   │   ├── gsheets.cpython-310.pyc
│   │   │   ├── joiner.cpython-310.pyc
│   │   │   ├── link_queue.cpython-310.pyc
│   │   │   ├── membership_db.cpython-310.pyc
│   │   │   ├── post_match.cpython-310.pyc
│   │   │   ├── post_watch_db.cpython-310.pyc
│   │   │   └── subscription_check.cpython-310.pyc
│   │   ├── account_pool.py
│   │   ├── db
│   │   │   └── bad_invites.py
│   │   ├── gsheets.py
│   │   ├── joiner.py
│   │   ├── link_queue.py
│   │   ├── membership_db.py
│   │   ├── post_match.py
│   │   ├── post_watch_db.py
│   │   └── subscription_check.py
│   ├── telethon_client.py
│   └── utils
│       ├── __init__.py
│       ├── __pycache__
│       │   ├── __init__.cpython-310.pyc
│       │   ├── formatting.cpython-310.pyc
│       │   ├── link_parser.cpython-310.pyc
│       │   ├── logx.cpython-310.pyc
│       │   ├── notices.cpython-310.pyc
│       │   ├── queue_cleanup.cpython-310.pyc
│       │   ├── text_norm.cpython-310.pyc
│       │   ├── tg_links.cpython-310.pyc
│       │   └── throttle.cpython-310.pyc
│       ├── formatting.py
│       ├── link_parser.py
│       ├── notices.py
│       ├── text_norm.py
│       ├── tg_links.py
│       └── throttle.py
├── data
│   └── post_templates_meta.json
├── docs
│   ├── ARCHITECTURE.md
│   └── PROJECT_MAP.md
├── fix-process_links.patch
├── main.py
├── post_watchdog.sqlite3
├── post_watchdog.sqlite3-shm
├── post_watchdog.sqlite3-wal
├── requirements.txt
├── scripts
│   └── generate-project-map.sh
├── service_account.json
├── tg_forward_patch.diff
├── tg_session.session
├── tg_session_2.session
├── tg_session_3.session
└── venv
    ├── .gitignore
    ├── bin
    │   ├── activate
    │   ├── activate.csh
    │   ├── activate.fish
    │   ├── activate.nu
    │   ├── activate.ps1
    │   ├── activate_this.py
    │   ├── aider
    │   ├── deactivate.nu
    │   ├── distro
    │   ├── dotenv
    │   ├── f2py
    │   ├── flake8
    │   ├── gast
    │   ├── google-oauthlib-tool
    │   ├── grep-ast
    │   ├── hf
    │   ├── httpx
    │   ├── huggingface-cli
    │   ├── jsonschema
    │   ├── litellm
    │   ├── litellm-proxy
    │   ├── markdown-it
    │   ├── mslex-split
    │   ├── normalizer
    │   ├── openai
    │   ├── pip
    │   ├── pip-3.10
    │   ├── pip3
    │   ├── pip3.10
    │   ├── pycodestyle
    │   ├── pyflakes
    │   ├── pygmentize
    │   ├── pyjson5
    │   ├── pyrsa-decrypt
    │   ├── pyrsa-encrypt
    │   ├── pyrsa-keygen
    │   ├── pyrsa-priv2pub
    │   ├── pyrsa-sign
    │   ├── pyrsa-verify
    │   ├── python -> /usr/local/bin/python3
    │   ├── python3 -> python
    │   ├── python3.10 -> python
    │   ├── shtab
    │   ├── tiny-agents
    │   ├── tqdm
    │   ├── watchfiles
    │   ├── wheel
    │   ├── wheel-3.10
    │   ├── wheel3
    │   └── wheel3.10
    └── pyvenv.cfg

17 directories, 138 files
```

## Symbols index (functions/classes)

```text
```

## Notes

- This file is generated. Do not edit manually.
- Adjust MAX_DEPTH or excludes in scripts/generate-project-map.sh as needed.
