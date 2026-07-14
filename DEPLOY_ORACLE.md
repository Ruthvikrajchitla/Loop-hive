# Deploy LoopHive on Oracle Cloud Always Free (24/7)

This runs the swarm **24/7, persists all data, and survives reboots / your laptop
being off** — none of which Render's free tier can do.

The whole thing runs as one `systemd` service: the dashboard process also runs the
autonomous swarm in the background. SQLite (`loophive.db`) lives on the VM disk, so
nothing is wiped on restart.

---

## 1. Create the free VM

1. Sign up at https://cloud.oracle.com (Always Free — no charge).
2. **Compute → Instances → Create instance.**
   - Image: **Ubuntu 22.04**.
   - Shape: **VM.Standard.A1.Flex** (ARM, Always Free — 1-4 OCPU / up to 24 GB) or
     **VM.Standard.E2.1.Micro** (x86, Always Free). Either is fine.
   - Save the SSH key (download the private key).
3. After it boots, note the instance's **Public IP address**.

## 2. Open the dashboard port (two layers)

**Layer A — Oracle Security List (cloud firewall):**
Networking → your VCN → Subnet → Security List → **Add Ingress Rule**:
- Source CIDR: `0.0.0.0/0` (or just your home IP for safety — see Security note)
- IP Protocol: TCP, Destination port: `8000`

**Layer B — the VM's own firewall (do this after you SSH in, step 3):**
```bash
sudo iptables -I INPUT -p tcp --dport 8000 -j ACCEPT
sudo netfilter-persistent save
```

## 3. SSH in and install

```bash
ssh -i /path/to/your-key ubuntu@YOUR_PUBLIC_IP

sudo apt update
sudo apt install -y python3-venv python3-pip git nodejs   # nodejs = JS validation in the sandbox

git clone https://github.com/Ruthvikrajchitla/Loop-hive.git
cd Loop-hive
python3 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install .
```

## 4. Add your API keys (fastest: copy your working local .env)

From YOUR LOCAL machine (a new terminal), copy your already-configured `.env` up:
```bash
scp -i /path/to/your-key .env ubuntu@YOUR_PUBLIC_IP:~/Loop-hive/.env
```
(Or on the VM: `cp .env.example .env && nano .env` and paste every key.)

Make sure these are set for the production deep-build behavior:
```
EXECUTION_SANDBOX=true       # ship only after real venv+install+import+tests pass
MAX_DAILY_PRODUCTS=1         # one deeply-perfected product per day
BUILD_ROUNDS=12  RESEARCH_ROUNDS=5  FUSION_WAIT=true  FUSION_ALL_MODELS=true
RUN_SWARM_IN_DASHBOARD=true  # run the swarm inside the dashboard process
# DATABASE_URL default = SQLite on the VM disk → PERSISTS across restarts (memory survives)
```

## 5. Install the 24/7 service

```bash
sudo cp deploy/loophive.service /etc/systemd/system/loophive.service
sudo systemctl daemon-reload
sudo systemctl enable --now loophive
```

Check it:
```bash
systemctl status loophive          # should say active (running)
journalctl -u loophive -f          # live logs — watch the agents work
```

## 6. Open the dashboard

Visit **http://YOUR_PUBLIC_IP:8000/dashboard**

It now runs forever: builds until the daily article/product target is reached,
then idles until the next day, and resumes automatically. A reboot or crash
auto-restarts the service, and your data (niches, articles, products) persists.

---

## Updating to the latest code later

```bash
cd ~/Loop-hive
git pull
.venv/bin/pip install .
sudo systemctl restart loophive
```

## Security note (important)

Port 8000 has **no login** — anyone with your IP can view the dashboard. Options:
- In the Oracle Ingress rule, set Source to **your home IP only** instead of `0.0.0.0/0`.
- Or put it behind a reverse proxy (Caddy/Nginx) with basic auth later.
Your API keys live only in `.env` on the VM (never in git), so they aren't exposed
by the dashboard.

## Data backup (optional)

Everything is in `~/Loop-hive/loophive.db`. To back up:
```bash
cp ~/Loop-hive/loophive.db ~/loophive-backup-$(date +%F).db
```
