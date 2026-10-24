# Nginx Proxy Manager Configuration for PokeSim Agent

## Problem

The PokeSim Agent's preview window streams video frames using the `multipart/x-mixed-replace` MIME type (MJPEG format). Standard nginx proxy configurations may buffer these streams, causing the preview to appear frozen or fail to load.

## Solution

Configure nginx proxy manager with specific headers and buffer settings to properly handle streaming responses.

## Optimal Nginx Proxy Manager Settings

### 1. Basic Proxy Configuration

In Nginx Proxy Manager, when creating or editing a proxy host for PokeSim:

**General Settings:**
- **Domain Names**: Your domain (e.g., `pokesim.example.com`)
- **Scheme**: `http` (if PokeSim is on same network) or `https` (with certificate)
- **Forward Hostname/IP**: Your PokeSim server IP (e.g., `192.168.1.100`)
- **Forward Port**: `8000` (default PokeSim port)
- **Cache**: Disable (uncheck "Cache Assets")

### 2. Custom Headers (Critical for Streaming)

In the **Custom Headers** tab, add the following headers:

```
# Essential for MJPEG streaming
add_header Connection "keep-alive";
add_header Cache-Control "no-cache, no-store, must-revalidate";
add_header Pragma "no-cache";
add_header Expires "0";

# Prevent buffering of streaming responses
add_header X-Accel-Buffering "no";

# Allow modern features
add_header X-Frame-Options "SAMEORIGIN";
add_header X-Content-Type-Options "nosniff";
```

### 3. Advanced Settings Tab

Configure these proxy parameters:

```
# In the Nginx Configuration section, add:
client_max_body_size 100M;
proxy_buffering off;
proxy_buffer_size 4k;
proxy_buffers 8 4k;
proxy_busy_buffers_size 8k;
proxy_read_timeout 90s;
proxy_connect_timeout 75s;
proxy_send_timeout 75s;

# Critical for multipart streaming
proxy_set_header Connection "keep-alive";
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
proxy_set_header X-Forwarded-Proto $scheme;
proxy_set_header X-Forwarded-Host $server_name;

# Disable SSL verification if needed (not recommended for production)
# proxy_ssl_verify off;
```

### 4. Complete Nginx Config Block

For reference, here's the complete Nginx configuration block you should generate:

```nginx
location / {
    proxy_pass http://pokesim_backend;
    
    # Connection settings
    proxy_http_version 1.1;
    proxy_set_header Connection "keep-alive";
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "Upgrade";
    
    # Header forwarding
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-Host $server_name;
    proxy_set_header X-Forwarded-Port $server_port;
    
    # Streaming settings (CRITICAL)
    proxy_buffering off;
    proxy_request_buffering off;
    proxy_set_header X-Accel-Buffering no;
    
    # Timeouts
    proxy_read_timeout 90s;
    proxy_connect_timeout 75s;
    proxy_send_timeout 75s;
    
    # Buffer sizes for normal requests
    proxy_buffer_size 4k;
    proxy_buffers 8 4k;
    proxy_busy_buffers_size 8k;
    
    # Max body size
    client_max_body_size 100M;
    
    # Caching
    proxy_no_cache 1;
    proxy_cache_bypass 1;
    
    # Headers
    add_header Cache-Control "no-cache, no-store, must-revalidate";
    add_header Pragma "no-cache";
    add_header Expires "0";
}

upstream pokesim_backend {
    server 192.168.1.100:8000;
    keepalive 32;
}
```

## Step-by-Step Nginx Proxy Manager Setup

### Via Nginx Proxy Manager Web UI

1. **Create New Proxy Host**
   - Click "Add Proxy Host" in the NPM dashboard
   
2. **Details Tab**
   - Domain Names: `pokesim.yourdomain.com`
   - Scheme: `http`
   - Forward Hostname/IP: `192.168.1.100` (your server)
   - Forward Port: `8000`
   - Check "Block Common Exploits"
   - Uncheck "Caching enabled"

3. **Custom Locations Tab**
   - Add location for `/stream` if needed with specific settings:
     ```
     location /stream {
         proxy_pass http://backend;
         proxy_buffering off;
         proxy_set_header X-Accel-Buffering no;
     }
     ```

4. **Advanced Tab**
   - Add the configuration block above

5. **SSL Tab** (Recommended)
   - Use Let's Encrypt for free HTTPS
   - Force HTTPS if desired

6. **Save and Test**

### Via Direct Nginx Config

If managing nginx directly, add this server block:

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name pokesim.yourdomain.com;
    
    # Redirect to HTTPS (optional)
    # return 301 https://$server_name$request_uri;
    
    location / {
        proxy_pass http://pokesim_backend;
        
        # Connection settings
        proxy_http_version 1.1;
        proxy_set_header Connection "keep-alive";
        
        # Headers
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # CRITICAL: Disable buffering for streaming
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_set_header X-Accel-Buffering no;
        
        # Timeouts
        proxy_read_timeout 90s;
        proxy_connect_timeout 75s;
        
        # Cache settings
        proxy_no_cache 1;
        proxy_cache_bypass 1;
    }
}

upstream pokesim_backend {
    server 192.168.1.100:8000 weight=1;
    keepalive 32;
}
```

## Troubleshooting

### Preview Window Shows "No Preview" or Freezes

**Issue**: Nginx is buffering the stream.

**Fix**: Ensure these settings are in place:
- `proxy_buffering off;` in nginx config
- `proxy_request_buffering off;` in nginx config
- `X-Accel-Buffering: no` header sent to client

### Connection Timeout

**Issue**: Streaming connection times out.

**Fix**: Increase timeout values:
```nginx
proxy_read_timeout 120s;
proxy_connect_timeout 75s;
proxy_send_timeout 75s;
keepalive_timeout 120s;
```

### CORS Errors

**Issue**: Browser blocks preview due to CORS.

**Fix**: PokeSim handles CORS automatically, but ensure proxy forwards origin headers:
```nginx
proxy_set_header Origin $http_origin;
proxy_set_header X-Forwarded-Proto $scheme;
```

### High Latency or Delayed Preview

**Issue**: Frames appear with delay.

**Fix**: 
1. Reduce buffer sizes:
   ```nginx
   proxy_buffer_size 2k;
   proxy_buffers 4 2k;
   ```

2. Ensure low network latency to backend

3. Check CPU usage on both proxy and PokeSim server

### "Bad Gateway" 502 Errors

**Issue**: Proxy can't connect to PokeSim.

**Fix**: 
- Verify PokeSim is running and accessible on port 8000
- Test direct connection: `curl http://192.168.1.100:8000/health/ready`
- Check firewall rules allow traffic between proxy and PokeSim

### Connection Reset During Stream

**Issue**: Stream disconnects frequently.

**Fix**:
- Increase keepalive settings:
  ```nginx
  keepalive_timeout 120s;
  keepalive_requests 100;
  ```

- Use persistent connections:
  ```nginx
  proxy_http_version 1.1;
  proxy_set_header Connection "keep-alive";
  ```

## Performance Optimization

### For High-Latency Networks

Increase timeouts and reduce frame rate:

```nginx
proxy_read_timeout 120s;
proxy_connect_timeout 90s;
proxy_send_timeout 90s;
proxy_buffer_size 8k;
proxy_buffers 16 8k;
```

In PokeSim settings, reduce `stream_fps` (stream frames per second) from 30 to 15-20.

### For Low-Latency Networks

Use minimal buffering for best responsiveness:

```nginx
proxy_buffer_size 2k;
proxy_buffers 2 2k;
proxy_read_timeout 60s;
```

## Security Considerations

### Rate Limiting

Prevent abuse of the streaming endpoint:

```nginx
limit_req_zone $binary_remote_addr zone=pokesim_limit:10m rate=30r/s;

location / {
    limit_req zone=pokesim_limit burst=50 nodelay;
    # ... other directives
}
```

### Authentication

Use basic auth if needed:

```nginx
location / {
    auth_basic "PokeSim Access";
    auth_basic_user_file /etc/nginx/.htpasswd;
    # ... proxy directives
}
```

### HTTPS/SSL

Always use HTTPS in production:

```nginx
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    
    ssl_certificate /path/to/certificate.crt;
    ssl_certificate_key /path/to/private.key;
    
    # ... proxy configuration
    proxy_set_header X-Forwarded-Proto https;
}

# Redirect HTTP to HTTPS
server {
    listen 80;
    listen [::]:80;
    server_name pokesim.yourdomain.com;
    return 301 https://$server_name$request_uri;
}
```

## Testing the Setup

### Test Direct Connection

```bash
curl -v http://192.168.1.100:8000/health/ready
```

Expected response:
```json
{"ok": true, "adventures": 1}
```

### Test Through Proxy

```bash
curl -v http://pokesim.yourdomain.com/health/ready
```

Should return same response through proxy.

### Test Stream Endpoint

```bash
curl -v http://pokesim.yourdomain.com/game-id/stream
```

Should show MJPEG stream headers:
```
Content-Type: multipart/x-mixed-replace
Content-Disposition: inline
Transfer-Encoding: chunked
```

### Test in Browser

Navigate to: `https://pokesim.yourdomain.com`

1. Create or start an adventure
2. Navigate to the adventure page
3. Preview window should show live game feed
4. Check browser console for errors

## Common Nginx Proxy Manager Configurations

### Configuration A: Basic Setup (Recommended for Most Users)

```
Proxy Details:
- Forward Hostname: [Your PokeSim IP]
- Forward Port: 8000

Advanced:
proxy_buffering off;
proxy_set_header X-Accel-Buffering no;
proxy_read_timeout 90s;
```

### Configuration B: High Performance

```
Advanced:
proxy_buffering off;
proxy_request_buffering off;
proxy_buffer_size 2k;
proxy_buffers 4 2k;
proxy_set_header X-Accel-Buffering no;
proxy_http_version 1.1;
proxy_set_header Connection "keep-alive";
proxy_read_timeout 90s;
proxy_connect_timeout 60s;
keepalive_timeout 120s;
```

### Configuration C: Stable Over Long Connections

```
Advanced:
proxy_buffering off;
proxy_buffer_size 4k;
proxy_buffers 8 4k;
proxy_set_header X-Accel-Buffering no;
proxy_read_timeout 120s;
proxy_connect_timeout 90s;
proxy_send_timeout 90s;
keepalive_timeout 150s;
keepalive_requests 100;
```

## Additional Resources

- [Nginx Proxy Manager Documentation](https://nginxproxymanager.com/)
- [Nginx Documentation](https://nginx.org/en/docs/)
- [MJPEG Streaming Documentation](https://en.wikipedia.org/wiki/Motion_JPEG)

## FAQ

**Q: Do I need HTTPS?**
A: Not strictly required for local networks, but highly recommended for internet-exposed instances.

**Q: Can I use other reverse proxies?**
A: Yes. The key settings are:
- Disable buffering
- Set `X-Accel-Buffering: no` header
- Use `multipart/x-mixed-replace` MIME type
- Maintain persistent connections

**Q: Why is the preview black?**
A: Usually means:
1. Adventure is not running (start it first)
2. Adventure is in a menu (not in battle)
3. Connection failed (check browser console)

**Q: Can I stream over the internet securely?**
A: Yes, use HTTPS/SSL. PokeSim handles all authentication internally.

**Q: What about Docker networks?**
A: Use Docker service name instead of IP:
```nginx
proxy_pass http://pokesim:8000;
upstream pokesim_backend {
    server pokesim:8000;
}
```
