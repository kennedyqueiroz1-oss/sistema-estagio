#!/usr/bin/env python3
"""
Sistema de Estágio — servidor online com Supabase/PostgreSQL.

Variáveis necessárias no Railway:
DATABASE_URL = URI do banco Supabase
PORT         = definida automaticamente pelo Railway
"""

import http.server
import json
import os
from pathlib import Path
from urllib.parse import urlparse, parse_qs

import psycopg2
import psycopg2.extras


BASE_DIR = Path(__file__).parent
PORT = int(os.environ.get("PORT", "8765"))

CHAVES = {
    "est_cal": "calendario",
    "est_alunos": "alunos",
    "est_emp": "empresas",
    "est_enc": "encaminhamentos",
}

DEFAULTS = {
    "est_cal": {},
    "est_alunos": [],
    "est_emp": [],
    "est_enc": {},
}

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".ico": "image/x-icon",
    ".txt": "text/plain; charset=utf-8",
}


def get_database_url():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL não configurada no Railway.")
    if "sslmode=" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}sslmode=require"
    return url


def get_conn():
    return psycopg2.connect(get_database_url())


def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                create table if not exists sistema_dados (
                    chave text primary key,
                    dados jsonb not null,
                    atualizado_em timestamp with time zone default now()
                );
            """)
            for chave, dados in DEFAULTS.items():
                cur.execute("""
                    insert into sistema_dados (chave, dados)
                    values (%s, %s)
                    on conflict (chave) do nothing;
                """, (chave, json.dumps(dados, ensure_ascii=False)))
        conn.commit()


def carregar_dados(chave):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("select dados from sistema_dados where chave = %s", (chave,))
            row = cur.fetchone()
            if row is None:
                return DEFAULTS[chave]
            return row["dados"]


def salvar_dados(chave, dados):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                insert into sistema_dados (chave, dados, atualizado_em)
                values (%s, %s, now())
                on conflict (chave)
                do update set dados = excluded.dados, atualizado_em = now();
            """, (chave, json.dumps(dados, ensure_ascii=False)))
        conn.commit()


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        status = args[1] if len(args) > 1 else "?"
        print(f"{self.command:6} {status} {self.path.split('?')[0]}")

    def cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Cache-Control", "no-cache, no-store")

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.cors()
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, fpath: Path):
        data = fpath.read_bytes()
        ctype = MIME.get(fpath.suffix.lower(), "application/octet-stream")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.cors()
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self):
        self.send_response(204)
        self.cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"

        if route == "/api/status":
            try:
                info = {}
                for chave in CHAVES:
                    dados = carregar_dados(chave)
                    info[chave] = len(dados)
                return self.send_json({"ok": True, "banco": "Supabase/PostgreSQL", "registros": info})
            except Exception as e:
                return self.send_json({"ok": False, "erro": str(e)}, 500)

        if route == "/api/dados":
            params = parse_qs(parsed.query)
            chave = params.get("chave", [None])[0]
            if chave not in CHAVES:
                return self.send_json({"ok": False, "erro": f"chave desconhecida: {chave}"}, 400)
            try:
                return self.send_json({"ok": True, "dados": carregar_dados(chave)})
            except Exception as e:
                return self.send_json({"ok": False, "erro": str(e)}, 500)

        if route == "/":
            route = "/sistema-estagio.html"

        fpath = BASE_DIR / route.lstrip("/")
        if fpath.exists() and fpath.is_file():
            return self.send_file(fpath)

        self.send_response(404)
        self.end_headers()
        self.wfile.write(b"404 Not Found")

    def do_POST(self):
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/")

        if route == "/api/dados":
            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                chave = payload.get("chave")
                dados = payload.get("dados")

                if chave not in CHAVES:
                    return self.send_json({"ok": False, "erro": f"chave desconhecida: {chave}"}, 400)
                if dados is None:
                    return self.send_json({"ok": False, "erro": "campo 'dados' ausente"}, 400)

                salvar_dados(chave, dados)
                return self.send_json({"ok": True})
            except json.JSONDecodeError as e:
                return self.send_json({"ok": False, "erro": f"JSON inválido: {e}"}, 400)
            except Exception as e:
                return self.send_json({"ok": False, "erro": str(e)}, 500)

        self.send_response(404)
        self.end_headers()


class ThreadedServer(http.server.ThreadingHTTPServer):
    daemon_threads = True


if __name__ == "__main__":
    init_db()
    server = ThreadedServer(("0.0.0.0", PORT), Handler)
    print("=" * 54)
    print("Sistema de Estágio — Online")
    print(f"Porta: {PORT}")
    print("Banco: Supabase/PostgreSQL")
    print("=" * 54)
    server.serve_forever()
