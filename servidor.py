#!/usr/bin/env python3
"""
Sistema de Estágio — servidor online com Supabase/PostgreSQL e Autenticação.

Variáveis necessárias no Railway:
DATABASE_URL = URI do banco Supabase
PORT         = definida automaticamente pelo Railway
"""

import http.server
import json
import os
import hashlib
import uuid
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

# Controle de sessões em memória: token -> {usuario, nome, tipo}
SESSIONS = {}

def hash_senha(senha, usuario):
    hasher = hashlib.sha256()
    hasher.update(f"{senha}:{usuario.lower().strip()}:sistema_estagio_salt_super_secreto_2026".encode('utf-8'))
    return hasher.hexdigest()

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
            # 1. Tabela de dados do sistema
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

            # 2. Tabela de usuários para login
            cur.execute("""
                create table if not exists sistema_usuarios (
                    usuario text primary key,
                    senha_hash text not null,
                    nome text not null,
                    tipo text not null check (tipo in ('coordenador', 'orientador', 'visualizador')),
                    criado_em timestamp with time zone default now()
                );
            """)

            # 3. Seed do coordenador inicial
            cur.execute("select count(*) from sistema_usuarios;")
            count = cur.fetchone()[0]
            if count == 0:
                user_padrao = "admin"
                senha_padrao = "admin123"
                shash = hash_senha(senha_padrao, user_padrao)
                cur.execute("""
                    insert into sistema_usuarios (usuario, senha_hash, nome, tipo)
                    values (%s, %s, %s, %s);
                """, (user_padrao, shash, "Coordenador Geral", "coordenador"))
                print("Usuário coordenador padrão 'admin' / 'admin123' criado com sucesso.")
        conn.commit()

# Funções auxiliares para dados
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

# Funções auxiliares para usuários
def obter_usuario(usuario):
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("select usuario, senha_hash, nome, tipo from sistema_usuarios where usuario = %s", (usuario.lower().strip(),))
            return cur.fetchone()

def listar_usuarios():
    with get_conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("select usuario, nome, tipo, criado_em from sistema_usuarios order by usuario;")
            return cur.fetchall()

def salvar_usuario(usuario, senha_hash, nome, tipo):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("""
                insert into sistema_usuarios (usuario, senha_hash, nome, tipo)
                values (%s, %s, %s, %s)
                on conflict (usuario)
                do update set senha_hash = excluded.senha_hash, nome = excluded.nome, tipo = excluded.tipo;
            """, (usuario.lower().strip(), senha_hash, nome.strip(), tipo))
        conn.commit()

def excluir_usuario(usuario):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("delete from sistema_usuarios where usuario = %s;", (usuario.lower().strip(),))
        conn.commit()


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        status = args[1] if len(args) > 1 else "?"
        print(f"{self.command:6} {status} {self.path.split('?')[0]}")

    def cors(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, DELETE")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
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

    def obter_usuario_sessao(self):
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth.split(" ")[1]
            return SESSIONS.get(token)
        return None

    def do_GET(self):
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"

        # Rota pública de status
        if route == "/api/status":
            try:
                info = {}
                for chave in CHAVES:
                    dados = carregar_dados(chave)
                    info[chave] = len(dados)
                return self.send_json({"ok": True, "banco": "Supabase/PostgreSQL", "registros": info})
            except Exception as e:
                return self.send_json({"ok": False, "erro": str(e)}, 500)

        # Todas as outras rotas da API requerem autenticação
        if route.startswith("/api/"):
            usuario_sessao = self.obter_usuario_sessao()
            if not usuario_sessao:
                return self.send_json({"ok": False, "erro": "Não autorizado. Faça login novamente."}, 401)

            if route == "/api/dados":
                params = parse_qs(parsed.query)
                chave = params.get("chave", [None])[0]
                if chave not in CHAVES:
                    return self.send_json({"ok": False, "erro": f"chave desconhecida: {chave}"}, 400)
                try:
                    return self.send_json({"ok": True, "dados": carregar_dados(chave)})
                except Exception as e:
                    return self.send_json({"ok": False, "erro": str(e)}, 500)

            if route == "/api/usuarios":
                # Apenas Coordenador pode listar usuários
                if usuario_sessao["tipo"] != "coordenador":
                    return self.send_json({"ok": False, "erro": "Acesso negado. Apenas coordenadores podem gerenciar usuários."}, 403)
                try:
                    return self.send_json({"ok": True, "usuarios": listar_usuarios()})
                except Exception as e:
                    return self.send_json({"ok": False, "erro": str(e)}, 500)

        # Se for arquivos estáticos
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

        # Rota pública de login
        if route == "/api/login":
            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                usuario_raw = payload.get("usuario", "")
                senha_raw = payload.get("senha", "")

                user_db = obter_usuario(usuario_raw)
                if not user_db:
                    return self.send_json({"ok": False, "erro": "Usuário ou senha incorretos."}, 401)

                shash = hash_senha(senha_raw, usuario_raw)
                if user_db["senha_hash"] != shash:
                    return self.send_json({"ok": False, "erro": "Usuário ou senha incorretos."}, 401)

                # Gera token de sessão
                token = uuid.uuid4().hex
                usuario_info = {
                    "usuario": user_db["usuario"],
                    "nome": user_db["nome"],
                    "tipo": user_db["tipo"]
                }
                SESSIONS[token] = usuario_info
                return self.send_json({"ok": True, "token": token, "usuario": usuario_info})
            except Exception as e:
                return self.send_json({"ok": False, "erro": str(e)}, 500)

        # Todas as outras rotas POST requerem autenticação
        usuario_sessao = self.obter_usuario_sessao()
        if not usuario_sessao:
            return self.send_json({"ok": False, "erro": "Não autorizado. Faça login novamente."}, 401)

        if route == "/api/dados":
            # Visualizadores não podem alterar dados
            if usuario_sessao["tipo"] == "visualizador":
                return self.send_json({"ok": False, "erro": "Acesso negado. Perfil de apenas visualização."}, 403)

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

        if route == "/api/usuarios":
            # Apenas Coordenador pode criar usuários
            if usuario_sessao["tipo"] != "coordenador":
                return self.send_json({"ok": False, "erro": "Acesso negado. Apenas coordenadores podem gerenciar usuários."}, 403)

            length = int(self.headers.get("Content-Length", 0))
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                new_user = payload.get("usuario", "").strip().lower()
                new_pass = payload.get("senha", "")
                new_name = payload.get("nome", "").strip()
                new_type = payload.get("tipo", "")

                if not new_user or not new_pass or not new_name or new_type not in ('coordenador', 'orientador', 'visualizador'):
                    return self.send_json({"ok": False, "erro": "Preencha todos os campos corretamente."}, 400)

                senha_hash = hash_senha(new_pass, new_user)
                salvar_usuario(new_user, senha_hash, new_name, new_type)
                return self.send_json({"ok": True})
            except Exception as e:
                return self.send_json({"ok": False, "erro": str(e)}, 500)

        self.send_response(404)
        self.end_headers()

    def do_DELETE(self):
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/")

        # Requer autenticação e ser Coordenador
        usuario_sessao = self.obter_usuario_sessao()
        if not usuario_sessao:
            return self.send_json({"ok": False, "erro": "Não autorizado. Faça login novamente."}, 401)

        if route == "/api/usuarios":
            if usuario_sessao["tipo"] != "coordenador":
                return self.send_json({"ok": False, "erro": "Acesso negado. Apenas coordenadores podem gerenciar usuários."}, 403)

            params = parse_qs(parsed.query)
            user_to_delete = params.get("usuario", [None])[0]

            if not user_to_delete:
                return self.send_json({"ok": False, "erro": "Usuário não especificado."}, 400)

            user_to_delete = user_to_delete.strip().lower()

            # Impede o coordenador de se excluir
            if user_to_delete == usuario_sessao["usuario"]:
                return self.send_json({"ok": False, "erro": "Você não pode excluir o seu próprio usuário enquanto está conectado."}, 400)

            try:
                user_db = obter_usuario(user_to_delete)
                if not user_db:
                    return self.send_json({"ok": False, "erro": "Usuário não encontrado."}, 404)

                excluir_usuario(user_to_delete)
                return self.send_json({"ok": True})
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
    print("Sistema de Estágio — Online com Autenticação")
    print(f"Porta: {PORT}")
    print("Banco: Supabase/PostgreSQL")
    print("=" * 54)
    server.serve_forever()
