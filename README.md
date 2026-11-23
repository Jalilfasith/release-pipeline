# Pipeline Desk · hands-on deployment guide

Build and operate a release board for a DevOps team. A run moves through Source, Build, Test, Deploy, and Verify. A teammate records each outcome. Mark a stage blocked when a check fails, resume after fixing it, and pass Verify to finish. The buttons record progress; your GitHub and AWS accounts are never invoked by the app.

## Target 1 — Understand the project

| File | Role |
|---|---|
| index.html | Dashboard layout and new-run form |
| style.css | Deep blue and warm cream interface with an animated electric-yellow pipeline and reduced-motion support |
| app.py | Handles browser requests, validates stage transitions, and saves each run in SQLite |
| Dockerfile | Packages Python, Gunicorn, and the three application files; starts the app as user 10001 |
| compose.yaml | Builds the image, publishes the loopback port, mounts the database volume, checks health and restarts the container |
| .gitignore and .dockerignore | Exclude local database files, credentials and generated files |

A browser GET displays current runs. A form POST saves one change in SQLite and redirects the browser back to the dashboard. Each update includes a version so an old tab cannot accidentally pass a second stage. The database lives at /data/tracker.sqlite3 in the Docker-managed runs volume.

## Target 2 — Run it on your Ubuntu laptop

Download pipeline-tracker.zip into Downloads. Run each command in order.

    cd ~/Downloads
    unzip pipeline-tracker.zip
    cd pipeline-tracker

Confirm Docker, Compose and the build plugin are available:

    sudo docker version
    sudo docker compose version
    sudo docker buildx version

Check your laptop port. If 19642 is occupied, change the middle number in the port mapping and use that new port in local URLs and Nginx. 19641 is internal to the container.

    sudo ss -ltn 'sport = :19642'
    sudo docker ps --filter publish=19642

Validate the YAML, build the image, and wait for the app:

    sudo docker compose config --quiet
    sudo docker compose up -d --build --wait
    sudo docker compose ps
    curl -i http://127.0.0.1:19642/health

Open http://127.0.0.1:19642/ on the laptop. Create “Store API v1.2”, pass Source, block Build, resume Build, then pass the remaining stages. Expect Complete after Verify.

## Target 3 — Prove the database survives a container replacement

    sudo docker compose down
    sudo docker compose up -d --wait

Refresh the browser. The same run and its stage should appear. A plain down preserves the named volume; adding -v deletes the database. To inspect startup, access requests or errors:

    sudo docker compose logs --tail 30 web

## Target 4 — Push the project to GitHub

On the laptop, create an empty GitHub repository named pipeline-tracker under your account. Skip automatic README creation. From the extracted project folder, using the account from the earlier lab:

    git init -b main
    git add .
    git status --short
    git commit -m "Add pipeline tracker with persistent release stages"
    git remote add origin https://github.com/Jalilfasith/pipeline-tracker.git
    git push -u origin main

Use your normal GitHub authentication. For a different owner, substitute its clone URL. Verify app.py, Dockerfile and compose.yaml are visible on GitHub. A private repo also needs read access from EC2.

## Target 5 — Run the backend on EC2

Cloud layout: browser → EC2 security group (443) → host Nginx → 127.0.0.1:19642 → container port 19641 → SQLite on an EBS-backed Docker volume. An Internet Gateway and a public IPv4 address make the proxy reachable. The database has no network port. The stored runs are local to this instance; take EBS backups if they matter.

Use the Amazon Linux 2023 instance and working SSH command from your Shelf Notes lab. For a new instance choose an encrypted EBS volume, a public subnet with an Internet Gateway route and a public IPv4 (an Elastic IP if you need a stable certificate address). Allow SSH 22 and HTTPS 443 from your laptop's public IPv4 /32; HTTP 80 must be reachable for the Certbot HTTP challenge. Restrict 443 to trusted users' IPs: anyone allowed in can edit this demo. Leave 19641 and 19642 closed in the security group.

On a new Amazon Linux 2023 instance install the host tools first:

    sudo dnf install -y docker git nginx
    sudo systemctl enable --now docker

Run the three Docker version checks in Target 2 on EC2. Fresh Amazon Linux installations may need the Linux Docker Compose and Buildx CLI plugins. Use the official Linux plugin instructions linked at the end, install system-wide for sudo, and choose the binary matching uname -m. On your working EC2 instance these plugins are already set up.

On EC2, clone the new repository into its own folder:

    cd ~
    git clone https://github.com/Jalilfasith/pipeline-tracker.git
    cd pipeline-tracker
    sudo ss -ltn 'sport = :19642'
    sudo docker compose up -d --build --wait
    curl -i http://127.0.0.1:19642/health

Expected: HTTP 200 and healthy. Laptop and EC2 databases are separate. If this fails, check sudo docker compose ps -a and sudo docker compose logs --tail 50 web before configuring TLS.

## Target 6A — Add HTTPS on the existing Shelf Notes instance

Use this route when the Nginx server block and IP certificate from the earlier lab are still in place. Your previous lab used 16.179.127.82. Confirm today's public IP in the AWS console. Check the certificate on EC2:

    sudo /opt/shelf-certbot/bin/certbot certificates

Confirm the certificate covers the current IP and is still valid. For an expired certificate on the same IP, use the existing port-80 ACME configuration and run sudo /opt/shelf-certbot/bin/certbot renew --cert-name shelf-notes-ip, then reload Nginx. For a new IP obtain a certificate for that address and update the corresponding Nginx server name and certificate paths.

Edit the existing HTTPS server:

    sudo nano /etc/nginx/conf.d/shelf-notes-https.conf

Inside its server { ... } block add the following location alongside the existing location / block. Keep the trailing slash on both the location and proxy_pass URL. Nginx removes /pipeline/ before forwarding; relative form actions and redirects keep the browser under /pipeline/.

    location /pipeline/ {
        proxy_pass http://127.0.0.1:19642/;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

Apply only after validation:

    sudo nginx -t && sudo systemctl reload nginx

On your laptop, if the verified public IP is still 16.179.127.82:

    curl -i https://16.179.127.82/pipeline/health

Open https://16.179.127.82/pipeline/ in the browser. Shelf Notes stays at /. Continue to Target 7. The steps below are for a separate fresh EC2 host.

## Target 6B — First certificate on a fresh EC2 instance

Use this route on a fresh Amazon Linux 2023 host with ports 80 and 443 available. On an existing multi-site host, reuse its Nginx configuration as in 6A. In the commands below enter the EC2 public IPv4 from the AWS console when prompted:

    read -rp "EC2 public IPv4: " PUBLIC_IP
    sudo dnf install -y nginx python3.11
    sudo python3.11 -m venv /opt/pipeline-certbot
    sudo /opt/pipeline-certbot/bin/pip install 'certbot>=5.4'
    sudo mkdir -p /var/www/letsencrypt

Paste this entire block. It creates the plain HTTP verification route:

    sudo tee /etc/nginx/conf.d/pipeline-http.conf >/dev/null <<EOF_HTTP
    server {
        listen 80;
        server_name ${PUBLIC_IP};
        location /.well-known/acme-challenge/ { root /var/www/letsencrypt; }
        location / { return 301 https://${PUBLIC_IP}\$request_uri; }
    }
    EOF_HTTP

When typing a heredoc, the closing marker (EOF_HTTP or EOF_TLS) starts at the beginning of the line without spaces. Markdown code blocks display the commands without their formatting indent.

    sudo nginx -t
    sudo systemctl enable --now nginx
    sudo systemctl reload nginx

Request a certificate; follow the email and agreement prompts:

    sudo /opt/pipeline-certbot/bin/certbot certonly --webroot -w /var/www/letsencrypt --preferred-profile shortlived --ip-address "$PUBLIC_IP" --cert-name pipeline-ip

After successful issuance, paste this block in the same shell:

    sudo tee /etc/nginx/conf.d/pipeline-https.conf >/dev/null <<EOF_TLS
    server {
        listen 443 ssl;
        server_name ${PUBLIC_IP};
        ssl_certificate /etc/letsencrypt/live/pipeline-ip/fullchain.pem;
        ssl_certificate_key /etc/letsencrypt/live/pipeline-ip/privkey.pem;
        location = / { return 302 /pipeline/; }
        location /pipeline/ {
            proxy_pass http://127.0.0.1:19642/;
            proxy_set_header Host \$host;
            proxy_set_header X-Forwarded-Proto \$scheme;
        }
    }
    EOF_TLS

    sudo nginx -t && sudo systemctl reload nginx

Open https://YOUR_PUBLIC_IP/pipeline/ from your laptop. An IP certificate is valid for 160 hours; this two-day playbook does not schedule renewal. Close the lab's public access when finished if you want it to end after two days.

## Target 7 — Verify, diagnose, and stop

| Check | Where to run it | Expected result |
|---|---|---|
| curl -i http://127.0.0.1:19642/health | EC2 | 200 healthy |
| curl -i https://YOUR_PUBLIC_IP/pipeline/health | Laptop | 200 healthy with trusted TLS |
| Create a run, pass Source, refresh | Laptop browser | Build is active |
| Block Build, resume it, finish Verify | Laptop browser | Complete |
| Recreate the service as in Target 3 | EC2 | Run survives refresh |

If HTTPS times out, verify TCP 443 source is your laptop's public IP and the subnet has an Internet Gateway route. If Nginx returns 502, check the local health URL, then sudo tail -n 30 /var/log/nginx/error.log. If SELinux is enforcing, inspect denials before changing host policy. If you see Shelf Notes, use /pipeline/ including its trailing slash. For a certificate warning, verify the current IP and expiry. For a 409 conflict, refresh the dashboard to read the latest stage before taking another action.

Stop just the tracker from its project folder:

    sudo docker compose stop

## Official references

- Docker Compose Linux plugin: https://docs.docker.com/compose/install/linux/
- Buildx releases and Linux installation: https://github.com/docker/buildx#installing
- EC2 security groups: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-security-groups.html
- VPC internet access: https://docs.aws.amazon.com/vpc/latest/userguide/VPC_Internet_Gateway.html
- Certbot IP certificates: https://letsencrypt.org/2026/03/11/shorter-certs-certbot/
