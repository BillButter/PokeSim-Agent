# Gemini Agent Troubleshooting Guide

## Problem: Gemini Shows Nothing on UI

If you select Gemini mode but see no agent output, this guide will help you diagnose and fix the issue.

### Diagnostic Checklist

#### 1. Verify GEMINI_API_KEY is Set

**Most Likely Issue:** `GEMINI_API_KEY` environment variable is not set in your deployment.

```bash
# Check if GEMINI_API_KEY is set
echo $GEMINI_API_KEY

# If empty or not found, that's the problem!
```

**Fix:**
```bash
# Set GEMINI_API_KEY before running PokeSim
export GEMINI_API_KEY="your-google-api-key-here"
```

#### 2. Check What UI Shows

When you select Gemini mode:
- If you see **"Error" status** with message "Set GEMINI_API_KEY...", the API key is not configured
- If you see **nothing at all**, check below for other issues
- If you see **"Thinking" or "Acting"**, Gemini is working!

#### 3. Verify Mode Switch Worked

Open browser DevTools and check the Network tab:
1. Select Gemini mode in Adventure Settings
2. Look for `POST /api/v1/adventures/...` request
3. Check the request body includes `"ai_mode": "gemini"`
4. Check the response

#### 4. Check /api/state Endpoint

Open your browser console and run:
```javascript
fetch('/api/state').then(r => r.json()).then(d => {
  console.log('ai_mode:', d.ai_mode);
  console.log('agent:', d.agent);
});
```

**What should appear:**
```javascript
ai_mode: "gemini"
agent: { 
  status: "error" OR "thinking" OR "acting",
  error: "Set GEMINI_API_KEY..." (if unconfigured)
  // other fields...
}
```

**If `agent` is null:** The runner was not created. Check logs for errors.

#### 5. Check Server Logs

Look for messages like:
```
WARNING Set GEMINI_API_KEY to use the Gemini agent.
```

This means the config is not set.

### Possible Causes

#### Cause 1: GEMINI_API_KEY Not Set (90% probability)

**Symptoms:**
- Agent panel shows but displays error
- Error message: "Set GEMINI_API_KEY to use the Gemini agent"

**Fix:**
```bash
# Add to your environment before running PokeSim
export GEMINI_API_KEY="AIza..."

# Or in Docker:
docker run -e GEMINI_API_KEY="AIza..." ...

# Or in docker-compose.yml:
environment:
  GEMINI_API_KEY: "AIza..."
```

#### Cause 2: Wrong Gemini Model Specified

**Symptoms:**
- Mode appears to switch
- Status shows "error" with API error (403, 404, etc.)

**Fix:**
```bash
# Default is fine:
export GEMINI_MODEL="gemini-2.5-flash"

# Or use another supported model
export GEMINI_MODEL="gemini-1.5-flash"
```

#### Cause 3: Custom Gemini Base URL Wrong

**Symptoms:**
- Status shows "error" with connection timeout

**Fix:**
```bash
# Only set if using custom endpoint
# Default should work:
export GEMINI_BASE_URL="https://generativelanguage.googleapis.com/v1beta/openai"
```

#### Cause 4: Old Deployment Still Running

**Symptoms:**
- Applied fixes but nothing changed
- The display logic never activates

**Fix:**
```bash
# Ensure you're running latest version
# Redeploy with v0.5.3-agent-gemini-fix tag or later

# Docker:
docker pull ghcr.io/billbutter/pokesim-agent:latest
docker run ... ghcr.io/billbutter/pokesim-agent:latest
```

#### Cause 5: JavaScript Panel Not Showing

**Symptoms:**
- Agent panel element is completely hidden

**Fix:**
Check `pokesim/web/static/app.js` line 521:
```javascript
panel.hidden = !(aiMode === 'vision' || aiMode === 'gemini')
```

This should show panel for both 'vision' and 'gemini' modes. If aiMode is not showing as 'gemini', the mode switch failed.

### How To Get It Working

#### Step 1: Set GEMINI_API_KEY

Get a free API key from: https://ai.google.dev/

```bash
export GEMINI_API_KEY="AIza..."
```

#### Step 2: Restart PokeSim

Stop and restart your PokeSim instance with the new environment variable.

#### Step 3: Select Gemini Mode

In Adventure Settings, select "Gemini agent · Google"

#### Step 4: Verify It Works

You should see:
- Agent panel appears
- Status shows "Thinking" or "Acting" (not "Error")
- Plan and thoughts update

### What Each Status Means

| Status | Meaning | Next Steps |
|--------|---------|-----------|
| **Thinking** | Gemini is analyzing the screen | Wait, it will soon act |
| **Acting** | Gemini just made a decision | Watch it execute |
| **Error** | Something is wrong | Check error message |
| **Idle** | Agent is not active | Check if game is paused |
| **Starting** | Agent just started | Wait a moment |

### Error Messages

| Error | Cause | Fix |
|-------|-------|-----|
| "Set GEMINI_API_KEY..." | API key not configured | Set GEMINI_API_KEY env var |
| "HTTP 401 Unauthorized" | Invalid API key | Check API key is correct |
| "HTTP 403 Forbidden" | API key lacks permissions | Regenerate API key with proper scopes |
| "HTTP 429 Too Many Requests" | Rate limited | Wait, then retry |
| "Connection timeout" | Can't reach API | Check internet, firewall |

### Testing Locally

To test Gemini agent locally without needing a real game:

```bash
# Set API key
export GEMINI_API_KEY="your-key"

# Run tests
cd /home/butter/dev/PokeSim-Agent
pytest tests/test_gemini_*.py -v
```

All tests should pass if configuration is correct.

### What Was Fixed

**Previous Bug (v0.5.3-agent-display-fixed):**
- emulator.status() only returned agent info for 'vision' mode
- Gemini and ML modes ran but UI showed nothing

**Current Fix (v0.5.3-agent-gemini-fix):**
- set_ai_mode() only started runner for 'vision' mode
- Gemini and ML modes never had runners created
- Now all three modes properly initialize

Together these fixes mean:
1. Runner is created when mode selected ✓
2. Runner processes game state ✓
3. Status is returned to API ✓
4. UI displays the info ✓

### If It Still Doesn't Work

1. Check server logs for errors
2. Verify GEMINI_API_KEY is actually set: `echo $GEMINI_API_KEY`
3. Check /api/state returns agent object (not null)
4. Verify browser gets the response (DevTools Network tab)
5. Check JavaScript console for errors
6. Report issue with:
   - Version: `git log -1 --oneline`
   - Environment: Docker/bare metal/other
   - GEMINI_API_KEY: Set? (value not needed, just yes/no)
   - Game: Gen I or Gen II?
   - Error message from UI or logs
