# How to Get X API Credentials for Replit Secrets

This guide walks you through obtaining all four X API credentials needed for your Replit secrets.

## Prerequisites

1. ✅ You have an X (Twitter) account (@societyspeaksio)
2. ✅ You've completed the Developer Agreement & Policy form
3. ✅ You have access to https://developer.x.com/portal

---

## Step-by-Step Guide

### Step 1: Access the Developer Portal

1. Go to **https://developer.x.com/portal**
2. Log in with your X account (@societyspeaksio)
3. You should see your developer dashboard

### Step 2: Create or Select Your App

1. In the developer portal, look for **"Projects & Apps"** or **"Overview"** section
2. If you don't have an app yet:
   - Click **"Create App"** or **"New App"**
   - Give it a name (e.g., "Society Speaks")
   - Select the app type (usually "Production" or "Hobbyist")
   - Accept the terms
3. If you already have an app, select it from the list

### Step 3: Get Consumer API Keys (API Key & API Secret)

These are also called "Consumer Keys" or "App Keys":

1. In your app's dashboard, look for the **"Keys and tokens"** tab or section
2. You'll see:
   - **API Key** (this is your `X_API_KEY`)
   - **API Key Secret** (this is your `X_API_SECRET`)
3. **Important**: 
   - If the API Key Secret is hidden, click **"Regenerate"** or **"Show"** to reveal it
   - **Copy both values immediately** - you may not be able to see the secret again!

### Step 4: Generate Access Token & Access Token Secret

These are user-specific tokens that allow your app to post on behalf of your account:

1. Still in the **"Keys and tokens"** section
2. Scroll down to **"Access Token and Secret"** or **"User authentication settings"**
3. If you see **"Generate"** or **"Create"** button:
   - Click it to generate new tokens
   - You may need to set permissions (select "Read and Write" for posting)
4. You'll see:
   - **Access Token** (this is your `X_ACCESS_TOKEN`)
   - **Access Token Secret** (this is your `X_ACCESS_TOKEN_SECRET`)
5. **Copy both values immediately** - secrets are only shown once!

### Step 5: Set App Permissions

Make sure your app has the right permissions:

1. Go to **"Settings"** or **"App permissions"** in your app dashboard
2. Set permissions to **"Read and Write"** (required for posting tweets)
3. Save the changes

### Step 6: Add to Replit Secrets

Now add all four values to your Replit secrets:

1. In Replit, open your project
2. Click the **🔒 Secrets** icon in the left sidebar (or go to Tools → Secrets)
3. Add each secret one by one:

   ```
   Key: X_API_KEY
   Value: [paste your API Key from Step 3]
   ```

   ```
   Key: X_API_SECRET
   Value: [paste your API Key Secret from Step 3]
   ```

   ```
   Key: X_ACCESS_TOKEN
   Value: [paste your Access Token from Step 4]
   ```

   ```
   Key: X_ACCESS_TOKEN_SECRET
   Value: [paste your Access Token Secret from Step 4]
   ```

4. Click **"Add secret"** for each one
5. **Important**: Make sure the key names match exactly (case-sensitive):
   - `X_API_KEY`
   - `X_API_SECRET`
   - `X_ACCESS_TOKEN`
   - `X_ACCESS_TOKEN_SECRET`

### Step 7: Verify the Setup

1. Restart your Replit app (or it will pick up new secrets automatically)
2. Check your app logs - you should see no warnings about missing X API credentials
3. In your trending topics dashboard, check the X status - it should show as "configured"
4. Try publishing a test discussion to verify posting works

---

## Troubleshooting

### "I can't see my API Key Secret"
- Click **"Regenerate"** to create a new one
- Copy it immediately - secrets are only shown once

### "I can't generate Access Tokens"
- Make sure your app has **"Read and Write"** permissions enabled
- You may need to regenerate your Consumer Keys first
- Some apps require OAuth 1.0a setup - follow X's OAuth flow if prompted

### "My app says 'Read only'"
- Go to **Settings** → **App permissions**
- Change to **"Read and Write"**
- You may need to regenerate your Access Tokens after changing permissions

### "I lost my secrets"
- You'll need to regenerate them in the X Developer Portal
- **Consumer Keys**: Can be regenerated (old ones will stop working)
- **Access Tokens**: Can be regenerated (old ones will stop working)
- After regenerating, update your Replit secrets with the new values

### "Authentication error when posting"
- Double-check all four secrets are set correctly in Replit
- Make sure there are no extra spaces or newlines in the secret values
- Verify your app has "Read and Write" permissions
- Try regenerating the Access Token and Access Token Secret

---

## Security Best Practices

1. ✅ **Never commit secrets to git** - They're already in `.gitignore`
2. ✅ **Use Replit Secrets** - Don't hardcode in your code
3. ✅ **Regenerate if compromised** - If you suspect a leak, regenerate all keys
4. ✅ **Keep secrets private** - Don't share them in screenshots or messages
5. ✅ **Use environment variables** - Your code already does this correctly via `os.getenv()`

---

## Quick Reference

| Replit Secret Name | X Developer Portal Location | What It's Called There |
|-------------------|---------------------------|----------------------|
| `X_API_KEY` | Keys and tokens → API Key | API Key / Consumer Key |
| `X_API_SECRET` | Keys and tokens → API Key Secret | API Key Secret / Consumer Secret |
| `X_ACCESS_TOKEN` | Keys and tokens → Access Token | Access Token |
| `X_ACCESS_TOKEN_SECRET` | Keys and tokens → Access Token Secret | Access Token Secret |

---

## Need Help?

- X Developer Documentation: https://developer.x.com/en/docs
- X Developer Support: https://developer.x.com/en/portal/support
- Your app dashboard: https://developer.x.com/portal
