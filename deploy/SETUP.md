# Deploying to a GCP VM with a DuckDNS name

Target: `e2-small` (2 GB RAM, 1 vCPU), Debian 12, 20 GB disk.

## 1. On GCP

Reserve a **static** external IP and attach it to the VM — the default
ephemeral IP changes every stop/start and would break DuckDNS silently.

Open the firewall for web traffic only:

```bash
gcloud compute firewall-rules create allow-web \
  --allow=tcp:80,tcp:443 --target-tags=firehose
gcloud compute instances add-tags firehose --tags=firehose --zone=YOUR_ZONE
```

Ports 3000 and 8000 stay closed. Caddy is the only thing the internet talks to.

## 2. On the VM

```bash
sudo apt update
sudo apt install -y python3-pip python3-venv git
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt install -y nodejs

# Caddy (handles HTTPS certificates by itself)
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https curl
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
  | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
  | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install -y caddy
```

## 3. The app

```bash
sudo git clone https://github.com/ravi3594444/jev-agent1.git /opt/firehose
cd /opt/firehose
sudo pip install -r requirements.txt --break-system-packages
cd web && npm install && npm run build && cd ..

sudo cp .env.example .env
sudo nano .env        # add AIMLAPI_API_KEY, ATRIA_API_KEY, and FIREHOSE_TOKEN
```

`FIREHOSE_TOKEN` is optional and can be left blank — the bridge only listens on
127.0.0.1, so nothing outside the VM can reach it either way. Set it if you ever
move the web UI off this box (to Vercel, say), because then the bridge becomes
internet-facing and that token is the only thing in front of it:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(32))"
```

## 4. DuckDNS

Point your DuckDNS subdomain at the VM's static IP, then keep it honest with a
cron entry on the VM (harmless if the IP never changes, essential if it does):

```
*/5 * * * * curl -fsS "https://www.duckdns.org/update?domains=YOURNAME&token=YOUR_DUCKDNS_TOKEN&ip=" >/dev/null
```

Leaving `ip=` empty makes DuckDNS use the source IP of the request, so you
never have to hardcode it.

## 5. Caddy

```bash
sudo cp Caddyfile /etc/caddy/Caddyfile
sudo nano /etc/caddy/Caddyfile   # set YOURNAME to your DuckDNS subdomain
sudo systemctl restart caddy
```

The shipped config has no password on it. If you later want one, uncomment the
`basic_auth` block and run `caddy hash-password`.

Caddy fetches a Let's Encrypt certificate on first request. Renewal is
automatic — nothing to schedule.

## 6. Services

```bash
sudo cp deploy/firehose-web.service /etc/systemd/system/
sudo cp deploy/firehose.service deploy/firehose.timer /etc/systemd/system/
sudo useradd -r -s /usr/sbin/nologin firehose || true
sudo chown -R firehose:firehose /opt/firehose
sudo systemctl daemon-reload
sudo systemctl enable --now firehose-web.service   # the bridge
sudo systemctl enable --now firehose.timer         # the daily scorer
```

The Next server needs a unit too — copy `firehose-next.service`, then:

```bash
sudo systemctl enable --now firehose-next.service
python3 -m firehose run        # first run, so there is something to chat about
```

## 7. Check it

```
https://YOURNAME.duckdns.org
```

Browser asks for the Caddy password, then the chat loads.

## What is exposed

| Port | Who can reach it |
|---|---|
| 443 | the internet (open — add `basic_auth` in the Caddyfile to gate it) |
| 80 | the internet, redirected to 443 by Caddy |
| 3000 | localhost only (Next) |
| 8000 | localhost only (the bridge), and it also checks `FIREHOSE_TOKEN` |

The bridge and Next are bound to localhost, so the only door in is Caddy on 443.
If you ever move Next to Vercel the bridge has to face the internet, and
`FIREHOSE_TOKEN` becomes the only thing in front of it — set it then.
