# Security Cleanup Instructions

## ⚠️ CRITICAL: Sensitive Data Found in Git History

This repository contains sensitive information that has been committed to git history:
- **Email addresses** (including personal emails)
- **Stripe subscription/customer IDs**
- **Screenshots** that may contain sensitive UI information
- **Payment-related logs** with subscription details

## Immediate Actions Taken

✅ Added `attached_assets/` to `.gitignore`  
✅ Removed `attached_assets/` from git tracking (files still exist locally)

## Required: Remove from Git History

The files are still in git history and visible to anyone who clones the repository. You **MUST** remove them from history.

### Option 1: Using git filter-repo (Recommended)

```bash
# Install git-filter-repo if not already installed
# macOS: brew install git-filter-repo
# Or: pip install git-filter-repo

# Remove attached_assets/ from entire git history
git filter-repo --path attached_assets --invert-paths

# Force push to remote (WARNING: This rewrites history)
git push origin --force --all
git push origin --force --tags
```

### Option 2: Using BFG Repo-Cleaner (Alternative)

```bash
# Download BFG from https://rtyley.github.io/bfg-repo-cleaner/

# Remove attached_assets/ directory
java -jar bfg.jar --delete-folders attached_assets

# Clean up
git reflog expire --expire=now --all
git gc --prune=now --aggressive

# Force push
git push origin --force --all
```

### Option 3: Manual git filter-branch (If above tools unavailable)

```bash
git filter-branch --force --index-filter \
  "git rm -rf --cached --ignore-unmatch attached_assets" \
  --prune-empty --tag-name-filter cat -- --all

# Clean up
git reflog expire --expire=now --all
git gc --prune=now --aggressive

# Force push
git push origin --force --all
git push origin --force --tags
```

## ⚠️ Important Warnings

1. **This rewrites git history** - All commit SHAs will change
2. **Force push required** - You'll need to force push to update the remote
3. **Team coordination** - If others have cloned the repo, they'll need to re-clone
4. **Backup first** - Make sure you have a backup before proceeding
5. **GitHub/GitLab** - The files may still be cached on GitHub/GitLab. After force pushing, you may need to contact support to clear caches.

## After Cleanup

1. Verify the files are gone:
   ```bash
   git log --all --full-history -- attached_assets/
   ```
   (Should return no results)

2. Check for any remaining sensitive data:
   ```bash
   # Search for email addresses
   git log -p | grep -E "@.*\.(com|org|net|io)"
   
   # Search for Stripe IDs
   git log -p | grep -E "(sub_|cus_|evt_|price_)"
   ```

3. Consider rotating any exposed Stripe keys/IDs if they were sensitive

## Prevention

- ✅ `attached_assets/` is now in `.gitignore`
- Always review files before committing
- Use `git status` before `git add .`
- Consider using pre-commit hooks to scan for sensitive data

## Additional Notes

- The files still exist locally in `attached_assets/` - they're just not tracked by git anymore
- If you want to delete them locally too, you can: `rm -rf attached_assets/`
- Consider using tools like `git-secrets` or `truffleHog` to prevent future commits of sensitive data
