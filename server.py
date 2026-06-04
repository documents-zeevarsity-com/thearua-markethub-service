"""
Arua MarketHub — Full Backend Server
Flask + SQLite, JWT-style tokens via HMAC-SHA256, base64 image storage
"""

import sqlite3, hashlib, hmac, json, uuid, base64, os, time
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, request, jsonify, send_from_directory, g

# ── Config ──────────────────────────────────────────────────────────────────
SECRET = os.environ.get("AMH_SECRET", "arua-markethub-secret-2026-change-in-prod")
DB_PATH = os.environ.get("DB_PATH", "/tmp/markethub.db")
STATIC_DIR = os.path.join(os.path.dirname(__file__), "public")

app = Flask(__name__, static_folder=STATIC_DIR, static_url_path="")

# ── Database ──────────────────────────────────────────────────────────────────
def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH, check_same_thread=False)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop("db", None)
    if db: db.close()

def init_db():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.executescript("""
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
        plan TEXT NOT NULL CHECK(plan IN ('basic','premium','premiumplus')),
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
    CREATE INDEX IF NOT EXISTS idx_ads_shop ON ads(shop_id);
    CREATE INDEX IF NOT EXISTS idx_msgs_from ON messages(from_user);
    CREATE INDEX IF NOT EXISTS idx_msgs_to ON messages(to_user);
    CREATE INDEX IF NOT EXISTS idx_favs_user ON favourites(user_id);
    """)
    db.commit()
    if not db.execute("SELECT 1 FROM users LIMIT 1").fetchone():
        seed_demo(db)
    db.close()

def seed_demo(db):
    now = utcnow()
    expiry = (datetime.utcnow() + timedelta(days=30)).isoformat() + "Z"
    u1, u2 = str(uuid.uuid4()), str(uuid.uuid4())
    sh1, sh2 = str(uuid.uuid4()), str(uuid.uuid4())
    db.execute("INSERT INTO users VALUES (?,?,?,?,?,?,?)",
               (u1, "Alex Seller", "alex@shop.com", hash_pw("1234"), "+256 700 123456", None, now))
    db.execute("INSERT INTO users VALUES (?,?,?,?,?,?,?)",
               (u2, "Beatrice Nakato", "bea@market.com", hash_pw("1234"), "+256 701 654321", None, now))
    db.execute("INSERT INTO shops VALUES (?,?,?,?,?,?,?,?,?,?)",
               (sh1, u1, "Urban Collective", "Trendy accessories & clothing", "🏪",
                "Arua City, Avenue Road, Shop 4A", "+256 700 123456",
                "https://wa.me/256700123456", "alex@shop.com", now))
    db.execute("INSERT INTO shops VALUES (?,?,?,?,?,?,?,?,?,?)",
               (sh2, u2, "Tech Vault", "Gadgets & electronics", "🏪",
                "Arua City, Weatherhead Park, Ground Floor", "+256 701 654321",
                "https://wa.me/256701654321", "bea@market.com", now))
    db.execute("INSERT INTO subscriptions VALUES (?,?,?,?,?,?)",
               (u1, "premium", expiry, "DEMO-TXN-001", "mtn", now))
    db.execute("INSERT INTO subscriptions VALUES (?,?,?,?,?,?)",
               (u2, "premiumplus", expiry, "DEMO-TXN-002", "airtel", now))
    demo_ads = [
        (sh1, "Vintage Denim Jacket", 280000, "Classic blue, size M — great condition", "fashion", "2026-05-20T10:00:00Z"),
        (sh1, "Leather Crossbody Bag", 195000, "Genuine leather, tan colour", "fashion", "2026-05-21T08:00:00Z"),
        (sh2, "Wireless Earbuds Pro", 165000, "Active noise cancellation, 30hr battery", "electronics", "2026-05-21T12:00:00Z"),
        (sh2, "Portable Power Bank", 98000, "20,000mAh fast charging", "electronics", "2026-05-22T06:00:00Z"),
        (sh1, "Handmade Ceramic Mug", 65000, "Artisan crafted, 350ml", "art", "2026-05-19T09:00:00Z"),
        (sh2, "Yoga Mat Premium", 125000, "Non-slip, 6mm thick, eco-friendly", "sports", "2026-05-18T15:00:00Z"),
    ]
    for shop_id, title, price, desc, cat, created in demo_ads:
        aid = str(uuid.uuid4())
        db.execute("INSERT INTO ads VALUES (?,?,?,?,?,?,?)", (aid, shop_id, title, price, desc, cat, created))
    db.commit()

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
        user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
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
            user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
            if user:
                g.current_user = dict(user)
        return f(*args, **kwargs)
    return wrapper

def get_sub(db, user_id):
    row = db.execute(
        "SELECT * FROM subscriptions WHERE user_id=? AND expiry > ?",
        (user_id, utcnow())
    ).fetchone()
    return dict(row) if row else None

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

def serialize_ad(db, ad, include_images=True):
    d = {
        "id": ad["id"], "shopId": ad["shop_id"], "title": ad["title"],
        "price": ad["price"], "desc": ad["description"],
        "cat": ad["category"], "createdAt": ad["created_at"],
    }
    if include_images:
        imgs = db.execute(
            "SELECT data FROM ad_images WHERE ad_id=? ORDER BY sort_order", (ad["id"],)
        ).fetchall()
        d["images"] = [r["data"] for r in imgs]
    return d

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
    if db.execute("SELECT 1 FROM users WHERE email=?", (email,)).fetchone():
        return jsonify({"error": "Email already registered"}), 409
    uid = str(uuid.uuid4())
    db.execute("INSERT INTO users VALUES (?,?,?,?,?,?,?)",
               (uid, name, email, hash_pw(password), phone, None, utcnow()))
    db.commit()
    user = dict(db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())
    return jsonify({"token": make_token(uid), "user": serialize_user(user, include_private=True)}), 201

@app.route("/api/auth/login", methods=["POST"])
def login():
    data = request.get_json(force=True) or {}
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    db = get_db()
    user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
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
    user = db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not user: return jsonify({"error": "Not found"}), 404
    return jsonify(serialize_user(dict(user)))

@app.route("/api/users/me", methods=["PATCH"])
@require_auth
def update_profile():
    data = request.get_json(force=True) or {}
    db = get_db()
    uid = g.current_user["id"]
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    phone = (data.get("phone") or "").strip()
    avatar = data.get("avatar")
    if not name: return jsonify({"error": "Name required"}), 400
    if not email or "@" not in email: return jsonify({"error": "Valid email required"}), 400
    if db.execute("SELECT 1 FROM users WHERE email=? AND id!=?", (email, uid)).fetchone():
        return jsonify({"error": "Email already used by another account"}), 409
    if avatar is not None:
        db.execute("UPDATE users SET name=?,email=?,phone=?,avatar=? WHERE id=?",
                   (name, email, phone, avatar, uid))
    else:
        db.execute("UPDATE users SET name=?,email=?,phone=? WHERE id=?",
                   (name, email, phone, uid))
    db.commit()
    user = dict(db.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())
    return jsonify({"user": serialize_user(user, include_private=True)})

# ── Shops ─────────────────────────────────────────────────────────────────────
@app.route("/api/shops", methods=["GET"])
def list_shops():
    db = get_db()
    shops = db.execute("SELECT * FROM shops ORDER BY name").fetchall()
    return jsonify([serialize_shop(dict(s)) for s in shops])

@app.route("/api/shops/mine", methods=["GET"])
@require_auth
def my_shop():
    db = get_db()
    shop = db.execute("SELECT * FROM shops WHERE owner_id=?", (g.current_user["id"],)).fetchone()
    if not shop: return jsonify({"shop": None})
    sub = get_sub(db, g.current_user["id"])
    result = serialize_shop(dict(shop))
    result["subscription"] = dict(sub) if sub else None
    return jsonify({"shop": result})

@app.route("/api/shops", methods=["POST"])
@require_auth
def create_shop():
    data = request.get_json(force=True) or {}
    db = get_db()
    uid = g.current_user["id"]
    if db.execute("SELECT 1 FROM shops WHERE owner_id=?", (uid,)).fetchone():
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
    db.execute("INSERT INTO shops VALUES (?,?,?,?,?,?,?,?,?,?)",
               (sid, uid, name, (data.get("desc") or "").strip(), "🏪",
                location, phone, whatsapp, email, utcnow()))
    db.commit()
    shop = dict(db.execute("SELECT * FROM shops WHERE id=?", (sid,)).fetchone())
    return jsonify({"shop": serialize_shop(shop)}), 201

@app.route("/api/shops/mine", methods=["PUT"])
@require_auth
def update_shop():
    data = request.get_json(force=True) or {}
    db = get_db()
    uid = g.current_user["id"]
    shop = db.execute("SELECT * FROM shops WHERE owner_id=?", (uid,)).fetchone()
    if not shop: return jsonify({"error": "No shop found"}), 404
    name = (data.get("name") or "").strip()
    location = (data.get("location") or "").strip()
    if not name: return jsonify({"error": "Shop name required"}), 400
    if not location: return jsonify({"error": "Location required"}), 400
    phone = (data.get("phone") or "").strip()
    whatsapp = (data.get("whatsapp") or "").strip()
    email = (data.get("email") or "").strip()
    if not phone and not whatsapp and not email:
        return jsonify({"error": "At least one contact method required"}), 400
    db.execute("""UPDATE shops SET name=?,description=?,location=?,phone=?,whatsapp=?,email=?
                  WHERE owner_id=?""",
               (name, (data.get("desc") or "").strip(), location, phone, whatsapp, email, uid))
    db.commit()
    shop = dict(db.execute("SELECT * FROM shops WHERE owner_id=?", (uid,)).fetchone())
    return jsonify({"shop": serialize_shop(shop)})

# ── Subscriptions ─────────────────────────────────────────────────────────────
@app.route("/api/subscriptions/mine", methods=["GET"])
@require_auth
def my_sub():
    db = get_db()
    sub = get_sub(db, g.current_user["id"])
    return jsonify({"subscription": dict(sub) if sub else None})

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
    uid = g.current_user["id"]
    expiry = (datetime.utcnow() + timedelta(days=30)).isoformat() + "Z"
    db.execute("""INSERT INTO subscriptions(user_id,plan,expiry,txn_id,pay_method,created_at)
                  VALUES(?,?,?,?,?,?)
                  ON CONFLICT(user_id) DO UPDATE SET
                  plan=excluded.plan, expiry=excluded.expiry,
                  txn_id=excluded.txn_id, pay_method=excluded.pay_method,
                  created_at=excluded.created_at""",
               (uid, plan, expiry, txn_id, pay_method, utcnow()))
    db.commit()
    sub = dict(db.execute("SELECT * FROM subscriptions WHERE user_id=?", (uid,)).fetchone())
    return jsonify({"subscription": sub, "message": f"✅ Subscribed to {SUB_PLANS[plan]['label']}! Active for 30 days."})

# ── Ads ───────────────────────────────────────────────────────────────────────
@app.route("/api/ads", methods=["GET"])
@optional_auth
def list_ads():
    db = get_db()
    cat = request.args.get("cat", "all")
    q = (request.args.get("q") or "").strip().lower()
    sort = request.args.get("sort", "new")

    rows = db.execute("""
        SELECT a.* FROM ads a
        JOIN shops s ON s.id = a.shop_id
        ORDER BY a.created_at DESC
    """).fetchall()

    result = [serialize_ad(db, dict(r), include_images=True) for r in rows]

    shop_boost = {}
    for ad in result:
        if ad["shopId"] not in shop_boost:
            shop_boost[ad["shopId"]] = 0

    if cat != "all":
        result = [a for a in result if a["cat"] == cat]
    if q:
        def matches(a):
            shop = db.execute("SELECT name FROM shops WHERE id=?", (a["shopId"],)).fetchone()
            shop_name = shop["name"].lower() if shop else ""
            return q in a["title"].lower() or q in (a["desc"] or "").lower() or q in shop_name
        result = [a for a in result if matches(a)]

    def sort_key(a):
        boost = shop_boost.get(a["shopId"], 0)
        if sort == "low": secondary = a["price"]
        elif sort == "high": secondary = -a["price"]
        else: secondary = 0
        return (-boost, secondary)
    if sort in ("low", "high"):
        result.sort(key=sort_key)
    else:
        result.sort(key=lambda a: -shop_boost.get(a["shopId"], 0))

    if g.current_user:
        fav_ids = {r["ad_id"] for r in db.execute(
            "SELECT ad_id FROM favourites WHERE user_id=?", (g.current_user["id"],)).fetchall()}
        for a in result:
            a["faved"] = a["id"] in fav_ids

    return jsonify({"ads": result, "total": len(result)})

@app.route("/api/ads/mine", methods=["GET"])
@require_auth
def my_ads():
    db = get_db()
    uid = g.current_user["id"]
    shop = db.execute("SELECT id FROM shops WHERE owner_id=?", (uid,)).fetchone()
    if not shop: return jsonify({"ads": []})
    rows = db.execute("SELECT * FROM ads WHERE shop_id=? ORDER BY created_at DESC", (shop["id"],)).fetchall()
    return jsonify({"ads": [serialize_ad(db, dict(r)) for r in rows]})

@app.route("/api/ads", methods=["POST"])
@require_auth
def create_ad():
    data = request.get_json(force=True) or {}
    db = get_db()
    uid = g.current_user["id"]
    sub = get_sub(db, uid)
    if not sub: return jsonify({"error": "Active subscription required to post ads"}), 403
    shop = db.execute("SELECT * FROM shops WHERE owner_id=?", (uid,)).fetchone()
    if not shop: return jsonify({"error": "Create a shop first"}), 403
    plan_info = SUB_PLANS[sub["plan"]]
    ad_count = db.execute("SELECT COUNT(*) as c FROM ads WHERE shop_id=?", (shop["id"],)).fetchone()["c"]
    if plan_info["maxAds"] != float("inf") and ad_count >= plan_info["maxAds"]:
        return jsonify({"error": f"Ad limit reached for your {plan_info['label']} plan"}), 403
    title = (data.get("title") or "").strip()
    if not title: return jsonify({"error": "Title required"}), 400
    price = data.get("price")
    if price is None or float(price) <= 0: return jsonify({"error": "Valid price required"}), 400
    images = data.get("images") or []
    max_imgs = plan_info["maxImages"]
    if max_imgs != float("inf"):
        images = images[:int(max_imgs)]
    aid = str(uuid.uuid4())
    db.execute("INSERT INTO ads VALUES (?,?,?,?,?,?,?)",
               (aid, shop["id"], title, float(price),
                (data.get("desc") or "").strip(),
                data.get("cat") or "other", utcnow()))
    for i, img_data in enumerate(images):
        db.execute("INSERT INTO ad_images VALUES (?,?,?,?)",
                   (str(uuid.uuid4()), aid, img_data, i))
    db.commit()
    ad = dict(db.execute("SELECT * FROM ads WHERE id=?", (aid,)).fetchone())
    return jsonify({"ad": serialize_ad(db, ad)}), 201

@app.route("/api/ads/<aid>", methods=["DELETE"])
@require_auth
def delete_ad(aid):
    db = get_db()
    uid = g.current_user["id"]
    shop = db.execute("SELECT id FROM shops WHERE owner_id=?", (uid,)).fetchone()
    if not shop: return jsonify({"error": "Not found"}), 404
    ad = db.execute("SELECT * FROM ads WHERE id=? AND shop_id=?", (aid, shop["id"])).fetchone()
    if not ad: return jsonify({"error": "Ad not found or not yours"}), 404
    db.execute("DELETE FROM ads WHERE id=?", (aid,))
    db.commit()
    return jsonify({"ok": True})

# ── Favourites ────────────────────────────────────────────────────────────────
@app.route("/api/favourites", methods=["GET"])
@require_auth
def list_favs():
    db = get_db()
    uid = g.current_user["id"]
    rows = db.execute("""
        SELECT a.* FROM ads a
        JOIN favourites f ON f.ad_id = a.id
        WHERE f.user_id=?
        ORDER BY f.created_at DESC
    """, (uid,)).fetchall()
    return jsonify({"ads": [serialize_ad(db, dict(r)) for r in rows]})

@app.route("/api/favourites/<aid>", methods=["POST"])
@require_auth
def add_fav(aid):
    db = get_db()
    uid = g.current_user["id"]
    if not db.execute("SELECT 1 FROM ads WHERE id=?", (aid,)).fetchone():
        return jsonify({"error": "Ad not found"}), 404
    db.execute("INSERT OR IGNORE INTO favourites VALUES (?,?,?)", (uid, aid, utcnow()))
    db.commit()
    return jsonify({"ok": True})

@app.route("/api/favourites/<aid>", methods=["DELETE"])
@require_auth
def remove_fav(aid):
    db = get_db()
    db.execute("DELETE FROM favourites WHERE user_id=? AND ad_id=?", (g.current_user["id"], aid))
    db.commit()
    return jsonify({"ok": True})

@app.route("/api/favourites/ids", methods=["GET"])
@require_auth
def fav_ids():
    db = get_db()
    rows = db.execute("SELECT ad_id FROM favourites WHERE user_id=?", (g.current_user["id"],)).fetchall()
    return jsonify({"ids": [r["ad_id"] for r in rows]})

# ── Messages ──────────────────────────────────────────────────────────────────
@app.route("/api/messages/conversations", methods=["GET"])
@require_auth
def conversations():
    db = get_db()
    uid = g.current_user["id"]
    rows = db.execute("""
        SELECT DISTINCT
            CASE WHEN from_user=? THEN to_user ELSE from_user END AS other_id
        FROM messages
        WHERE from_user=? OR to_user=?
    """, (uid, uid, uid)).fetchall()
    convs = []
    for row in rows:
        other_id = row["other_id"]
        other = db.execute("SELECT * FROM users WHERE id=?", (other_id,)).fetchone()
        if not other: continue
        last_msg = db.execute("""
            SELECT * FROM messages
            WHERE (from_user=? AND to_user=?) OR (from_user=? AND to_user=?)
            ORDER BY created_at DESC LIMIT 1
        """, (uid, other_id, other_id, uid)).fetchone()
        unread = db.execute("""
            SELECT COUNT(*) as c FROM messages
            WHERE from_user=? AND to_user=? AND read=0
        """, (other_id, uid)).fetchone()["c"]
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
    uid = g.current_user["id"]
    msgs = db.execute("""
        SELECT * FROM messages
        WHERE (from_user=? AND to_user=?) OR (from_user=? AND to_user=?)
        ORDER BY created_at ASC
    """, (uid, other_id, other_id, uid)).fetchall()
    db.execute("""
        UPDATE messages SET read=1
        WHERE from_user=? AND to_user=? AND read=0
    """, (other_id, uid))
    db.commit()
    return jsonify({"messages": [serialize_msg(dict(m)) for m in msgs]})

@app.route("/api/messages/<other_id>", methods=["POST"])
@require_auth
def send_message(other_id):
    data = request.get_json(force=True) or {}
    text = (data.get("text") or "").strip()
    if not text: return jsonify({"error": "Message text required"}), 400
    db = get_db()
    uid = g.current_user["id"]
    if not db.execute("SELECT 1 FROM users WHERE id=?", (other_id,)).fetchone():
        return jsonify({"error": "Recipient not found"}), 404
    mid = str(uuid.uuid4())
    db.execute("INSERT INTO messages VALUES (?,?,?,?,?,?)",
               (mid, uid, other_id, text, 0, utcnow()))
    db.commit()
    msg = dict(db.execute("SELECT * FROM messages WHERE id=?", (mid,)).fetchone())
    return jsonify({"message": serialize_msg(msg)}), 201

@app.route("/api/messages/unread-count", methods=["GET"])
@require_auth
def unread_count():
    db = get_db()
    count = db.execute(
        "SELECT COUNT(*) as c FROM messages WHERE to_user=? AND read=0",
        (g.current_user["id"],)
    ).fetchone()["c"]
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
