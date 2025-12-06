#!/usr/bin/env python3
import http.server
import socketserver

PORT = 8000

class Handler(http.server.SimpleHTTPRequestHandler):
    pass

with socketserver.TCPServer(("127.0.0.1", PORT), Handler) as httpd:
    print(f"Serving at port {PORT}")
    httpd.serve_forever()
