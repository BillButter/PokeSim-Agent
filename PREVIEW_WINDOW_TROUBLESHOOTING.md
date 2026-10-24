# PokeSim Preview Window Troubleshooting Guide

## Quick Diagnosis

### Preview Shows Nothing

1. **Check if adventure is running**
   - Preview only works when adventure is in gameplay (not menus)
   - Start an adventure first, then navigate to its page

2. **Test direct connection**
   ```bash
   curl http://your-pokesim-server:8000/health/ready
   ```
   Should return: `{"ok": true, "adventures": 1}`

3. **Check browser console**
   - Press F12 to open developer tools
   - Check the Console tab for errors
   - Check the Network tab for failed requests

### Via Nginx Proxy Manager

### Issue: Connection Failed

**Error**: "Preview unavailable" or "Connection refused"

**Diagnosis**:
```bash
# Test from proxy manager container
docker exec nginx-proxy-manager curl http://pokesim:8000/health/ready

# Test from host
curl http://localhost:8000/health/ready
```

**Common Fixes**:
1. **PokeSim not running**
   ```bash
   docker ps | grep pokesim
   ```
   If not running, start it:
   ```bash
   docker-compose up -d pokesim
   ```

2. **Firewall blocking port 8000**
   ```bash
   # Allow port 8000
   sudo ufw allow 8000/tcp
   ```

3. **Nginx proxy not configured correctly**
   - In Nginx PM admin panel
   - Edit the pokesim proxy host
   - Verify "Forward Hostname" is `pokesim` (if using Docker)
   - Verify "Forward Port" is `8000`
   - Click "Test" to verify connectivity

### Issue: "Stream Buffering" or Frozen Preview

**Symptoms**: Preview appears but freezes, doesn't update frames

**Root Cause**: Nginx is buffering the MJPEG stream

**Diagnosis**:
```bash
# Check nginx config has buffering disabled
docker exec nginx-proxy-manager grep -r "proxy_buffering" /etc/nginx/conf.d/

# Check if X-Accel-Buffering header is present
curl -i http://localhost/pokesim.yourdomain.com/stream | grep -i "x-accel"
```

**Fix**: In Nginx Proxy Manager

1. Click on your pokesim proxy host
2. Go to "Advanced" tab
3. Add/verify this configuration:
   ```
   proxy_buffering off;
   proxy_request_buffering off;
   proxy_set_header X-Accel-Buffering no;
   ```
4. Save and wait for nginx to reload

### Issue: Preview Shows But Updates Very Slowly

**Causes**:
1. High network latency
2. Proxy buffers too large
3. Low FPS setting
4. CPU overload

**Solutions**:

1. **Reduce buffer sizes** (in Nginx PM Advanced tab):
   ```nginx
   proxy_buffer_size 2k;
   proxy_buffers 4 2k;
   proxy_busy_buffers_size 4k;
   ```

2. **Reduce PokeSim stream FPS** (in adventure settings):
   - Adventure page → Settings
   - Change `stream_fps` from 30 to 15-20

3. **Check network latency**:
   ```bash
   ping your-pokesim-server
   ```
   Should be < 50ms for smooth streaming

4. **Monitor server CPU**:
   ```bash
   docker stats pokesim
   ```
   If CPU is 100%, check if adventure is running complex operations

### Issue: "No JSON" Errors in Preview Window

**This may indicate a different AI model issue, not preview-related**

See: [NGINX_PROXY_SETUP.md](NGINX_PROXY_SETUP.md) for streaming configuration

### Issue: Preview Works Locally But Not Through Proxy

**Diagnosis**:
1. Test direct: `http://pokesim-server:8000/game-id`
2. Test through proxy: `http://pokesim.yourdomain.com/game-id`

**If direct works but proxy fails**:

1. **Verify proxy is configured**
   ```bash
   curl -H "Host: pokesim.yourdomain.com" http://nginx-proxy-ip/game-id
   ```

2. **Check proxy logs**
   ```bash
   docker logs nginx-proxy-manager
   ```

3. **Verify forward hostname/port in NPM**
   - Should be: hostname=`pokesim`, port=`8000`
   - Not: `localhost:8000` or `127.0.0.1:8000`

4. **Check network connectivity between proxy and pokesim**
   ```bash
   docker exec nginx-proxy-manager ping pokesim
   docker exec nginx-proxy-manager curl http://pokesim:8000/
   ```

### Issue: "503 Service Unavailable" Through Proxy

**Cause**: Nginx can't reach PokeSim backend

**Fixes**:

1. **Verify backend is online**
   ```bash
   docker exec pokesim curl http://localhost:8000/health/ready
   ```

2. **Check Docker network connectivity**
   ```bash
   docker network inspect pokesim-network
   # Verify both pokesim and nginx-proxy-manager are connected
   ```

3. **Verify proxy host configuration**
   - Forward Hostname must match service name (usually `pokesim`)
   - Not IP address in Docker network

4. **Check nginx logs**
   ```bash
   docker logs nginx-proxy-manager | tail -50
   ```
   Look for "upstream" or "connection refused" errors

5. **Verify firewall between containers**
   ```bash
   docker exec nginx-proxy-manager nc -zv pokesim 8000
   ```
   Should show: `Connection to pokesim 8000 port [tcp/*] succeeded`

## Advanced Diagnostics

### Capture Stream Debugging

**Check if stream is being sent**:
```bash
# Raw stream test
curl -v http://pokesim-server:8000/adventure-id/stream 2>&1 | head -20
```

Should show:
```
< Content-Type: multipart/x-mixed-replace; boundary=frame
< Connection: keep-alive
< X-Accel-Buffering: no
```

**Through nginx proxy**:
```bash
curl -v -H "Host: pokesim.yourdomain.com" http://proxy-ip/adventure-id/stream 2>&1 | head -20
```

Should show same headers.

### Test MJPEG Decoder

**Verify browser can decode MJPEG**:
```html
<img src="http://pokesim-server:8000/adventure-id/stream" />
```

If this works in browser, preview should work too.

### Check Frame Generation

**Verify frames are being generated**:
```bash
# Check if frame.jpg exists and updates
ls -la pokesim_data/interactions/*/attempts/*/outputs/
stat pokesim_data/interactions/*/attempts/*/outputs/left.jpg
# Check modification time updates frequently
```

## Performance Tuning

### For High Latency Networks (> 100ms)

1. **Increase timeouts**:
   ```nginx
   proxy_read_timeout 120s;
   proxy_connect_timeout 90s;
   proxy_send_timeout 90s;
   ```

2. **Reduce frame rate**:
   - PokeSim settings: `stream_fps: 15`

3. **Larger buffers to handle jitter**:
   ```nginx
   proxy_buffer_size 8k;
   proxy_buffers 16 8k;
   ```

### For Low Latency Networks (< 50ms)

1. **Reduce timeouts**:
   ```nginx
   proxy_read_timeout 60s;
   proxy_connect_timeout 45s;
   ```

2. **Minimal buffers**:
   ```nginx
   proxy_buffer_size 2k;
   proxy_buffers 2 2k;
   ```

3. **Normal frame rate**:
   - PokeSim settings: `stream_fps: 30`

## Browser-Specific Issues

### Chrome/Chromium

**Issue**: Preview works but performance is poor

**Fix**: Enable hardware acceleration
1. Chrome settings → Advanced → System
2. Enable "Use hardware acceleration"

### Firefox

**Issue**: MJPEG stream not updating

**Fix**: Disable image.http.keep-alive.timeout
1. Type `about:config` in address bar
2. Search for `image.http.keep-alive`
3. Disable if necessary

### Safari

**Issue**: Preview not appearing

**Fix**: Clear browser cache and restart
1. Safari → Develop → Empty Caches
2. Force refresh: Cmd+Shift+R

## Docker-Specific Issues

### Verify Docker Network Setup

```bash
# List networks
docker network ls

# Inspect network
docker network inspect pokesim-network

# Verify services are connected
docker network inspect pokesim-network | grep -A 20 "Containers"
```

### Rebuild Network Connection

```bash
# Stop services
docker-compose down

# Remove network
docker network rm pokesim-network

# Restart (recreates network)
docker-compose up -d
```

### Check Docker Logs

```bash
# PokeSim logs
docker logs pokesim -f

# Nginx Proxy Manager logs
docker logs nginx-proxy-manager -f

# Follow specific errors
docker logs pokesim | grep -i "stream\|error"
```

## Common Proxy Manager Settings

### Settings That Break Preview

❌ **DO NOT USE**:
```
- Caching enabled
- Gzip compression
- IP whitelist (unless needed)
- Client certificates
```

### Settings That Fix Preview

✅ **MUST USE**:
```
- proxy_buffering off
- proxy_set_header X-Accel-Buffering no
- Forward correct hostname/port
- HTTPS with proper certificate
```

## Testing Checklist

Before reporting an issue, verify:

- [ ] PokeSim is running: `docker ps | grep pokesim`
- [ ] Health check passes: `curl http://pokesim:8000/health/ready`
- [ ] Adventure is started and in gameplay
- [ ] Direct preview works: `http://pokesim-server:8000/game-id`
- [ ] Nginx PM is running: `docker ps | grep nginx`
- [ ] Proxy host is configured correctly
- [ ] Proxy buffering is disabled
- [ ] Browser console has no errors (F12)
- [ ] Network tab shows successful stream connection (F12)
- [ ] Firewall allows port 8000 (if not Docker)

## Getting Help

If preview still doesn't work after troubleshooting:

1. **Collect diagnostics**:
   ```bash
   curl -v http://pokesim-server:8000/health/ready
   docker logs pokesim | tail -50
   docker logs nginx-proxy-manager | tail -50
   ```

2. **Check detailed config**:
   ```bash
   docker exec nginx-proxy-manager cat /etc/nginx/conf.d/default.conf
   ```

3. **Review logs in Nginx PM web UI**:
   - Access admin panel at http://localhost:81
   - Check logs for errors

4. **Test stream endpoint directly**:
   ```bash
   curl -i http://pokesim-server:8000/adventure-id/stream
   ```

## See Also

- [NGINX_PROXY_SETUP.md](NGINX_PROXY_SETUP.md) - Detailed proxy configuration
- [README.md](README.md) - General setup instructions
- Docker logs with `docker logs <container> -f` for real-time debugging
