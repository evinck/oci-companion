import importlib.util
import os
import secrets
import threading
import time
from functools import wraps
from urllib.parse import urlencode

import jwt
import requests
from flask import Flask, jsonify, make_response, redirect, request, send_from_directory

# Load the generator helpers from oci-web1.py, whose filename cannot be imported directly as a module.
OCI_WEB1_PATH = os.path.join(os.path.dirname(__file__), "oci-web1.py")
OCI_WEB1_SPEC = importlib.util.spec_from_file_location("oci_web1_script", OCI_WEB1_PATH)
OCI_WEB1_MODULE = importlib.util.module_from_spec(OCI_WEB1_SPEC)
OCI_WEB1_SPEC.loader.exec_module(OCI_WEB1_MODULE)

build_arg_parser = OCI_WEB1_MODULE.build_arg_parser
generate_output = OCI_WEB1_MODULE.generate_output


DOCUMENT_ROOT = os.path.join(os.path.dirname(__file__), "DocumentRoot")
SESSION_COOKIE_NAME = "oci_companion_sid"


# Collect the runtime authentication settings used by the web app.
class AuthConfig:
    # Read OCI IAM and session settings from the environment.
    def __init__(self):
        self.domain_url = os.getenv("OCI_IAM_DOMAIN_URL", "").strip().rstrip("/")
        self.client_id = os.getenv("OCI_IAM_CLIENT_ID", "").strip()
        self.client_secret = os.getenv("OCI_IAM_CLIENT_SECRET", "").strip()
        self.redirect_uri = os.getenv(
            "OCI_IAM_REDIRECT_URI", "https://localhost:8080/auth/callback"
        ).strip()
        self.scopes = os.getenv("OCI_IAM_SCOPES", "openid profile email").strip()
        self.cookie_secure = (
            os.getenv("OCI_COMPANION_COOKIE_SECURE", "false").strip().lower() == "true"
        )
        self.session_ttl_seconds = int(
            os.getenv("OCI_COMPANION_SESSION_TTL_SECONDS", "43200")
        )
        self.discovery_timeout = float(
            os.getenv("OCI_COMPANION_HTTP_TIMEOUT_SECONDS", "10")
        )

    @property
    # Tell the app whether OCI IAM authentication is fully configured.
    def enabled(self):
        return all(
            [
                self.domain_url,
                self.client_id,
                self.client_secret,
                self.redirect_uri,
            ]
        )

    @property
    # Build the OIDC discovery endpoint from the identity domain URL.
    def discovery_url(self):
        return self.domain_url + "/.well-known/openid-configuration"


# Store browser sessions in memory with simple expiration handling.
class InMemorySessionStore:
    # Initialize the in-memory session store with a TTL.
    def __init__(self, ttl_seconds):
        self.ttl_seconds = ttl_seconds
        self.sessions = {}
        self.lock = threading.Lock()

    # Return an active session and extend its expiration.
    def get(self, session_id):
        if not session_id:
            return None
        with self.lock:
            session = self.sessions.get(session_id)
            if not session:
                return None
            if session["expires_at"] <= time.time():
                self.sessions.pop(session_id, None)
                return None
            session["expires_at"] = time.time() + self.ttl_seconds
            return session["data"]

    # Create a new empty session entry.
    def create(self):
        session_id = secrets.token_urlsafe(32)
        with self.lock:
            self.sessions[session_id] = {
                "expires_at": time.time() + self.ttl_seconds,
                "data": {},
            }
        return session_id

    # Remove a session from the store.
    def delete(self, session_id):
        with self.lock:
            self.sessions.pop(session_id, None)

    # Clean up expired sessions from memory.
    def prune(self):
        now = time.time()
        with self.lock:
            expired_ids = [
                session_id
                for session_id, session in self.sessions.items()
                if session["expires_at"] <= now
            ]
            for session_id in expired_ids:
                self.sessions.pop(session_id, None)


# Handle OIDC discovery, token exchange, and token validation.
class OIDCClient:
    # Keep OIDC metadata and signing keys for the current identity domain.
    def __init__(self, auth_config):
        self.auth_config = auth_config
        self.discovery_document = None
        self.jwks_client = None
        self.lock = threading.Lock()

    # Fetch and cache the OIDC discovery document and JWKS endpoint.
    def get_discovery_document(self):
        if self.discovery_document:
            return self.discovery_document

        with self.lock:
            if self.discovery_document:
                return self.discovery_document
            response = requests.get(
                self.auth_config.discovery_url,
                timeout=self.auth_config.discovery_timeout,
            )
            response.raise_for_status()
            self.discovery_document = response.json()
            jwks_uri = self.discovery_document.get("jwks_uri")
            if jwks_uri:
                self.jwks_client = jwt.PyJWKClient(jwks_uri)
            return self.discovery_document

    # Build the authorization URL used to start the login flow.
    def build_authorization_url(self, state, nonce):
        discovery_document = self.get_discovery_document()
        query = {
            "client_id": self.auth_config.client_id,
            "response_type": "code",
            "scope": self.auth_config.scopes,
            "redirect_uri": self.auth_config.redirect_uri,
            "state": state,
            "nonce": nonce,
        }
        return discovery_document["authorization_endpoint"] + "?" + urlencode(query)

    # Exchange an authorization code for tokens.
    def exchange_code(self, code):
        discovery_document = self.get_discovery_document()
        response = requests.post(
            discovery_document["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": self.auth_config.redirect_uri,
            },
            auth=(self.auth_config.client_id, self.auth_config.client_secret),
            timeout=self.auth_config.discovery_timeout,
        )
        response.raise_for_status()
        return response.json()

    # Load the authenticated user's profile from the userinfo endpoint.
    def fetch_userinfo(self, access_token):
        discovery_document = self.get_discovery_document()
        userinfo_endpoint = discovery_document.get("userinfo_endpoint")
        if not userinfo_endpoint:
            return {}
        response = requests.get(
            userinfo_endpoint,
            headers={"Authorization": "Bearer {}".format(access_token)},
            timeout=self.auth_config.discovery_timeout,
        )
        response.raise_for_status()
        return response.json()

    # Validate the ID token signature and expected claims.
    def validate_id_token(self, id_token, nonce):
        discovery_document = self.get_discovery_document()
        signing_key = self.jwks_client.get_signing_key_from_jwt(id_token)
        decoded = jwt.decode(
            id_token,
            signing_key.key,
            algorithms=["RS256", "RS384", "RS512", "ES256", "ES384", "ES512"],
            audience=self.auth_config.client_id,
            issuer=discovery_document["issuer"],
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
        if nonce and decoded.get("nonce") != nonce:
            raise ValueError("OIDC nonce mismatch")
        return decoded


# Keep redirect targets on local application paths only.
def safe_next_url(candidate):
    if not candidate:
        return "/"
    if not candidate.startswith("/"):
        return "/"
    if candidate.startswith("//"):
        return "/"
    return candidate


# Create and configure the Flask application.
def create_app(args):
    auth_config = AuthConfig()
    session_store = InMemorySessionStore(auth_config.session_ttl_seconds)
    oidc_client = OIDCClient(auth_config)
    data_file = os.path.abspath(args.output_location)

    app = Flask(__name__, static_folder=None)

    # Load the current session from the browser cookie.
    def get_session(create=False):
        session_store.prune()
        session_id = request.cookies.get(SESSION_COOKIE_NAME)
        session_data = session_store.get(session_id)
        if session_data is not None:
            return session_id, session_data
        if not create:
            return None, None
        session_id = session_store.create()
        return session_id, session_store.get(session_id)

    # Add the session cookie to the outgoing response.
    def attach_session_cookie(response, session_id):
        if not session_id:
            return response
        response.set_cookie(
            SESSION_COOKIE_NAME,
            session_id,
            httponly=True,
            secure=auth_config.cookie_secure,
            samesite="Lax",
            max_age=auth_config.session_ttl_seconds,
        )
        return response

    # Remove the session cookie from the browser.
    def clear_session_cookie(response):
        response.delete_cookie(SESSION_COOKIE_NAME, samesite="Lax")
        return response

    # Protect routes that require an authenticated user.
    def login_required(view):
        @wraps(view)
        # Redirect unauthenticated users into the login flow.
        def wrapped(*view_args, **view_kwargs):
            if not auth_config.enabled:
                return view(*view_args, **view_kwargs)

            session_id, session_data = get_session(create=True)
            if session_data.get("user"):
                response = make_response(view(*view_args, **view_kwargs))
                return attach_session_cookie(response, session_id)

            session_data["next_url"] = safe_next_url(request.full_path or request.path)
            response = make_response(redirect("/login"))
            return attach_session_cookie(response, session_id)

        return wrapped

    @app.route("/healthz")
    # Report a simple health status for the web app.
    def healthz():
        return jsonify({"status": "ok", "auth_enabled": auth_config.enabled})

    @app.route("/login")
    # Start the OCI IAM authorization code flow.
    def login():
        if not auth_config.enabled:
            return redirect("/")

        session_id, session_data = get_session(create=True)
        state = secrets.token_urlsafe(24)
        nonce = secrets.token_urlsafe(24)
        session_data["oauth_state"] = state
        session_data["oauth_nonce"] = nonce
        try:
            authorization_url = oidc_client.build_authorization_url(state, nonce)
        except requests.RequestException as exc:
            return make_response(
                "Authentication failed: unable to load OCI IAM metadata ({})".format(
                    exc
                ),
                502,
            )

        response = make_response(redirect(authorization_url))
        return attach_session_cookie(response, session_id)

    @app.route("/auth/callback")
    # Complete the OCI IAM login flow and create a local session.
    def auth_callback():
        if not auth_config.enabled:
            return redirect("/")

        error = request.args.get("error")
        if error:
            return make_response(
                "Authentication failed: {}".format(error), 400
            )

        session_id, session_data = get_session(create=True)
        returned_state = request.args.get("state", "")
        expected_state = session_data.get("oauth_state")
        if not expected_state or returned_state != expected_state:
            return make_response("Authentication failed: invalid state", 400)

        code = request.args.get("code")
        if not code:
            return make_response("Authentication failed: missing code", 400)

        try:
            token_response = oidc_client.exchange_code(code)
            id_token = token_response.get("id_token")
            access_token = token_response.get("access_token")
            if not id_token or not access_token:
                return make_response("Authentication failed: missing tokens", 400)

            id_claims = oidc_client.validate_id_token(
                id_token, session_data.get("oauth_nonce")
            )
            userinfo = oidc_client.fetch_userinfo(access_token)
        except requests.RequestException as exc:
            return make_response(
                "Authentication failed: token or userinfo request failed ({})".format(
                    exc
                ),
                502,
            )
        except (jwt.PyJWTError, ValueError) as exc:
            return make_response(
                "Authentication failed: invalid ID token ({})".format(exc),
                400,
            )

        session_data["user"] = {
            "sub": id_claims.get("sub"),
            "email": userinfo.get("email") or id_claims.get("email"),
            "name": userinfo.get("name")
            or userinfo.get("preferred_username")
            or id_claims.get("name")
            or id_claims.get("preferred_username")
            or id_claims.get("sub"),
        }
        session_data.pop("oauth_state", None)
        session_data.pop("oauth_nonce", None)
        next_url = safe_next_url(session_data.pop("next_url", "/"))

        response = make_response(redirect(next_url))
        return attach_session_cookie(response, session_id)

    @app.route("/logout")
    # Clear the local session and return to the home page.
    def logout():
        session_id = request.cookies.get(SESSION_COOKIE_NAME)
        if session_id:
            session_store.delete(session_id)
        response = make_response(redirect("/"))
        return clear_session_cookie(response)

    @app.route("/api/session")
    @login_required
    # Return the current authentication state for the frontend.
    def session_info():
        if not auth_config.enabled:
            return jsonify(
                {
                    "auth_enabled": False,
                    "authenticated": False,
                    "user": None,
                }
            )

        _, session_data = get_session(create=False)
        return jsonify(
            {
                "auth_enabled": True,
                "authenticated": bool(session_data and session_data.get("user")),
                "user": session_data.get("user") if session_data else None,
            }
        )

    @app.route("/data.json")
    @login_required
    # Serve the generated OCI data payload.
    def data_json():
        return send_from_directory(
            os.path.dirname(data_file),
            os.path.basename(data_file),
            mimetype="application/json",
        )

    @app.route("/")
    @login_required
    # Serve the main application page.
    def index():
        return send_from_directory(DOCUMENT_ROOT, "index.html")

    @app.route("/styles.css")
    # Serve the application stylesheet.
    def styles():
        return send_from_directory(DOCUMENT_ROOT, "styles.css")

    @app.route("/images/<path:filename>")
    # Serve static image assets used by the UI.
    def images(filename):
        return send_from_directory(os.path.join(DOCUMENT_ROOT, "images"), filename)

    return app


# Build the mandatory SSL context tuple expected by Flask.
def resolve_ssl_context(args):
    if not args.ssl_cert_file or not args.ssl_key_file:
        raise ValueError(
            "HTTPS is required. Provide both --ssl-cert-file and --ssl-key-file."
        )

    return (args.ssl_cert_file, args.ssl_key_file)


# Run one OCI scan and write the refreshed data.json file.
def refresh_data_file(args):
    print("Refreshing data file at {}".format(args.output_location))
    generate_output(
        profile_name=args.profile_name,
        profile_location=args.profile_location,
        compartment_id=args.compartment_id,
        output_location=args.output_location,
        debug=args.debug,
        debug_files=args.debugFiles,
    )


# Start the background worker that continuously refreshes OCI data.
def start_refresh_worker(args):
    if args.keep_existing_data:
        return None

    # Re-run OCI discovery as soon as the previous pass finishes.
    def refresh_loop():
        while True:
            try:
                refresh_data_file(args)
            except Exception as exc:
                print("Background refresh failed: {}".format(exc), flush=True)

    worker = threading.Thread(
        target=refresh_loop,
        name="oci-companion-refresh-worker",
        daemon=True,
    )
    worker.start()
    print("Background refresh worker started")
    return worker


# Ensure an existing data file is present before serving it.
def ensure_existing_data_file(path):
    if os.path.isfile(path):
        return
    raise FileNotFoundError(
        "The existing data file was requested but not found: {}".format(path)
    )


# Parse startup options, initialize data, and launch the web app.
def main(argv=None):
    parser = build_arg_parser()
    parser.add_argument(
        "--listen-host",
        dest="listen_host",
        default=os.getenv("OCI_COMPANION_LISTEN_HOST", "0.0.0.0"),
        help="the listen host",
    )
    parser.add_argument(
        "--listen-port",
        dest="listen_port",
        type=int,
        default=int(os.getenv("OCI_COMPANION_LISTEN_PORT", "8080")),
        help="the listen port",
    )
    parser.add_argument(
        "--ssl-cert-file",
        dest="ssl_cert_file",
        default=os.getenv("OCI_COMPANION_SSL_CERT_FILE", "").strip(),
        help="the TLS certificate file for HTTPS",
    )
    parser.add_argument(
        "--ssl-key-file",
        dest="ssl_key_file",
        default=os.getenv("OCI_COMPANION_SSL_KEY_FILE", "").strip(),
        help="the TLS private key file for HTTPS",
    )
    parser.add_argument(
        "--keep-existing-data",
        dest="keep_existing_data",
        action="store_true",
        help="serve the existing data.json without regenerating it",
    )
    args = parser.parse_args(argv)

    if args.keep_existing_data:
        ensure_existing_data_file(args.output_location)
        print("Using existing data file at {}".format(args.output_location))
    else:
        refresh_data_file(args)

    app = create_app(args)
    start_refresh_worker(args)
    ssl_context = resolve_ssl_context(args)
    app.run(host=args.listen_host, port=args.listen_port, ssl_context=ssl_context)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
