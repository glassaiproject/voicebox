# Deploy Voicebox (fork, GHCR, VPS)

## Fork and upstream remote

If you maintain a fork (for example under an org), keep `**origin**` pointing at your fork and add **upstream** to pull from the canonical project:

```bash
git remote add upstream https://github.com/jamiepine/voicebox.git
git fetch upstream
git merge upstream/main   # or: git rebase upstream/main
```

Or run:

```bash
./scripts/setup-upstream-remote.sh
```

## GitHub Actions

- **Docker publish** (`.github/workflows/docker-publish.yml`): builds the root `Dockerfile` and pushes to **GHCR** at  
`ghcr.io/<repository_owner>/<repository_name>:<tags>`  
on pushes to `main`, version tags `v*`, and manual `workflow_dispatch`. Pull requests only **build** (no push).
- **VPS deploy** (`.github/workflows/deploy-vps.yml`): SSH rollout on every **push to the `deploy` branch** (merge or push your release ref there when you want the VPS to pull and restart).

### Secrets and variables (GitHub repo)

Add these under **Settings → Secrets and variables → Actions** on the voicebox repository (or use **organization** secrets/variables and grant this repo access). You do **not** duplicate `GITHUB_TOKEN`—see below.

#### `GITHUB_TOKEN` (automatic)

- **Do not create this** in the secrets UI. GitHub injects it into every workflow run.
- **Role:** Lets **Docker publish** log in to GHCR and push the image. The workflow sets `permissions: packages: write` on the job so that token can publish packages.
- **You configure nothing** for this name unless you switch to a custom PAT for publishing (unusual).

#### `VPS_HOST`

- **Used by:** `deploy-vps` (SSH).
- **Value:** Your server’s **hostname or public IP**, e.g. `voice.example.com` or `203.0.113.50`. Same idea as `ssh user@VPS_HOST`.

#### `VPS_USER`

- **Used by:** `deploy-vps` (SSH).
- **Value:** The **Linux account** that SSH uses on the VPS (e.g. `ubuntu`, `debian`, `root`, or a dedicated deploy user). It must be allowed to run `docker` and `docker compose` in the deploy directory (often via `docker` group or `sudo`).

#### `VPS_SSH_KEY`

- **Used by:** `deploy-vps` (SSH).
- **Value:** The **full PEM/OpenSSH private key** (including `-----BEGIN … KEY-----` / `-----END … KEY-----` lines), usually the private half of a key pair whose **public** key is in that user’s `~/.ssh/authorized_keys` on the VPS.
- **How to get it:** Generate a deploy key pair (`ssh-keygen -t ed25519 -f voicebox_deploy -N ""`), put `voicebox_deploy.pub` on the server in `authorized_keys`, paste the contents of `voicebox_deploy` into this secret. Or reuse an existing key you already use for other deploys—paste its **private** key here.

#### `GHCR_PULL_TOKEN` (optional)

- **Used by:** `deploy-vps` only when the workflow runs `docker login` on the VPS before `docker compose pull`.
- **When you need it:** Your GHCR package is **private** (or pull otherwise fails without auth). If the image is **public**, leave this unset; the deploy script skips `docker login`.
- **Value:** A **Personal Access Token (classic or fine-grained)** from GitHub: create under **Settings → Developer settings → Personal access tokens**. For classic, enable `**read:packages`** (and use a user that can read the org’s packages). Paste the token string as the secret.
- **Login user on the server:** The workflow uses `docker login ghcr.io -u <repository_owner>` with this token; the token must belong to (or have access for) that owner/org.

#### `DEPLOY_PATH` (optional variable)

- **Used by:** `deploy-vps` to `cd` before `docker compose`.
- **Value:** Absolute path on the VPS where you copied `**docker-compose.prod.yml`** (and where `docker compose` should run), e.g. `/var/www/voicebox` or `/home/deploy/voicebox`.
- **Default:** If unset, the workflow uses `**/var/www/voicebox`**.
- **Set in:** **Actions → Variables** tab (not Secrets). Create `**DEPLOY_PATH`** if your files live somewhere other than `/var/www/voicebox`.

## Production on the VPS

1. Install Docker and Compose plugin.
2. Copy `docker-compose.prod.yml` (repo root) to the server. The image is pinned to `**ghcr.io/glassaiproject/voicebox:latest**` (from **Docker publish**). Edit the `image:` line if your fork uses another org or registry.
3. Open port **17493** (or put a reverse proxy in front; the sample compose binds `127.0.0.1:17493` like the dev file—adjust for public access if needed).
4. Run: `docker compose -f docker-compose.prod.yml up -d`

Public GHCR images do not require `docker login` on the server. Use `GHCR_PULL_TOKEN` in the deploy workflow only for private packages.