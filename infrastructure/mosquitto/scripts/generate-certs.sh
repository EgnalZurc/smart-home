#!/bin/bash
# Generate self-signed TLS certificates for Mosquitto MQTT broker
#
# Usage:
#   ./generate-certs.sh [output_directory]
#
# If output_directory is not specified, certificates are created in the
# current working directory.
#
# Examples:
#   cd ~/smart-home-prod/data/mosquitto/certs && /path/to/generate-certs.sh
#   ./generate-certs.sh /path/to/certs

set -euo pipefail

# Use argument if provided, otherwise current directory
CERTS_DIR="${1:-$(pwd)}"

# Certificate parameters
CA_DAYS=3650        # 10 years for CA
CERT_DAYS=365       # 1 year for server/client
KEY_SIZE=2048
COUNTRY="ES"
STATE="Madrid"
CITY="Madrid"
ORG="CuchiCasa"
CA_CN="CuchiCasa-CA"
SERVER_CN="mosquitto"
CLIENT_CN="mqtt-client"

echo "=== Mosquitto TLS Certificate Generator ==="
echo "Output directory: ${CERTS_DIR}"
echo ""

# Create certs directory if it doesn't exist
mkdir -p "${CERTS_DIR}"
cd "${CERTS_DIR}"

# Warn if certificates already exist
if [[ -f "ca.crt" || -f "server.crt" || -f "client.crt" ]]; then
    echo "WARNING: Existing certificates found in ${CERTS_DIR}"
    read -p "Overwrite? (y/N) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Aborted."
        exit 1
    fi
fi

echo "[1/3] Generating CA certificate (valid ${CA_DAYS} days)..."
openssl genrsa -out ca.key ${KEY_SIZE}
openssl req -x509 -new -nodes \
    -key ca.key \
    -sha256 \
    -days ${CA_DAYS} \
    -out ca.crt \
    -subj "/C=${COUNTRY}/ST=${STATE}/L=${CITY}/O=${ORG}/CN=${CA_CN}"
echo "      Created: ca.key, ca.crt"

echo "[2/3] Generating server certificate (valid ${CERT_DAYS} days)..."
openssl genrsa -out server.key ${KEY_SIZE}
openssl req -new \
    -key server.key \
    -out server.csr \
    -subj "/C=${COUNTRY}/ST=${STATE}/L=${CITY}/O=${ORG}/CN=${SERVER_CN}"
openssl x509 -req \
    -in server.csr \
    -CA ca.crt \
    -CAkey ca.key \
    -CAcreateserial \
    -out server.crt \
    -days ${CERT_DAYS} \
    -sha256
rm -f server.csr
echo "      Created: server.key, server.crt"

echo "[3/3] Generating client certificate (valid ${CERT_DAYS} days)..."
openssl genrsa -out client.key ${KEY_SIZE}
openssl req -new \
    -key client.key \
    -out client.csr \
    -subj "/C=${COUNTRY}/ST=${STATE}/L=${CITY}/O=${ORG}/CN=${CLIENT_CN}"
openssl x509 -req \
    -in client.csr \
    -CA ca.crt \
    -CAkey ca.key \
    -CAcreateserial \
    -out client.crt \
    -days ${CERT_DAYS} \
    -sha256
rm -f client.csr
echo "      Created: client.key, client.crt"

# Set restrictive permissions on private keys
chmod 600 ca.key server.key client.key
chmod 644 ca.crt server.crt client.crt

# Clean up serial file
rm -f ca.srl

echo ""
echo "=== Certificate generation complete ==="
echo ""
echo "Files created in ${CERTS_DIR}:"
ls -la "${CERTS_DIR}"
echo ""
echo "CA certificate fingerprint:"
openssl x509 -in ca.crt -noout -fingerprint -sha256
echo ""
echo "Server certificate expires:"
openssl x509 -in server.crt -noout -enddate
echo ""
echo "Next steps:"
echo "  1. Update mosquitto.conf to use these certificates"
echo "  2. Distribute ca.crt to MQTT clients"
echo "  3. NEVER commit .key files to git (they're in .gitignore)"
