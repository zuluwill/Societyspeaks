# Quick Steps Based on Your Current Screen

## Step 1: Click "Keys and tokens" Tab
You're currently on the "Settings" tab. Click the **"Keys and tokens"** tab right next to it.

## Step 2: Find Your Consumer Keys
In the "Keys and tokens" tab, you should see:
- **API Key** → This is your `X_API_KEY`
- **API Key Secret** → This is your `X_API_SECRET`

**Action**: Copy both of these values. If the API Key Secret is hidden, click "Regenerate" or "Show" to reveal it.

## Step 3: Generate Access Tokens
Still in the "Keys and tokens" tab, look for:
- **Access Token** → This is your `X_ACCESS_TOKEN`
- **Access Token Secret** → This is your `X_ACCESS_TOKEN_SECRET`

**If you don't see these:**
- Look for a "Generate" or "Create" button
- You may need to set app permissions to "Read and Write" first (go back to Settings tab)
- Some apps require OAuth setup - if prompted, follow the OAuth 1.0a flow

## Step 4: Set App Permissions (if needed)
If you can't generate access tokens:
1. Go back to the **Settings** tab
2. Look for **"App permissions"** or **"Read and Write"** settings
3. Set permissions to **"Read and Write"** (required for posting)
4. Save changes
5. Go back to "Keys and tokens" and try generating tokens again

## Step 5: Add to Replit Secrets
Once you have all 4 values:
1. Open Replit Secrets (🔒 icon in left sidebar)
2. Add each secret:
   - `X_API_KEY` = [your API Key]
   - `X_API_SECRET` = [your API Key Secret]
   - `X_ACCESS_TOKEN` = [your Access Token]
   - `X_ACCESS_TOKEN_SECRET` = [your Access Token Secret]

---

**Next Action**: Click the **"Keys and tokens"** tab now!
