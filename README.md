# Arua MarketHub — Backend

A complete Flask + SQLite backend for the Arua MarketHub marketplace.

## Quick Start

### Requirements
- Python 3.8+
- `flask` (install with `pip install flask`)

### Run
```bash
python3 server.py
# → http://localhost:5000
```

Then open **http://localhost:5000** in your browser.

---

## Architecture

```
arua-markethub/
├── server.py          ← Flask backend (all API routes)
├── markethub.db       ← SQLite database (auto-created on first run)
├── public/
│   ├── index.html     ← Original frontend (unchanged)
│   └── api.js         ← API client layer (replaces localStorage)
└── start.sh           ← Convenience start script
```

## How It Works

The original `index.html` was a fully self-contained client-only app that stored all data in `localStorage`. The backend replaces the data layer:

1. **`server.py`** — Flask server with SQLite database. Provides a full REST API.
2. **`api.js`** — Injected into the frontend. Overrides `load()`, `save()`, and all mutation functions to make real API calls instead of touching `localStorage`.

The frontend HTML/CSS/UI logic is **100% unchanged** — only the data layer is swapped.

---

## API Endpoints

### Auth
| Method | Path | Description |
|--------|------|-------------|
| POST | `/api/auth/signup` | Register new account |
| POST | `/api/auth/login` | Sign in, returns JWT token |
| GET  | `/api/auth/me` | Get current user (auth required) |

### Users
| Method | Path | Description |
|--------|------|-------------|
| GET  | `/api/users/:id` | Get public user profile |
| PATCH | `/api/users/me` | Update own profile + avatar |

### Shops
| Method | Path | Description |
|--------|------|-------------|
| GET  | `/api/shops` | List all shops |
| GET  | `/api/shops/mine` | Get own shop + subscription |
| POST | `/api/shops` | Create shop (auth required) |
| PUT  | `/api/shops/mine` | Update own shop |

### Subscriptions
| Method | Path | Description |
|--------|------|-------------|
| GET  | `/api/subscriptions/mine` | Get own subscription status |
| POST | `/api/subscriptions` | Activate/renew subscription |

### Ads
| Method | Path | Description |
|--------|------|-------------|
| GET  | `/api/ads` | List marketplace ads (with filters) |
| GET  | `/api/ads/mine` | Get own shop's ads |
| POST | `/api/ads` | Post new ad with images |
| DELETE | `/api/ads/:id` | Delete own ad |

**Query params for GET /api/ads:** `?cat=fashion&q=jacket&sort=new|low|high`

### Favourites
| Method | Path | Description |
|--------|------|-------------|
| GET  | `/api/favourites` | Get saved ads |
| GET  | `/api/favourites/ids` | Get saved ad IDs |
| POST | `/api/favourites/:adId` | Save ad |
| DELETE | `/api/favourites/:adId` | Unsave ad |

### Messages
| Method | Path | Description |
|--------|------|-------------|
| GET  | `/api/messages/conversations` | List all conversations |
| GET  | `/api/messages/:userId` | Get messages with a user (marks as read) |
| POST | `/api/messages/:userId` | Send a message |
| GET  | `/api/messages/unread-count` | Total unread count |

---

## Demo Accounts

The database is seeded with two demo users on first run:

| Email | Password | Shop | Plan |
|-------|----------|------|------|
| alex@shop.com | 1234 | Urban Collective | Premium |
| bea@market.com | 1234 | Tech Vault | Premium Plus |

---

## Subscription Plans

| Plan | Price | Max Ads | Max Photos | Boost |
|------|-------|---------|------------|-------|
| Basic | UGX 15,000/mo | 10 | 5 | None |
| Premium | UGX 35,000/mo | 30 | 12 | ✦ Featured |
| Premium Plus | UGX 105,000/mo | Unlimited | Unlimited | ⭐ Top Shop |

---

## Production Notes

- Change `SECRET` in `server.py` (or set `AMH_SECRET` env var)
- Images stored as base64 in SQLite — for scale, move to object storage (S3/Cloudinary)
- Add HTTPS via nginx reverse proxy
- Transaction IDs are accepted on trust — integrate real MTN/Airtel MoMo API for production
