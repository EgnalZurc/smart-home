# Security Implementation TODO

## Critical Before Production Use

### 1. HTTP Basic Authentication (30 min)
- [ ] Install apache2-utils for htpasswd
- [ ] Create .htpasswd file with secure password
- [ ] Update nginx.conf with auth_basic
- [ ] Test authentication works
- [ ] Document credentials securely

### 2. HTTPS with Let's Encrypt (45 min)
- [ ] Install certbot
- [ ] Stop nginx temporarily
- [ ] Run certbot to get certificate
- [ ] Update nginx.conf for SSL
- [ ] Configure auto-renewal
- [ ] Test HTTPS access
- [ ] Open port 443 in router (and close port 80)

### 3. Security Headers (15 min)
- [ ] Add X-Frame-Options
- [ ] Add X-Content-Type-Options
- [ ] Add Strict-Transport-Security
- [ ] Test headers with securityheaders.com

### 4. Rate Limiting (15 min)
- [ ] Configure nginx rate limiting
- [ ] Test with multiple requests
- [ ] Verify IP blocking works

## Quick Start Command

When ready to implement:

ssh pi@raspberrypi.local
cd ~/projects/smart-home
# Follow steps in this file

## Estimated Total Time: 2 hours

---

Created: June 24, 2026
Status: Port forwarding configured, HTTP working, security PENDING
