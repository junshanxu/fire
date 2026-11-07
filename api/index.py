"""Vercel entrypoint for the inspection demo.

The local development server remains ``platform_app.http_server.run``. On
Vercel each request is handled by this adapter, so no background scheduler or
process-local persistence is assumed.
"""

from platform_app.http_server import PlatformHandler


class handler(PlatformHandler):
    pass
