#!/usr/bin/env bash
# Makes a private certificate authority and one server certificate for a broker on this machine, for the bridge's TLS option.
#   bash docs/make-certs.sh [output-directory] [days] [subjectAltName]
# Defaults: ./certs, 365 days, "DNS:localhost,IP:127.0.0.1". The tests run this very script.
#
# Files: ca.crt (public: give it to the bridge with --mqtt-tls-ca), server.crt (public), server.key (SECRET: the broker only),
#        ca.key (SECRET: it can sign certificates for anything the bridge trusts; keep it off the broker and out of git).
set -euo pipefail
OUT="${1:-certs}"; DAYS="${2:-365}"; SAN="${3:-DNS:localhost,IP:127.0.0.1}"
mkdir -p "$OUT"
cd "$OUT"
umask 077
openssl genrsa -out ca.key 3072 2>/dev/null
openssl req -x509 -new -key ca.key -sha256 -days "$DAYS" -subj "/CN=edge-mqtt-bridge private CA" -out ca.crt
openssl genrsa -out server.key 3072 2>/dev/null
openssl req -new -key server.key -subj "/CN=edge-broker" -out server.csr
printf 'subjectAltName=%s\nbasicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n' "$SAN" > server.ext
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -out server.crt -days "$DAYS" -sha256 -extfile server.ext 2>/dev/null
rm -f server.csr server.ext ca.srl
chmod 644 ca.crt server.crt
echo "Made $(pwd)/{ca.crt,server.crt,server.key,ca.key}  (valid $DAYS days, names: $SAN)"
