-- Game Compare DB Schema v2.0
-- Refleja el estado actual tras la consolidación del pipeline.
-- Última actualización: 2026-07-27

CREATE TABLE IF NOT EXISTS stores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,        -- 'xbox_argentina', 'steam_argentina'
    currency TEXT NOT NULL,           -- 'ARS', 'USD'
    base_url TEXT NOT NULL
);

INSERT OR IGNORE INTO stores (name, currency, base_url) VALUES
    ('xbox_argentina', 'ARS', 'https://www.xbox.com/es-ar/games/all-games/console'),
    ('steam_argentina', 'USD', 'https://store.steampowered.com/search/?cc=ar&l=spanish');

CREATE TABLE IF NOT EXISTS games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    store_id INTEGER NOT NULL,
    store_game_id TEXT NOT NULL,       -- Xbox product ID or Steam app ID
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    cover_url TEXT,
    platforms TEXT,                    -- 'Xbox One, Xbox Series X|S'
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(store_id, store_game_id),
    FOREIGN KEY (store_id) REFERENCES stores(id)
);

CREATE TABLE IF NOT EXISTS prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL,
    price REAL NOT NULL,
    original_price REAL,
    discount_percent INTEGER,
    is_game_pass BOOLEAN DEFAULT 0,
    is_free BOOLEAN DEFAULT 0,
    scraped_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    price_verified BOOLEAN DEFAULT 0,
    verified_at TIMESTAMP,
    verified_source TEXT,              -- 'steam_api', 'display_catalog', 'steam_api_definitive', 'display_catalog_definitive'
    FOREIGN KEY (game_id) REFERENCES games(id)
);

CREATE TABLE IF NOT EXISTS scrape_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    store_id INTEGER NOT NULL,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP,
    games_found INTEGER DEFAULT 0,
    games_new INTEGER DEFAULT 0,
    status TEXT DEFAULT 'running',     -- 'running', 'completed', 'failed'
    error_message TEXT,
    FOREIGN KEY (store_id) REFERENCES stores(id)
);

-- ── Pipeline core tables ──────────────────────────────────────────

CREATE TABLE IF NOT EXISTS steam_queue (
    steam_app_id TEXT PRIMARY KEY,
    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    processed_at TIMESTAMP,
    status TEXT DEFAULT 'pending'      -- 'pending', 'done', 'no_xbox_match', 'api_error'
);

CREATE TABLE IF NOT EXISTS pipeline_checkpoint (
    id INTEGER PRIMARY KEY DEFAULT 1,
    last_steam_app_id TEXT,
    processed_count INTEGER DEFAULT 0,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- ── Cross-store matches (main comparison table) ───────────────────

CREATE TABLE IF NOT EXISTS igdb_steam_to_xbox (
    steam_game_id INTEGER,
    steam_app_id TEXT NOT NULL,
    igdb_game_id INTEGER,
    xbox_store_id TEXT,
    xbox_title TEXT,
    xbox_price_ars REAL,
    xbox_msrp_ars REAL,
    xbox_wholesale_ars REAL,
    xbox_currency TEXT DEFAULT 'ARS',
    xbox_is_free BOOLEAN DEFAULT 0,
    xbox_is_game_pass BOOLEAN DEFAULT 0,
    matched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    steam_price_usd REAL,
    steam_original_usd REAL,
    steam_discount_pct INTEGER DEFAULT 0,
    steam_is_free INTEGER DEFAULT 0,
    source TEXT DEFAULT 'legacy',
    platforms TEXT,
    xbox_playable_on TEXT,
    PRIMARY KEY (steam_game_id, steam_app_id),
    FOREIGN KEY (steam_game_id) REFERENCES games(id)
);

-- ── Indexes ───────────────────────────────────────────────────────

CREATE INDEX IF NOT EXISTS idx_prices_game_scraped ON prices(game_id, scraped_at);
CREATE INDEX IF NOT EXISTS idx_prices_scraped ON prices(scraped_at);
CREATE INDEX IF NOT EXISTS idx_prices_verified ON prices(price_verified);
CREATE INDEX IF NOT EXISTS idx_games_store ON games(store_id);
CREATE INDEX IF NOT EXISTS idx_games_title ON games(title);
CREATE INDEX IF NOT EXISTS idx_steam_to_xbox_igdb ON igdb_steam_to_xbox(igdb_game_id);
CREATE INDEX IF NOT EXISTS idx_steam_to_xbox_source ON igdb_steam_to_xbox(source);
CREATE INDEX IF NOT EXISTS idx_steam_queue_status ON steam_queue(status);
