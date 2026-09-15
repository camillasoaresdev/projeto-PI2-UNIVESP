import hashlib
import hmac
import json
import re
import secrets
import sqlite3
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse


ROOT = Path(__file__).resolve().parent
DATABASE = ROOT / "database" / "urban_barber.db"
SCHEMA = ROOT / "database" / "schema.sql"
STATIC_ROOT = ROOT / "Templates aplicativo"
PASSWORD_ITERATIONS = 310_000


def initialize_database():
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DATABASE) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.executescript(SCHEMA.read_text(encoding="utf-8"))
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(usuarios)")
        }
        if "email" not in columns:
            connection.execute("ALTER TABLE usuarios ADD COLUMN email TEXT")
        if "telefone" not in columns:
            connection.execute("ALTER TABLE usuarios ADD COLUMN telefone TEXT")
        if "contato" in columns:
            connection.execute(
                "UPDATE usuarios SET email = contato WHERE email IS NULL"
            )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_usuarios_email ON usuarios (email)"
        )
        connection.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_usuarios_telefone ON usuarios (telefone)"
        )


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )
    return f"{PASSWORD_ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password, stored_hash):
    try:
        iterations, salt_hex, digest_hex = stored_hash.split("$")
        expected = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            int(iterations),
        ).hex()
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(expected, digest_hex)


def validate_credentials(payload, registering):
    name = str(payload.get("name", "")).strip()
    email = str(payload.get("email", "")).strip().lower()
    phone = re.sub(r"\D", "", str(payload.get("phone", "")))
    password = str(payload.get("password", ""))
    role = payload.get("role", "cliente")

    if registering and len(name) < 2:
        return "Informe um nome válido."
    if registering and (
        not email
        or len(email) > 120
        or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email)
    ):
        return "Informe um e-mail válido."
    if registering and len(phone) not in (10, 11):
        return "Informe um telefone válido com DDD."
    if not registering and not email and not phone:
        return "Informe seu e-mail ou telefone."
    if not registering and email and (
        len(email) > 120
        or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email)
    ):
        return "Informe um e-mail válido."
    if len(password) < 8:
        return "A senha deve ter pelo menos 8 caracteres."
    if role not in ("cliente", "barbeiro"):
        return "Perfil de usuário inválido."
    return None


class UrbanBarberHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(STATIC_ROOT), **kwargs)

    def send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/":
            self.path = "/Untitled-1.html"
        elif path.startswith("/"):
            self.path = unquote(path)
        super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        if path not in ("/api/auth/register", "/api/auth/login"):
            self.send_json(HTTPStatus.NOT_FOUND, {"error": "Rota não encontrada."})
            return

        try:
            payload = self.read_json()
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": "JSON inválido."})
            return

        registering = path.endswith("register")
        error = validate_credentials(payload, registering)
        if error:
            self.send_json(HTTPStatus.BAD_REQUEST, {"error": error})
            return

        email = str(payload.get("email", "")).strip().lower()
        phone = re.sub(r"\D", "", str(payload.get("phone", "")))
        with sqlite3.connect(DATABASE) as connection:
            connection.row_factory = sqlite3.Row
            if registering:
                try:
                    user_columns = {
                        row[1]
                        for row in connection.execute("PRAGMA table_info(usuarios)")
                    }
                    values = (
                        str(payload["name"]).strip(),
                        email,
                        phone,
                        hash_password(str(payload["password"])),
                        payload.get("role", "cliente"),
                    )
                    if "contato" in user_columns:
                        cursor = connection.execute(
                            """
                            INSERT INTO usuarios
                                (nome, contato, email, telefone, senha_hash, perfil)
                            VALUES (?, ?, ?, ?, ?, ?)
                            """,
                            (values[0], email, *values[1:]),
                        )
                    else:
                        cursor = connection.execute(
                            """
                            INSERT INTO usuarios (nome, email, telefone, senha_hash, perfil)
                            VALUES (?, ?, ?, ?, ?)
                            """,
                            values,
                        )
                    user = connection.execute(
                        "SELECT id, nome, email, telefone, perfil FROM usuarios WHERE id = ?",
                        (cursor.lastrowid,),
                    ).fetchone()
                except sqlite3.IntegrityError:
                    self.send_json(
                        HTTPStatus.CONFLICT,
                        {"error": "Este e-mail ou telefone já está cadastrado."},
                    )
                    return
            else:
                user = connection.execute(
                    """
                    SELECT id, nome, email, telefone, perfil, senha_hash
                    FROM usuarios
                    WHERE (email = ? OR telefone = ?) AND ativo = 1
                    """,
                    (email, phone),
                ).fetchone()
                if user is None or not verify_password(
                    str(payload["password"]), user["senha_hash"]
                ):
                    self.send_json(
                        HTTPStatus.UNAUTHORIZED,
                        {"error": "E-mail/telefone ou senha inválidos."},
                    )
                    return

        self.send_json(
            HTTPStatus.OK,
            {
                "message": "Conta criada com sucesso." if registering else "Login realizado.",
                "user": {
                    "id": user["id"],
                    "name": user["nome"],
                    "email": user["email"],
                    "phone": user["telefone"],
                    "role": user["perfil"],
                },
            },
        )


if __name__ == "__main__":
    initialize_database()
    server = ThreadingHTTPServer(("127.0.0.1", 8000), UrbanBarberHandler)
    print("Urban Barber disponível em http://127.0.0.1:8000")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nServidor encerrado.")
    finally:
        server.server_close()