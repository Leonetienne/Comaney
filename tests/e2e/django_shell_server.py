"""Long-lived Django process for the e2e helpers (see django_shell.py).

Runs inside the web container, started from the app root via `python -c`.
Reads one JSON request per line on stdin, answers one JSON line on stdout:
  {"argv": ["create_user", "a@b.c", "-p", "x"]}  a management command, CLI argv semantics
  {"code": "print(1)"}                          a snippet in a fresh namespace
  -> {"returncode": 0, "stdout": "...", "stderr": "..."}
"""
import builtins
import contextlib
import io
import json
import os
import sys
import traceback

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "comaney.settings")

# Keep the protocol on private fds, so a command touching fd 0/1 cannot corrupt it.
_requests = os.fdopen(os.dup(0), "r", encoding="utf-8")
_replies = os.fdopen(os.dup(1), "w", encoding="utf-8")
_devnull = os.open(os.devnull, os.O_RDONLY)
os.dup2(_devnull, 0)
os.dup2(2, 1)

import django  # noqa: E402

django.setup()

from django.core.management import call_command  # noqa: E402
from django.core.management.base import CommandError  # noqa: E402
from django.core.management.commands import shell as shell_command  # noqa: E402
from django.db import close_old_connections  # noqa: E402


def _exec(code: str, namespace: dict) -> None:
    exec(compile(code, "<e2e>", "exec"), namespace)


def _run_argv(argv: list) -> None:
    if argv[:1] == ["shell"]:
        # manage.py shell -c execs in the shell module's globals; a copy keeps calls apart
        options = shell_command.Command().create_parser("manage.py", "shell").parse_args(argv[1:])
        if not options.command:
            raise CommandError("only shell -c is supported")
        _exec(options.command, dict(vars(shell_command)))
    else:
        call_command(*argv)


def _handle(request: dict) -> dict:
    out, err = io.StringIO(), io.StringIO()
    returncode = 0
    close_old_connections()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        sys.stdin = io.StringIO("")
        try:
            if "argv" in request:
                _run_argv([str(a) for a in request["argv"]])
            else:
                _exec(request["code"], {"__name__": "__main__", "__builtins__": builtins})
        except CommandError as exc:
            err.write(f"CommandError: {exc}\n")
            returncode = exc.returncode
        except SystemExit as exc:
            code = exc.code
            if code is not None and not isinstance(code, int):
                err.write(f"{code}\n")
                code = 1
            returncode = code or 0
        except BaseException:
            traceback.print_exc(file=err)
            returncode = 1
        finally:
            close_old_connections()
    return {"returncode": returncode, "stdout": out.getvalue(), "stderr": err.getvalue()}


def main() -> None:
    _replies.write(json.dumps({"ready": True}) + "\n")
    _replies.flush()
    for line in _requests:
        if not line.strip():
            continue
        _replies.write(json.dumps(_handle(json.loads(line))) + "\n")
        _replies.flush()


main()
