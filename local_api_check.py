#!/usr/bin/env python3
"""Loopback-only SwitcheOn account/API diagnostic; never persists credentials."""

from __future__ import annotations

import html
import json
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

API = "https://www.switcheon.com/api"


def page(body: str, title: str = "SwitcheOn API check") -> bytes:
    return f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>
<style>body{{font:16px system-ui;max-width:720px;margin:3rem auto;padding:0 1rem;color:#222}}
label{{display:block;margin:1rem 0 .35rem}}input{{box-sizing:border-box;width:100%;padding:.7rem;font:inherit}}
button{{margin-top:1rem;padding:.7rem 1rem;font:inherit}}li{{margin:.5rem 0}}code{{overflow-wrap:anywhere}}</style>
<h1>{title}</h1>{body}</html>""".encode()


class Handler(BaseHTTPRequestHandler):
    """Serve one form and make API requests only on explicit local submission."""

    def log_message(self, fmt, *args):
        # Avoid logging request details or anything that might contain secrets.
        return

    def send_page(self, body: str, status: int = 200, title: str = "SwitcheOn API check"):
        data = page(body, title)
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        self.send_page("""<p>This tool sends credentials directly from your Mac to SwitcheOn over HTTPS.
They are not saved or displayed. Results omit the password and token.</p>
<form method="post" action="/check" autocomplete="off">
<label for="email">SwitcheOn email</label><input id="email" name="email" type="email" required autocomplete="username">
<label for="password">SwitcheOn password</label><input id="password" name="password" type="password" required autocomplete="current-password">
<button type="submit">Test login and account lookup</button></form>""")

    def do_POST(self):
        if self.path != "/check":
            self.send_error(404)
            return
        origin = self.headers.get("Origin", "")
        allowed_origins = {
            f"http://127.0.0.1:{self.server.server_port}",
            f"http://localhost:{self.server.server_port}",
        }
        if origin not in allowed_origins:
            self.send_error(403)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 8192:
                raise ValueError("form too large")
            fields = urllib.parse.parse_qs(self.rfile.read(length).decode(), strict_parsing=True)
            email = fields.get("email", [""])[0].strip()
            password = fields.get("password", [""])[0]
            if not email or not password:
                raise ValueError("email and password are required")
            result, trace = check_account(email, password)
        except ValueError as err:
            self.send_page(f"<p>Could not run the check: {html.escape(str(err))}</p><p><a href='/'>Return</a></p>", 400)
            return
        except Exception:
            self.send_page("<p>The API request failed. Check your connection and try again.</p><p><a href='/'>Return</a></p>", 502)
            return
        finally:
            # Drop local references as soon as the request completes.
            if "password" in locals():
                password = ""
        self.send_page(render_result(result, trace))


def redact(value):
    """Redact authentication material recursively before rendering a trace."""
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if key.casefold() in {
                "token", "usersecret", "password", "userpassword", "authorization"
            } else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def request_json(url: str, *, data: bytes | None = None, trace: list | None = None) -> dict:
    req = urllib.request.Request(url, data=data)
    req.add_header("Accept", "application/json")
    if data is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    safe_url = re.sub(r"([?&]UserSecret=)[^&]*", r"\1[REDACTED]", url)
    request_body = None
    if data is not None:
        form = urllib.parse.parse_qs(data.decode(), keep_blank_values=True)
        request_body = urllib.parse.urlencode({
            key: "[REDACTED]" if key.casefold() in {"userpassword", "usersecret", "password"} else values[0]
            for key, values in form.items()
        })
    record = {
        "request": {
            "method": req.get_method(), "url": safe_url,
            "headers": dict(req.header_items()), "body": request_body,
        }
    }
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            raw = response.read().decode()
            record["response"] = {
                "status": response.status,
                "headers": dict(response.headers.items()),
                "body": redact(json.loads(raw)),
            }
    except urllib.error.HTTPError as err:
        raw = err.read().decode(errors="replace")
        try:
            response_body = redact(json.loads(raw))
        except ValueError:
            response_body = raw
        record["response"] = {
            "status": err.code, "headers": dict(err.headers.items()), "body": response_body,
        }
        if trace is not None:
            trace.append(record)
        raise RuntimeError(f"SwitcheOn returned HTTP {err.code}") from None
    if trace is not None:
        trace.append(record)
    return json.loads(raw)


def check_account(email: str, password: str) -> tuple[dict, list]:
    trace = []
    form = urllib.parse.urlencode({"Email": email, "UserPassword": password}).encode()
    login = request_json(f"{API}/User", data=form, trace=trace)
    user_id, token = login["userIdBin"], login["token"]
    query = urllib.parse.urlencode({"UserIdBin": user_id, "UserSecret": token})
    account = request_json(f"{API}/User?{query}", trace=trace)
    # Keep only non-secret fields required for troubleshooting.
    boxes = [{
        "box_id": box.get("boxIdText"),
        "location": box.get("location"),
        "device_type": box.get("deviceType"),
        "channels": box.get("channels"),
    } for box in account.get("boxes", [])]
    return {
        "email": account.get("email"),
        "firstname": account.get("firstname"),
        "lastname": account.get("lastname"),
        "user_id": user_id,
        "boxes": boxes,
    }, trace


def render_result(result: dict, trace: list) -> str:
    safe = lambda value: html.escape(str(value)) if value is not None else "(not returned)"
    rows = "".join(
        "<li><b>" + safe(box.get("location")) + "</b>: box ID <code>" + safe(box.get("box_id"))
        + "</code>; type " + safe(box.get("device_type")) + "; channels " + safe(box.get("channels")) + "</li>"
        for box in result["boxes"]
    ) or "<li>No boxes were returned.</li>"
    return ("<h2>API response</h2><ul><li>Account email: " + safe(result.get("email"))
        + "</li><li>Name: " + safe((result.get("firstname") or "") + " " + (result.get("lastname") or ""))
        + "</li><li>User ID: <code>" + safe(result.get("user_id")) + "</code></li>"
        + "<li>Boxes returned: " + str(len(result["boxes"])) + "</li></ul><h3>Boxes</h3><ul>" + rows
        + "</ul><h2>Request and response trace</h2><p>Passwords and tokens are redacted.</p>"
        + "<pre>" + html.escape(json.dumps(trace, indent=2, ensure_ascii=False)) + "</pre>"
        + "<p><a href='/'>Run another check</a></p>")


def main():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.daemon_threads = True
    url = f"http://127.0.0.1:{server.server_port}/"
    print(f"Open {url} in your browser. Press Ctrl+C here to stop.")
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        import webbrowser
        webbrowser.open(url)
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
