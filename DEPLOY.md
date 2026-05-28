# DEPLOY.md — AACE production deployment

Step-by-step VPS provisioning, hardening, and deploy for v0.1.0.
Roughly 30 minutes from a fresh server to AACE running 24/7.

These instructions target **Ubuntu 24.04 LTS** on any cloud provider
(Hetzner, DigitalOcean, Oracle Cloud, Linode, etc.). Differences
between providers are flagged inline.

---

## 1. Provision the VPS (5 min)

Whichever provider you pick, the specs are the same:

- **Ubuntu 24.04 LTS** (or 22.04 LTS — both work)
- **2 GB RAM minimum**, 4 GB recommended (the build of `psycopg[binary]` + feedparser uses some memory transiently)
- **20 GB disk**
- **A region close to you** for low-latency SSH

### Hetzner Cloud (~€4/month — recommended)
1. Sign up at https://www.hetzner.com/cloud
2. Create a new project → "Add Server"
3. Location: pick the closest to you (Nuremberg / Helsinki / Ashburn US-East / Hillsboro US-West)
4. Image: **Ubuntu 24.04**
5. Type: **CX22** (€4.59/mo, 2 vCPU, 4 GB RAM) — perfect for v0.1.0
6. SSH key: paste the contents of `~/.ssh/id_ed25519.pub` (see step 2 below)
7. Create + Buy now

### DigitalOcean ($6/month)
1. Sign up at https://www.digitalocean.com
2. Create → Droplets
3. Region: closest to you
4. Image: **Ubuntu 24.04 (LTS) x64**
5. Plan: **Basic / Regular / $6/mo** (1 vCPU, 1 GB RAM, 25 GB SSD) — bump to $12 if you want margin
6. Authentication: **SSH Key** → paste `~/.ssh/id_ed25519.pub`
7. Create Droplet

### Oracle Cloud Free Tier ($0 forever)
1. Sign up at https://www.oracle.com/cloud/free
2. Identity verification can take 1–24 hours.
3. Compute → Instances → Create instance
4. Image: **Canonical Ubuntu 24.04** (or 22.04)
5. Shape: **Ampere A1 Flex** (free) — 1 OCPU, 6 GB RAM is plenty
6. Networking: assign a public IPv4
7. Add SSH keys: paste `~/.ssh/id_ed25519.pub`
8. Create

Once provisioned, grab the server's **public IP address** — you'll use it below.

---

## 2. Generate an SSH key if you don't have one (1 min)

On your Mac, in any terminal:

```
ls -la ~/.ssh/id_*.pub
```

If you see `id_ed25519.pub` or `id_rsa.pub`, you're set. Otherwise:

```
ssh-keygen -t ed25519
```

Press enter on every prompt (no passphrase is fine for now — add one
later via `ssh-keygen -p` if desired).

Then print the public key to copy into the VPS provider's UI:

```
cat ~/.ssh/id_ed25519.pub
```

---

## 3. First SSH in + harden (5 min)

Replace `1.2.3.4` with your server's public IP throughout.

```
ssh root@1.2.3.4
```

(On Oracle, the user might be `ubuntu` instead of `root`. The provider's
console tells you which.)

Inside the server, run this hardening block — copy-paste the whole thing:

```bash
# Create a non-root user and give it sudo
useradd -m -s /bin/bash -G sudo aace
mkdir -p /home/aace/.ssh
cp ~/.ssh/authorized_keys /home/aace/.ssh/
chown -R aace:aace /home/aace/.ssh
chmod 700 /home/aace/.ssh
chmod 600 /home/aace/.ssh/authorized_keys

# Allow the new user passwordless sudo
echo "aace ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/aace
chmod 0440 /etc/sudoers.d/aace

# Disable password SSH logins (keys only)
sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#*PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config
systemctl reload ssh

# Update + install firewall + fail2ban + git
apt-get update -y && apt-get upgrade -y
apt-get install -y ufw fail2ban git
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw --force enable
systemctl enable --now fail2ban
```

Log out (`exit`) and SSH back in as the new user from now on:

```
ssh aace@1.2.3.4
```

If that works, you're hardened.

---

## 4. Install Docker + Compose plugin (3 min)

Still on the server, as `aace`:

```bash
# Docker engine + compose plugin (official upstream)
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER

# Log out + back in so the docker group takes effect
exit
```

Reconnect:

```
ssh aace@1.2.3.4
```

Verify:

```
docker --version
docker compose version
```

Both should print versions without `sudo`.

---

## 5. Clone the repo (1 min)

```
cd ~
git clone https://github.com/Kpakpavi/aace-execution.git
cd aace-execution
```

---

## 6. Configure the environment (3 min)

Copy the example, then edit:

```
cp .env.example .env
nano .env
```

You **must** set these — leaving any blank will refuse to start:

| Variable | What to put |
|---|---|
| `POSTGRES_PASSWORD` | Long random string. Generate with `openssl rand -hex 32` |
| `AACE_API_KEY` | Long random string. Same command |
| `AGENT_WEBHOOK_URL` | Your AI agent's webhook URL. For initial shakedown, use a free https://webhook.site URL |
| `AGENT_WEBHOOK_SECRET` | Long random string. Same generator |

You can leave the `SCORER_*` and `WORKER_INTERVAL_MINUTES` values at
their defaults for now. Tune them on Day 7 against real data.

Save (`Ctrl+O`, Enter, `Ctrl+X`).

---

## 7. Build + launch the stack (3 min for first build)

```
docker compose up -d --build
```

Wait ~2 minutes. Then verify everything is running:

```
docker compose ps
```

All four containers should show `Up` / `running`:

- `aace-postgres`
- `aace-api`
- `aace-dashboard`
- `aace-worker`

---

## 8. Verify the worker is doing real work (2 min)

Tail the worker logs:

```
docker compose logs -f worker
```

Within ~30 seconds of launch, you should see a `worker_starting` entry
and then a `worker_tick_complete` entry. The worker fires once at boot,
then every `WORKER_INTERVAL_MINUTES` thereafter.

If you set `AGENT_WEBHOOK_URL` to a webhook.site URL, refresh that
browser tab and you should see signed POSTs arriving (assuming any
cross-source matches happened).

`Ctrl+C` to stop tailing — the container keeps running.

---

## 9. Reboot persistence check (1 min)

The `restart: unless-stopped` policy on every service means everything
auto-recovers. To prove it:

```
sudo reboot
```

Wait 60 seconds, SSH back in, run:

```
docker compose ps
```

All four should be `Up` again on their own.

---

## 10. (Optional) Tailscale for dashboard access

Don't expose port 8502 (the Streamlit dashboard) to the public internet.
Instead, install Tailscale and reach the dashboard via private network.

```
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

Authorize the device at the URL it prints. Install Tailscale on your
Mac too, then visit `http://<server-tailscale-hostname>:8502` from
your laptop — the dashboard is now reachable only from devices on
your private Tailnet.

---

## You're live

The worker is now pulling from Slickdeals + DealNews every 30 minutes,
matching cross-source, scoring, and shipping to your agent.

**Day 7** = let it run 24h, audit `docker compose logs worker`,
tune `SCORER_MIN_*` if there's too much noise or too little signal,
act on the first real arbitrage deal, and tag `v0.1.0` on GitHub.

---

## Useful day-2 commands

```
# Tail worker logs in real time
docker compose logs -f worker

# Restart just the worker (e.g. after env change)
docker compose up -d worker

# Pull latest code + rebuild
git pull && docker compose up -d --build

# Stop everything
docker compose down

# Stop everything AND delete the Postgres volume (nuke)
docker compose down -v
```
