# AliCloud ECS Deploy

This deployment runs VibeChat on one AliCloud ECS instance with Docker Compose.

## 1. Security group

Open these inbound ports:

```text
22/tcp   your IP only if possible
80/tcp   0.0.0.0/0
443/tcp  0.0.0.0/0, optional for later HTTPS
```

Do not open 3000 or 8000. Nginx proxies both frontend and backend through port 80.

## 2. Install Docker on Ubuntu

Run on the ECS instance:

```bash
sudo apt update
sudo apt install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
```

## 3. Deploy VibeChat

```bash
git clone https://github.com/ice-cream-art/vibechat.git
cd vibechat
docker compose -f docker-compose.alicloud.yml up -d --build
```

For real AI replies, create a `.env` file in the repository root before starting:

```bash
cat > .env <<'EOF'
LLM_PROVIDER=openai
OPENAI_API_KEY=replace_with_your_key
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-v4-pro

AUTH_SECRET_KEY=replace_with_a_long_random_secret
AUTH_USERS=[{"email":"3117681462@qq.com","password":"vibechat2026","display_name":"VibeChat user"},{"email":"22013318","password":"535311","display_name":"Qingxing Planet 18"},{"email":"22013319","password":"535311","display_name":"Warm Beacon 19"},{"email":"22013320","password":"535311","display_name":"Shimmer Cloud 20"},{"email":"220013321","password":"535311","display_name":"Free Bird 21"}]
EOF
```

Do not commit `.env`.

## 4. Verify

Replace `SERVER_IP` with the ECS public IP:

```bash
curl http://SERVER_IP/_/backend/health
```

Then open:

```text
http://SERVER_IP
```

## 5. Update later

```bash
cd vibechat
git pull
docker compose -f docker-compose.alicloud.yml up -d --build
```

## Notes

- Use the public IP for testing first.
- A mainland China domain normally requires ICP filing before production use.
- HTTPS can be added later after a domain is bound.
