"""The one local site for every job (owner, 2026-09-29: "all previews always on same port with just pages with links
that are easier to navigate"). One server on config.PREVIEW_PORT serves out/: the home page lists every build and every
job with links, /results the builds with their six views and scores, /refs the reference pictures to approve, and
each job's delivery/preview.html. The pages are rendered when they are opened, so they are always current; every page
carries the same nav bar. `ms serve`, `ms preview`, `ms refs` and `ms results` start the server when it is not running
and restart it when its code is older than this file (or the pages it renders).

Run as `python -m mastersmith.site <out_dir> <port>`."""
import html
import json
import os
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from functools import partial
from http.server import ThreadingHTTPServer

from . import refs_review, results_page

NAV_CSS = """.ms-nav{position:sticky;top:0;z-index:20;display:flex;flex-wrap:wrap;gap:4px 18px;align-items:center;
 padding:9px 16px;background:#1d2733;color:#e8edf2;font:500 14px "Segoe UI",system-ui,sans-serif}
.ms-nav b{font-weight:700;letter-spacing:.3px;margin-right:6px}.ms-nav a{color:#bcd3ec;text-decoration:none;padding:2px 0}
.ms-nav a:hover{color:#fff;text-decoration:underline}.ms-nav a.on{color:#fff;border-bottom:2px solid #7fa8d6}
.ms-nav .ms-crumb{color:#8fa2b5;margin-left:auto;font-size:13px}"""


def nav(active="", crumb=""):
    """The bar at the top of every page: Home, Builds, References, and where you are."""
    links = (("/", "Home", "home"), ("/results", "Builds", "results"), ("/refs", "References", "refs"))
    a = "".join('<a href="%s"%s>%s</a>' % (h, ' class="on"' if k == active else "", t) for h, t, k in links)
    return '<style>%s</style><nav class="ms-nav"><b>Master Smith</b>%s%s</nav>' % (
        NAV_CSS, a, ('<span class="ms-crumb">%s</span>' % crumb) if crumb else "")


def code_stamp():
    """When the site's code last changed: a running server older than this is restarted."""
    here = os.path.dirname(os.path.abspath(__file__))
    return max(int(os.path.getmtime(os.path.join(here, f))) for f in ("site.py", "refs_review.py", "results_page.py"))


LOADED = code_stamp()          # the code this process runs; ping reports it, so a stale server is restarted


def _jobs_by_recent(out_dir, delivered):
    jobs = results_page.delivered_jobs(out_dir) if delivered else refs_review.all_jobs(out_dir)
    stamp = lambda j: os.path.getmtime(os.path.join(out_dir, j, "delivery", "report.json")) if delivered else \
        os.path.getmtime(os.path.join(out_dir, j, "brief.json"))
    return sorted(jobs, key=stamp, reverse=True)


def home_page(out_dir):
    """Every build, newest first, with its score and links; then the jobs that have pictures but no build yet."""
    e = html.escape
    rows = []
    for job in _jobs_by_recent(out_dir, True):
        d = os.path.join(out_dir, job, "delivery")
        sc_path = os.path.join(d, "scorecard.json")
        sc = json.load(open(sc_path, encoding="utf-8")) if os.path.exists(sc_path) else {}
        brief = json.load(open(os.path.join(out_dir, job, "brief.json"), encoding="utf-8"))
        score, who = results_page.shown_score(sc)
        when = time.strftime("%b %d %H:%M", time.localtime(os.path.getmtime(os.path.join(d, "report.json"))))
        views = os.path.join(d, "preview_views.png")
        thumb = ('<img src="%s/delivery/preview_views.png?v=%d" alt="">' % (e(job), int(os.path.getmtime(views)))) if os.path.exists(views) else ""
        zips = [f for f in os.listdir(d) if f.endswith(".zip")]
        rows.append('<tr><td class="t"><a href="%(j)s/delivery/preview.html">%(thumb)s</a></td><td><a class="name" href="%(j)s/delivery/preview.html">%(j)s</a>'
                    '<div class="sub">%(cat)s · %(how)s</div></td><td class="sc %(cls)s">%(score)s</td><td class="when">%(when)s</td>'
                    '<td class="links"><a href="%(j)s/delivery/preview.html">3D preview</a><a href="%(j)s/delivery/preview_views.png">Six views</a>'
                    '<a href="refs?jobs=%(j)s">References</a>%(zip)s</td></tr>' % {
                        "j": e(job), "thumb": thumb, "cat": e(brief.get("category", "")), "how": e(sc.get("tonetta") or ""),
                        "cls": "" if score is None else "good" if score >= 8 else "mid" if score >= 7 else "low",
                        "score": "–" if score is None else "%g %s" % (score, who), "when": when,
                        "zip": ('<a href="%s/delivery/%s">Zip</a>' % (e(job), e(zips[0]))) if zips else ""})
    built = set(results_page.delivered_jobs(out_dir))
    pending = ['<li><a href="refs?jobs=%s">%s</a></li>' % (e(j), e(j)) for j in _jobs_by_recent(out_dir, False) if j not in built]
    return HOME % {"nav": nav("home"), "n": len(rows), "rows": "".join(rows) or '<tr><td colspan="5">No builds yet.</td></tr>',
                   "pending": "".join(pending) or "<li>None.</li>"}


HOME = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<link rel="icon" href="data:,"><title>Master Smith</title><style>
:root{color-scheme:light;--g:#edeff2;--s:#fff;--i:#1b2127;--m:#5a6571;--l:#d4d9df;--a:#2e5e8c;--ok:#2f7d4f;--mid:#a8690f;--low:#b03a2e}
@media (prefers-color-scheme:dark){:root{color-scheme:dark;--g:#13171b;--s:#1c2228;--i:#e6eaee;--m:#9aa6b2;--l:#2e363f;--a:#7fa8d6;--ok:#63be87;--mid:#e3aa4f;--low:#e07a6e}}
body{margin:0;background:var(--g);color:var(--i);font:15px/1.45 "Segoe UI",system-ui,sans-serif}
main{max-width:1200px;margin:0 auto;padding:20px 16px 60px;display:grid;gap:18px}
h1{margin:0;font:600 26px "Segoe UI Semibold","Segoe UI",sans-serif} h2{margin:8px 0 0;font:600 18px "Segoe UI Semibold","Segoe UI",sans-serif}
p{margin:0;color:var(--m)} .wrap{overflow-x:auto;background:var(--s);border:1px solid var(--l);border-radius:8px}
table{border-collapse:collapse;width:100%%} td{padding:8px 12px;border-bottom:1px solid var(--l);vertical-align:middle}
tr:last-child td{border-bottom:0} td.t img{width:150px;height:auto;display:block;border-radius:4px;background:#9a9da1}
a{color:var(--a)} a.name{font-weight:600;text-decoration:none;color:var(--i)} a.name:hover{text-decoration:underline}
.sub{font-size:13px;color:var(--m);max-width:48ch} .when{font:12px Consolas,monospace;color:var(--m);white-space:nowrap}
.sc{font:600 16px Consolas,monospace;text-align:center;white-space:nowrap} .good{color:var(--ok)} .mid{color:var(--mid)} .low{color:var(--low)}
.links a{display:inline-block;margin:2px 10px 2px 0;font-size:14px;white-space:nowrap}
ul{margin:0;padding-left:20px;columns:3 220px}
</style></head><body>%(nav)s<main>
<h1>Master Smith</h1><p>%(n)d builds, newest first. Click a picture or name for the 3D preview; every page has the bar above to come back.</p>
<div class="wrap"><table>%(rows)s</table></div>
<h2>Jobs with pictures and no build yet</h2><ul>%(pending)s</ul>
</main></body></html>"""


class Handler(refs_review.Handler):
    """Static files from out/, the reference-review writes (POST /api/review), and the rendered pages."""

    def _html(self, text):
        raw = text.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(url.query)
        pick = [j for j in ",".join(q.get("jobs", [])).split(",") if j]
        out_dir = self.directory
        try:
            if url.path in ("/", "/index.html"):
                return self._html(home_page(out_dir))
            if url.path in ("/results", "/results.html"):
                jobs = [j for j in pick if j in results_page.delivered_jobs(out_dir)] or _jobs_by_recent(out_dir, True)
                return self._html(results_page.render_results(out_dir, jobs).replace("<body>", "<body>" + nav("results"), 1))
            if url.path in ("/refs", "/refs.html"):
                jobs = [j for j in pick if j in refs_review.all_jobs(out_dir)] or _jobs_by_recent(out_dir, False)
                return self._html(refs_review.render_page(out_dir, jobs).replace("<body>", "<body>" + nav("refs"), 1))
            if url.path == "/api/ping":
                return self._json(200, {"mastersmith": True, "out_dir": os.path.abspath(out_dir), "pid": os.getpid(), "code": LOADED})
        except Exception as exc:  # noqa: BLE001 - a broken job folder shows as an error page, the server stays up
            return self._json(500, {"error": str(exc)})
        return super().do_GET()

    def do_POST(self):
        if self.path == "/api/stop":
            self._json(200, {"stopping": True})
            os._exit(0)
        return super().do_POST()


def serve(out_dir, port):
    ThreadingHTTPServer(("127.0.0.1", port), partial(Handler, directory=os.path.abspath(out_dir))).serve_forever()


def _ping(port, timeout=1.5):
    try:
        with urllib.request.urlopen("http://127.0.0.1:%d/api/ping" % port, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:  # noqa: BLE001 - nothing (or something else) on the port
        return None


def ensure(out_dir, port, root, restart=False):
    """The site running on `port` for `out_dir`, started or restarted as needed. -> base URL"""
    out_dir = os.path.abspath(out_dir)
    p = _ping(port)
    if p and (restart or p.get("code") != code_stamp() or os.path.normcase(p.get("out_dir", "")) != os.path.normcase(out_dir)):
        try:
            urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:%d/api/stop" % port, data=b"{}", method="POST"), timeout=2)
        except Exception:  # noqa: BLE001 - it exits while answering
            pass
        for _ in range(20):
            if not _ping(port, 0.3):
                break
            time.sleep(0.2)
        p = None
    if not p:
        flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
        subprocess.Popen([sys.executable, "-m", "mastersmith.site", out_dir, str(port)], cwd=str(root),
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)
        for _ in range(50):
            p = _ping(port, 0.3)
            if p:
                break
            time.sleep(0.2)
        if not p:
            raise RuntimeError("the site did not start on port %d (something else on it? set MASTERSMITH_PREVIEW_PORT)" % port)
    return "http://127.0.0.1:%d" % port


if __name__ == "__main__":
    serve(sys.argv[1], int(sys.argv[2]))
