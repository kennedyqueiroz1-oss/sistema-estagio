#!/usr/bin/env python3
"""
Importa os arquivos JSON atuais para a tabela sistema_dados no Supabase.

Antes de executar:
1. Coloque DATABASE_URL no ambiente, ou edite temporariamente abaixo.
2. Mantenha os arquivos JSON na mesma pasta deste script.
3. Execute: python importar_json.py
"""

import json
import os
from pathlib import Path

import psycopg2

BASE_DIR = Path(__file__).parent

ARQUIVOS = {
    "est_alunos": "alunos.json",
    "est_emp": "empresas.json",
    "est_cal": "calendario.json",
    "est_enc": "encaminhamentos.json",
}

DEFAULTS = {
    "est_alunos": [],
    "est_emp": [],
    "est_cal": {},
    "est_enc": {},
}


def get_database_url():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("Defina a variável DATABASE_URL com a URI do Supabase.")
    if "sslmode=" not in url:
        sep = "&" if "?" in url else "?"
        url = f"{url}{sep}sslmode=require"
    return url


def main():
    with psycopg2.connect(get_database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                create table if not exists sistema_dados (
                    chave text primary key,
                    dados jsonb not null,
                    atualizado_em timestamp with time zone default now()
                );
            """)

            for chave, nome in ARQUIVOS.items():
                caminho = BASE_DIR / nome
                if caminho.exists():
                    dados = json.loads(caminho.read_text(encoding="utf-8"))
                else:
                    dados = DEFAULTS[chave]

                cur.execute("""
                    insert into sistema_dados (chave, dados, atualizado_em)
                    values (%s, %s, now())
                    on conflict (chave)
                    do update set dados = excluded.dados, atualizado_em = now();
                """, (chave, json.dumps(dados, ensure_ascii=False)))

                print(f"Importado: {nome} -> {chave}")

        conn.commit()

    print("Migração concluída com sucesso.")


if __name__ == "__main__":
    main()
