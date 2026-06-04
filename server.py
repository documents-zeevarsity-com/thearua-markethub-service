"""
Arua MarketHub — Full Backend Server
Flask + PostgreSQL, JWT-style tokens via HMAC-SHA256, base64 image storage
"""

import hashlib, hmac, json, uuid, base64, os, time
from datetime import datetime, timedelta
from functools import wraps
import psycopg2
import psycopg2.extras
from flask import Flask, request, jsonify, send_from_directory, g

# ── Config ────────────────────────────────────────────────────────────────────
SECRET = os.environ.get("AMH_SECRET", "arua-markethub-secret-2026-change-in-prod")
DATABASE_URL = os.environ.get("DATABASE_URL")
STATIC_DIR = os.path.join(os.path.dirname(__file__), "public")

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")

# ── Database ──────────────────────────────────────────────────────────────────
def get_db():
    if "db" not in g:
        g.db = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
        g.db.autocommit = False
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop("db", None)
    if db:
        try: db.close()
        except: pass

def init_db():
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=psycopg2.extras.RealDictCursor)
    cur = conn.cursor()
    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        phone TEXT DEFAULT '',
        avatar TEXT DEFAULT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS shops (
        id TEXT PRIMARY KEY,
        owner_id TEXT NOT NULL REFERENCES users(id),
        name TEXT NOT NULL,
        description TEXT DEFAULT '',
        icon TEXT DEFAULT '🏪',
        location TEXT DEFAULT '',
        phone TEXT DEFAULT '',
        whatsapp TEXT DEFAULT '',
        email TEXT DEFAULT '',
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS subscriptions (
        user_id TEXT PRIMARY KEY REFERENCES users(id),
        plan TEXT NOT NULL,
        expiry TEXT NOT NULL,
        txn_id TEXT,
        pay_method TEXT,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS ads (
        id TEXT PRIMARY KEY,
        shop_id TEXT NOT NULL REFERENCES shops(id),
        title TEXT NOT NULL,
        price REAL NOT NULL,
        description TEXT DEFAULT '',
        category TEXT DEFAULT 'other',
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS ad_images (
        id TEXT PRIMARY KEY,
        ad_id TEXT NOT NULL REFERENCES ads(id) ON DELETE CASCADE,
        data TEXT NOT NULL,
        sort_order INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS messages (
        id TEXT PRIMARY KEY,
        from_user TEXT NOT NULL REFERENCES users(id),
        to_user TEXT NOT NULL REFERENCES users(id),
        text TEXT NOT NULL,
        read INTEGER DEFAULT 0,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS favourites (
        user_id TEXT NOT NULL REFERENCES users(id),
        ad_id TEXT NOT NULL REFERENCES ads(id) ON DELETE CASCADE,
        created_at TEXT NOT NULL,
        PRIMARY KEY (user_id, ad_id)
    );
    """)
    conn.commit()
    cur.close()
    conn.close()

# ── Helpers ───────────────────────────────────────────────────────────────────
def utcnow():
    return datetime.utcnow().isoformat() + "Z"

def hash_pw(password):
    return hashlib.sha256((password + SECRET).encode()).hexdigest()

def make_token(user_id):
    payload = json.dumps({"uid": user_id, "exp": time.time() + 60 * 60 * 24 * 30})
    b64 = base64.urlsafe_b64encode(payload.encode()).decode()
    sig = hmac.new(SECRET.encode(), b64.encode(), hashlib.sha256).hexdigest()
    return f"{b64}.{sig}"

def verify_token(token):
    try:
        b64, sig = token.rsplit(".", 1)
        expected = hmac.new(SECRET.encode(), b64.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(base64.urlsafe_b64decode(b64 + "=="))
        if payload["exp"] < time.time():
            return None
        return payload["uid"]
    except Exception:
        return None

def require_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        token = auth.removeprefix("Bearer ").strip()
        uid = verify_token(token)
        if not uid:
            return jsonify({"error": "Unauthorized"}), 401
        db = get_db()
        cur = db.cursor()
        cur.execute("SELECT * FROM users WHERE id=%s", (uid,))
        user = cur.fetchone()
        cur.close()
        if not user:
            return jsonify({"error": "User not found"}), 401
        g.current_user = dict(user)
        return f(*args, **kwargs)
    return wrapper

def optional_auth(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        token = auth.removeprefix("Bearer ").strip()
        uid = verify_token(token) if token else None
        g.current_user = None
        if uid:
            db = get_db()
            cur = db.cursor()
            cur.execute("SELECT * FROM users WHERE id=%s", (uid,))
            user = cur.fetchone()
            cur.close()
            if user:
                g.current_user = dict(user)
        return f(*args, **kwargs)
    return wrapper

def get_sub(cur, user_id):
    cur.execute(
        "SELECT * FROM subscriptions WHERE user_id=%s AND expiry > %s",
        (user_id, utcnow())
    )
    row = cur.fetchone()
    return dict(row) if row else None

def get_ad_images(db, ad_id):
    cur = db.cursor()
    cur.execute("SELECT data FROM ad_images WHERE ad_id=%s ORDER BY sort_order", (ad_id,))
    images = [r["data"] for r in cur.fetchall()]
    cur.close()
    return images

def serialize_ad_with_images(db, ad):
    return {
        "id": ad["id"],
        "shopId": ad["shop_id"],
        "title": ad["title"],
        "price": ad["price"],
        "desc": ad["description"],
        "cat": ad["category"],
        "createdAt": ad["created_at"],
        "images": get_ad_images(db, ad["id"]),
    }

def serialize_ad(db, ad, include_images=True):
    d = {
        "id": ad["id"], "shopId": ad["shop_id"], "title": ad["title"],
        "price": ad["price"], "desc": ad["description"],
        "cat": ad["category"], "createdAt": ad["created_at"],
    }
    if include_images:
        d["images"] = get_ad_images(db, ad["id"])
    return d

SUB_PLANS = {
    "basic":       {"label": "Basic",       "price": 15000,  "maxAds": 10,           "boost": 0, "maxImages": 5},
    "premium":     {"label": "Premium",      "price": 35000,  "maxAds": 30,           "boost": 1, "maxImages": 12},
    "premiumplus": {"label": "Premium Plus", "price": 105000, "maxAds": float("inf"), "boost": 2, "maxImages": float("inf")},
}

def serialize_user(u, include_private=False):
    d = {"id": u["id"], "name": u["name"], "avatar": u["avatar"]}
    if include_private:
        d.update({"email": u["email"], "phone": u["phone"], "createdAt": u["created_at"]})
    return d

def serialize_shop(s):
    return {
        "id": s["id"], "ownerId": s["owner_id"], "name": s["name"],
        "desc": s["description"], "icon": s["icon"], "location": s["location"],
        "phone": s["phone"], "whatsapp": s["whatsapp"], "email": s["email"],
        "createdAt": s["created_at"],
    }

def serialize_msg(m):
    return {
        "id": m["id"], "from": m["from_user"], "to": m["to_user"],
        "text": m["text"], "read": bool(m["read"]), "ts": m["created_at"],
    }

# ── CORS ──────────────────────────────────────────────────────────────────────
@app.after_request
def add_cors(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, PATCH, DELETE, OPTIONS"
    return response

@app.route("/<path:path>", methods=["OPTIONS"])
@app.route("/", methods=["OPTIONS"])
def options_handler(path=""):
    return "", 204

# ── Auth ──────────────────────────────────────────────────────────────────────
@app.route("/api/auth/signup", methods=["POST"])
def signup():
    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    phone = (data.get("phone") or "").strip()
    if not name: return jsonify({"error": "Name is required"}), 400
    if not email or "@" not in email: return jsonify({"error": "Valid email required"}), 400
    if len(password) < 6: return jsonify({"error": "Password must be at least 6 characters"}), 400
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT 1 FROM users WHERE email=%s", (email,))
    if cur.fetchone():
        cur.close()
        return jsonify({"error": "Email already registered"}), 409
    uid = str(uuid.uuid4())
    cur.execute("INSERT INTO users VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (uid, name, email, hash_pw(password), phone, None, utcnow()))
    db.commit()
    cur.execute("SELECT * FROM users WHERE id=%s", (uid,))
    user = dict(cur.fetchone())
    cur.close()
    return jsonify({"token": make_token(uid), "user": serialize_user(user, include_private=True)}), 201

@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json(force=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM users WHERE email=%s", (email,))
    user = cur.fetchone()
    cur.close()
    if not user or user["password_hash"] != hash_pw(password):
        return jsonify({"error": "Incorrect email or password"}), 401
    return jsonify({"token": make_token(user["id"]), "user": serialize_user(dict(user), include_private=True)})

@app.route("/api/auth/me", methods=["GET"])
@require_auth
def me():
    return jsonify({"user": serialize_user(g.current_user, include_private=True)})

# ── Users ─────────────────────────────────────────────────────────────────────
@app.route("/api/users/<uid>", methods=["GET"])
def get_user(uid):
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM users WHERE id=%s", (uid,))
    user = cur.fetchone()
    cur.close()
    if not user: return jsonify({"error": "Not found"}), 404
    return jsonify(serialize_user(dict(user)))

@app.route("/api/users/me", methods=["PATCH"])
@require_auth
def update_profile():
    data = request.get_json(force=True) or {}
    db = get_db()
    cur = db.cursor()
    uid = g.current_user["id"]
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    phone = (data.get("phone") or "").strip()
    avatar = data.get("avatar")
    if not name: return jsonify({"error": "Name required"}), 400
    if not email or "@" not in email: return jsonify({"error": "Valid email required"}), 400
    cur.execute("SELECT 1 FROM users WHERE email=%s AND id!=%s", (email, uid))
    if cur.fetchone():
        cur.close()
        return jsonify({"error": "Email already used by another account"}), 409
    if avatar is not None:
        cur.execute("UPDATE users SET name=%s,email=%s,phone=%s,avatar=%s WHERE id=%s",
                    (name, email, phone, avatar, uid))
    else:
        cur.execute("UPDATE users SET name=%s,email=%s,phone=%s WHERE id=%s",
                    (name, email, phone, uid))
    db.commit()
    cur.execute("SELECT * FROM users WHERE id=%s", (uid,))
    user = dict(cur.fetchone())
    cur.close()
    return jsonify({"user": serialize_user(user, include_private=True)})

# ── Shops ─────────────────────────────────────────────────────────────────────
@app.route("/api/shops", methods=["GET"])
def list_shops():
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM shops ORDER BY name")
    shops = cur.fetchall()
    cur.close()
    return jsonify([serialize_shop(dict(s)) for s in shops])

@app.route("/api/shops/mine", methods=["GET"])
@require_auth
def my_shop():
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT * FROM shops WHERE owner_id=%s", (g.current_user["id"],))
    shop = cur.fetchone()
    if not shop:
        cur.close()
        return jsonify({"shop": None})
    sub = get_sub(cur, g.current_user["id"])
    result = serialize_shop(dict(shop))
    result["subscription"] = sub
    cur.close()
    return jsonify({"shop": result})

@app.route("/api/shops", methods=["POST"])
@require_auth
def create_shop():
    data = request.get_json(force=True) or {}
    db = get_db()
    cur = db.cursor()
    uid = g.current_user["id"]
    cur.execute("SELECT 1 FROM shops WHERE owner_id=%s", (uid,))
    if cur.fetchone():
        cur.close()
        return jsonify({"error": "You already have a shop. Use PUT to update it."}), 409
    name = (data.get("name") or "").strip()
    location = (data.get("location") or "").strip()
    if not name: return jsonify({"error": "Shop name required"}), 400
    if not location: return jsonify({"error": "Location required"}), 400
    phone = (data.get("phone") or "").strip()
    whatsapp = (data.get("whatsapp") or "").strip()
    email = (data.get("email") or "").strip()
    if not phone and not whatsapp and not email:
        return jsonify({"error": "At least one contact method required"}), 400
    sid = str(uuid.uuid4())
    cur.execute("INSERT INTO shops VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (sid, uid, name, (data.get("desc") or "").strip(), "🏪",
                 location, phone, whatsapp, email, utcnow()))
    db.commit()
    cur.execute("SELECT * FROM shops WHERE id=%s", (sid,))
    shop = dict(cur.fetchone())
    cur.close()
    return jsonify({"shop": serialize_shop(shop)}), 201

@app.route("/api/shops/mine", methods=["PUT"])
@require_auth
def update_shop():
    data = request.get_json(force=True) or {}
    db = get_db()
    cur = db.cursor()
    uid = g.current_user["id"]
    cur.execute("SELECT * FROM shops WHERE owner_id=%s", (uid,))
    shop = cur.fetchone()
    if not shop:
        cur.close()
        return jsonify({"error": "No shop found"}), 404
    name = (data.get("name") or "").strip()
    location = (data.get("location") or "").strip()
    if not name: return jsonify({"error": "Shop name required"}), 400
    if not location: return jsonify({"error": "Location required"}), 400
    phone = (data.get("phone") or "").strip()
    whatsapp = (data.get("whatsapp") or "").strip()
    email = (data.get("email") or "").strip()
    if not phone and not whatsapp and not email:
        return jsonify({"error": "At least one contact method required"}), 400
    cur.execute("""UPDATE shops SET name=%s,description=%s,location=%s,phone=%s,whatsapp=%s,email=%s
                   WHERE owner_id=%s""",
                (name, (data.get("desc") or "").strip(), location, phone, whatsapp, email, uid))
    db.commit()
    cur.execute("SELECT * FROM shops WHERE owner_id=%s", (uid,))
    shop = dict(cur.fetchone())
    cur.close()
    return jsonify({"shop": serialize_shop(shop)})

# ── Subscriptions ─────────────────────────────────────────────────────────────
@app.route("/api/subscriptions/mine", methods=["GET"])
@require_auth
def my_sub():
    db = get_db()
    cur = db.cursor()
    sub = get_sub(cur, g.current_user["id"])
    cur.close()
    return jsonify({"subscription": sub})

@app.route("/api/subscriptions", methods=["POST"])
@require_auth
def activate_sub():
    data = request.get_json(force=True) or {}
    plan = data.get("plan")
    txn_id = (data.get("txnId") or "").strip()
    pay_method = data.get("payMethod")
    if plan not in SUB_PLANS: return jsonify({"error": "Invalid plan"}), 400
    if not txn_id or len(txn_id) < 5: return jsonify({"error": "Invalid transaction ID"}), 400
    db = get_db()
    cur = db.cursor()
    uid = g.current_user["id"]
    expiry = (datetime.utcnow() + timedelta(days=30)).isoformat() + "Z"
    cur.execute("""INSERT INTO subscriptions(user_id,plan,expiry,txn_id,pay_method,created_at)
                   VALUES(%s,%s,%s,%s,%s,%s)
                   ON CONFLICT(user_id) DO UPDATE SET
                   plan=EXCLUDED.plan, expiry=EXCLUDED.expiry,
                   txn_id=EXCLUDED.txn_id, pay_method=EXCLUDED.pay_method,
                   created_at=EXCLUDED.created_at""",
                (uid, plan, expiry, txn_id, pay_method, utcnow()))
    db.commit()
    cur.execute("SELECT * FROM subscriptions WHERE user_id=%s", (uid,))
    sub = dict(cur.fetchone())
    cur.close()
    return jsonify({"subscription": sub, "message": f"✅ Subscribed to {SUB_PLANS[plan]['label']}! Active for 30 days."})

# ── Ads ───────────────────────────────────────────────────────────────────────
@app.route("/api/ads", methods=["GET"])
@optional_auth
def list_ads():
    db = get_db()
    cur = db.cursor()
    cat = request.args.get("cat", "all")
    q = (request.args.get("q") or "").strip().lower()
    sort = request.args.get("sort", "new")

    cur.execute("SELECT * FROM ads ORDER BY created_at DESC")
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()

    result = [serialize_ad(db, r, include_images=True) for r in rows]

    if cat != "all":
        result = [a for a in result if a["cat"] == cat]

    if q:
        def matches(a):
            c = db.cursor()
            c.execute("SELECT name FROM shops WHERE id=%s", (a["shopId"],))
            shop = c.fetchone()
            c.close()
            shop_name = shop["name"].lower() if shop else ""
            return q in a["title"].lower() or q in (a["desc"] or "").lower() or q in shop_name
        result = [a for a in result if matches(a)]

    if sort == "low":
        result.sort(key=lambda a: a["price"])
    elif sort == "high":
        result.sort(key=lambda a: -a["price"])

    if g.current_user:
        c = db.cursor()
        c.execute("SELECT ad_id FROM favourites WHERE user_id=%s", (g.current_user["id"],))
        fav_ids = {r["ad_id"] for r in c.fetchall()}
        c.close()
        for a in result:
            a["faved"] = a["id"] in fav_ids

    return jsonify({"ads": result, "total": len(result)})

@app.route("/api/ads/mine", methods=["GET"])
@require_auth
def my_ads():
    db = get_db()
    cur = db.cursor()
    uid = g.current_user["id"]
    cur.execute("SELECT id FROM shops WHERE owner_id=%s", (uid,))
    shop = cur.fetchone()
    if not shop:
        cur.close()
        return jsonify({"ads": []})
    cur.execute("SELECT * FROM ads WHERE shop_id=%s ORDER BY created_at DESC", (shop["id"],))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    result = [serialize_ad(db, r) for r in rows]
    return jsonify({"ads": result})

@app.route("/api/ads", methods=["POST"])
@require_auth
def create_ad():
    data = request.get_json(force=True) or {}
    db = get_db()
    cur = db.cursor()
    uid = g.current_user["id"]
    sub = get_sub(cur, uid)
    if not sub:
        cur.close()
        return jsonify({"error": "Active subscription required to post ads"}), 403
    cur.execute("SELECT * FROM shops WHERE owner_id=%s", (uid,))
    shop = cur.fetchone()
    if not shop:
        cur.close()
        return jsonify({"error": "Create a shop first"}), 403
    plan_info = SUB_PLANS[sub["plan"]]
    cur.execute("SELECT COUNT(*) as c FROM ads WHERE shop_id=%s", (shop["id"],))
    ad_count = cur.fetchone()["c"]
    if plan_info["maxAds"] != float("inf") and ad_count >= plan_info["maxAds"]:
        cur.close()
        return jsonify({"error": f"Ad limit reached for your {plan_info['label']} plan"}), 403
    title = (data.get("title") or "").strip()
    if not title:
        cur.close()
        return jsonify({"error": "Title required"}), 400
    price = data.get("price")
    if price is None or float(price) <= 0:
        cur.close()
        return jsonify({"error": "Valid price required"}), 400
    images = data.get("images") or []
    max_imgs = plan_info["maxImages"]
    if max_imgs != float("inf"):
        images = images[:int(max_imgs)]
    aid = str(uuid.uuid4())
    cur.execute("INSERT INTO ads VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (aid, shop["id"], title, float(price),
                 (data.get("desc") or "").strip(),
                 data.get("cat") or "other", utcnow()))
    for i, img_data in enumerate(images):
        cur.execute("INSERT INTO ad_images VALUES (%s,%s,%s,%s)",
                    (str(uuid.uuid4()), aid, img_data, i))
    db.commit()
    cur.execute("SELECT * FROM ads WHERE id=%s", (aid,))
    ad = dict(cur.fetchone())
    cur.close()
    result = serialize_ad(db, ad)
    return jsonify({"ad": result}), 201

@app.route("/api/ads/<aid>", methods=["DELETE"])
@require_auth
def delete_ad(aid):
    db = get_db()
    cur = db.cursor()
    uid = g.current_user["id"]
    cur.execute("SELECT id FROM shops WHERE owner_id=%s", (uid,))
    shop = cur.fetchone()
    if not shop:
        cur.close()
        return jsonify({"error": "Not found"}), 404
    cur.execute("SELECT * FROM ads WHERE id=%s AND shop_id=%s", (aid, shop["id"]))
    ad = cur.fetchone()
    if not ad:
        cur.close()
        return jsonify({"error": "Ad not found or not yours"}), 404
    cur.execute("DELETE FROM ads WHERE id=%s", (aid,))
    db.commit()
    cur.close()
    return jsonify({"ok": True})

# ── Favourites ────────────────────────────────────────────────────────────────
@app.route("/api/favourites", methods=["GET"])
@require_auth
def list_favs():
    db = get_db()
    cur = db.cursor()
    uid = g.current_user["id"]
    cur.execute("""
        SELECT a.* FROM ads a
        JOIN favourites f ON f.ad_id = a.id
        WHERE f.user_id=%s
        ORDER BY f.created_at DESC
    """, (uid,))
    rows = [dict(r) for r in cur.fetchall()]
    cur.close()
    result = [serialize_ad(db, r) for r in rows]
    return jsonify({"ads": result})

@app.route("/api/favourites/<aid>", methods=["POST"])
@require_auth
def add_fav(aid):
    db = get_db()
    cur = db.cursor()
    uid = g.current_user["id"]
    cur.execute("SELECT 1 FROM ads WHERE id=%s", (aid,))
    if not cur.fetchone():
        cur.close()
        return jsonify({"error": "Ad not found"}), 404
    cur.execute("INSERT INTO favourites VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                (uid, aid, utcnow()))
    db.commit()
    cur.close()
    return jsonify({"ok": True})

@app.route("/api/favourites/<aid>", methods=["DELETE"])
@require_auth
def remove_fav(aid):
    db = get_db()
    cur = db.cursor()
    cur.execute("DELETE FROM favourites WHERE user_id=%s AND ad_id=%s",
                (g.current_user["id"], aid))
    db.commit()
    cur.close()
    return jsonify({"ok": True})

@app.route("/api/favourites/ids", methods=["GET"])
@require_auth
def fav_ids():
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT ad_id FROM favourites WHERE user_id=%s", (g.current_user["id"],))
    ids = [r["ad_id"] for r in cur.fetchall()]
    cur.close()
    return jsonify({"ids": ids})

# ── Messages ──────────────────────────────────────────────────────────────────
@app.route("/api/messages/conversations", methods=["GET"])
@require_auth
def conversations():
    db = get_db()
    cur = db.cursor()
    uid = g.current_user["id"]
    cur.execute("""
        SELECT DISTINCT
            CASE WHEN from_user=%s THEN to_user ELSE from_user END AS other_id
        FROM messages
        WHERE from_user=%s OR to_user=%s
    """, (uid, uid, uid))
    rows = cur.fetchall()
    cur.close()
    convs = []
    for row in rows:
        other_id = row["other_id"]
        c = db.cursor()
        c.execute("SELECT * FROM users WHERE id=%s", (other_id,))
        other = c.fetchone()
        if not other:
            c.close()
            continue
        c.execute("""
            SELECT * FROM messages
            WHERE (from_user=%s AND to_user=%s) OR (from_user=%s AND to_user=%s)
            ORDER BY created_at DESC LIMIT 1
        """, (uid, other_id, other_id, uid))
        last_msg = c.fetchone()
        c.execute("""
            SELECT COUNT(*) as c FROM messages
            WHERE from_user=%s AND to_user=%s AND read=0
        """, (other_id, uid))
        unread = c.fetchone()["c"]
        c.close()
        convs.append({
            "otherId": other_id,
            "otherName": other["name"],
            "otherAvatar": other["avatar"],
            "lastMsg": last_msg["text"] if last_msg else "",
            "lastTs": last_msg["created_at"] if last_msg else "",
            "unread": unread,
        })
    convs.sort(key=lambda c: c["lastTs"], reverse=True)
    return jsonify({"conversations": convs})

@app.route("/api/messages/<other_id>", methods=["GET"])
@require_auth
def get_messages(other_id):
    db = get_db()
    cur = db.cursor()
    uid = g.current_user["id"]
    cur.execute("""
        SELECT * FROM messages
        WHERE (from_user=%s AND to_user=%s) OR (from_user=%s AND to_user=%s)
        ORDER BY created_at ASC
    """, (uid, other_id, other_id, uid))
    msgs = cur.fetchall()
    cur.execute("""
        UPDATE messages SET read=1
        WHERE from_user=%s AND to_user=%s AND read=0
    """, (other_id, uid))
    db.commit()
    cur.close()
    return jsonify({"messages": [serialize_msg(dict(m)) for m in msgs]})

@app.route("/api/messages/<other_id>", methods=["POST"])
@require_auth
def send_message(other_id):
    data = request.get_json(force=True) or {}
    text = (data.get("text") or "").strip()
    if not text: return jsonify({"error": "Message text required"}), 400
    db = get_db()
    cur = db.cursor()
    uid = g.current_user["id"]
    cur.execute("SELECT 1 FROM users WHERE id=%s", (other_id,))
    if not cur.fetchone():
        cur.close()
        return jsonify({"error": "Recipient not found"}), 404
    mid = str(uuid.uuid4())
    cur.execute("INSERT INTO messages VALUES (%s,%s,%s,%s,%s,%s)",
                (mid, uid, other_id, text, 0, utcnow()))
    db.commit()
    cur.execute("SELECT * FROM messages WHERE id=%s", (mid,))
    msg = dict(cur.fetchone())
    cur.close()
    return jsonify({"message": serialize_msg(msg)}), 201

@app.route("/api/messages/unread-count", methods=["GET"])
@require_auth
def unread_count():
    db = get_db()
    cur = db.cursor()
    cur.execute(
        "SELECT COUNT(*) as c FROM messages WHERE to_user=%s AND read=0",
        (g.current_user["id"],)
    )
    count = cur.fetchone()["c"]
    cur.close()
    return jsonify({"count": count})

# ── Serve frontend ────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")

@app.route("/<path:path>")
def static_files(path):
    try:
        return send_from_directory(STATIC_DIR, path)
    except Exception:
        return send_from_directory(STATIC_DIR, "index.html")

# ── Main ──────────────────────────────────────────────────────────────────────
os.makedirs(STATIC_DIR, exist_ok=True)
init_db()

if __name__ == "__main__":
    print("🚀 Arua MarketHub backend running on http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, debug=False)
