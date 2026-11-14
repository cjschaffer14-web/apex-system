#!/bin/bash
set -euo pipefail
mkdir -p /var/lib/apex-stream/spool /var/lib/apex-stream/docker-config
chmod 700 /var/lib/apex-stream/docker-config
export DOCKER_CONFIG=/var/lib/apex-stream/docker-config
curl -fsS -H 'Metadata-Flavor: Google' http://169.254.169.254/computeMetadata/v1/instance/service-accounts/default/token | sed -n 's/.*"access_token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | docker login -u oauth2accesstoken --password-stdin https://us-central1-docker.pkg.dev
docker pull 'us-central1-docker.pkg.dev/alert-maker-509913-m7/apex-public/stream@sha256:a4f40eb9beeff09195141da435cbe1f5337d4e020bd3ce6085ee14ba249f230c'
if docker container inspect apex-stream >/dev/null 2>&1; then
 docker stop -t 60 apex-stream
 docker rm apex-stream
fi
docker run -d --name apex-stream --restart=always --network=host --memory=650m --log-driver=local --log-opt max-size=10m --log-opt max-file=3 -v /var/lib/apex-stream/spool:/spool -e EXPECTED_PROJECT=alert-maker-509913-m7 -e BUCKET=alert-maker-509913-m7-apex-public-stream-v2 'us-central1-docker.pkg.dev/alert-maker-509913-m7/apex-public/stream@sha256:a4f40eb9beeff09195141da435cbe1f5337d4e020bd3ce6085ee14ba249f230c'
docker logout us-central1-docker.pkg.dev

