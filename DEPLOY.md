# Deploying PaidUp + PaidUp Intelligence to a VPS

This runs **both** apps on a single VPS with Docker Compose: the public PaidUp
donor-card app, the `/ask` intelligence agent, two Postgres instances, Redis,
and (optionally) a Caddy reverse proxy for automatic HTTPS.

The stack is host-agnostic — nothing here is tied to Railway. Start with plain
IP access, add a domain and TLS whenever you're ready.

```
                 ┌───────── Caddy (tls profile) ─────────┐
   :80/:443 ───▶ │  paidup.example.com → paidup:5002     │
                 │  ask.example.com    → …intelligence:5003
                 └───────────────────────────────────────┘
   :5002 ───────▶ paidup ───────────────┐
   :5003 ───────▶ paidup-intelligence ──┤
                                         ├─▶ paidup-db (postgres:16)
                                         ├─▶ intelligence-db (pgvector)
                                         └─▶ redis
```

Two separate Postgres instances are deliberate — mixing OLTP with bulk vector
writes filled the disk once before (see `docs/engineering-maturity.md`).

---

## 1. Provision the VPS

Any provider works (Hetzner, DigitalOcean, Linode, …). Suggested minimum:
**2 vCPU / 4 GB RAM / 40 GB disk**, Ubuntu 22.04+. The vector tables and index
builds are the memory-hungry part.

Install Docker Engine + the Compose plugin:

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"   # log out/in so this takes effect
docker compose version            # verify the plugin is present
```

## 2. Clone both repos as siblings

The deploy compose builds both apps from sibling directories, so the layout
matters:

```bash
cd ~
git clone https://github.com/mahsa7haft/paidup.git
git clone https://github.com/mahsa7haft/paidup-intelligence.git
```

You should now have `~/paidup` and `~/paidup-intelligence` next to each other.

## 3. Configure

```bash
cd ~/paidup-intelligence/deploy
cp .env.example .env
nano .env        # set DB passwords + API keys (see comments in the file)
```

At minimum set `PAIDUP_DB_PASSWORD`, `INTELLIGENCE_DB_PASSWORD`,
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and `FLASK_SECRET_KEY`.

## 4. Bring it up (IP-only, HTTP)

```bash
cd ~/paidup-intelligence/deploy
docker compose up -d --build
docker compose ps
```

Verify:

```bash
curl http://localhost:5002/health   # PaidUp
curl http://localhost:5003/health   # Intelligence
```

From your laptop, `http://SERVER_IP:5002` and `http://SERVER_IP:5003` should now
respond. (Open those ports — see the firewall step.)

## 5. Load the intelligence data

The vector tables start empty. Run the one-shot ingestion (costs OpenAI
embedding spend; smart re-embed keeps re-runs near zero):

```bash
docker compose --profile ingest run --rm ingest
```

Then **build the IVFFlat indexes**. They're left commented out in `schema.sql`
on purpose — IVFFlat needs real data to learn its centroids, so you create them
*after* the first load, not at schema init (see issue #15 / ADR 003):

```bash
docker compose exec intelligence-db psql -U intelligence -d intelligence <<'SQL'
CREATE INDEX IF NOT EXISTS idx_interests_embedding_ivfflat
  ON interests_vectors USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX IF NOT EXISTS idx_party_donations_embedding_ivfflat
  ON party_donations_vectors USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);
CREATE INDEX IF NOT EXISTS idx_votes_embedding_ivfflat
  ON votes_vectors USING ivfflat (embedding vector_cosine_ops) WITH (lists = 200);
SQL
```

Re-run this only after a *large* data change — day-to-day ingests reuse the
existing indexes.

PaidUp manages its own tables on first boot; no seed step is needed for it.

## 6. Add a domain + HTTPS (optional, do this any time)

1. Point two DNS **A records** at the server's IP, e.g. `paidup.example.com` and
   `ask.example.com`.
2. Put them in `deploy/.env`:
   ```
   PAIDUP_DOMAIN=paidup.example.com
   INTELLIGENCE_DOMAIN=ask.example.com
   ```
3. Start the proxy:
   ```bash
   docker compose --profile tls up -d
   ```

Caddy fetches and auto-renews Let's Encrypt certificates. Once TLS is live,
close the direct app ports (below) so traffic only enters through 443.

## 7. Firewall

```bash
sudo ufw allow 22
sudo ufw allow 80
sudo ufw allow 443
# IP-only phase only — remove these once Caddy/TLS fronts the apps:
sudo ufw allow 5002
sudo ufw allow 5003
sudo ufw enable
```

To stop exposing the raw app ports after enabling TLS, either drop the two
`ufw allow` rules above, or bind the published ports to localhost by changing
`"5002:5002"` → `"127.0.0.1:5002:5002"` in `deploy/docker-compose.yml`.

## 8. Backups

Dump both databases (schedule via cron):

```bash
docker compose exec -T paidup-db \
  pg_dump -U paidup paidup | gzip > paidup-$(date +%F).sql.gz
docker compose exec -T intelligence-db \
  pg_dump -U intelligence intelligence | gzip > intelligence-$(date +%F).sql.gz
```

## 9. Updates

```bash
cd ~/paidup && git pull
cd ~/paidup-intelligence && git pull
cd deploy && docker compose up -d --build
```

## 10. Operations

- **Logs:** `docker compose logs -f paidup` / `... paidup-intelligence`
- **Restart on reboot:** services use `restart: unless-stopped`; ensure Docker
  starts at boot with `sudo systemctl enable docker`.
- **Disk:** watch both Postgres volumes — a full disk during an index build is
  the known failure mode. `docker system df` and `df -h` before big ingests.
- **Scheduled ingestion:** add a cron entry running the `ingest` profile (e.g.
  monthly) to keep the vector tables fresh.
