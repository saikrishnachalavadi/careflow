# Push CareFlow to GitHub

Your repo: **https://github.com/saikrishnachalavadi/careflow**

Run these in the project folder (`~/PycharmProjects/careflow`) in a terminal.

## If you haven't pushed yet (first time)

```bash
cd ~/PycharmProjects/careflow

# If git is not initialized:
git init
git remote add origin https://github.com/saikrishnachalavadi/careflow.git

# Stage everything (.env is ignored by .gitignore)
git add -A
git status   # confirm .env is NOT listed

# Commit (if you get "trailer" error, try: git commit -m "Initial commit")
git commit -m "Initial commit: CareFlow POC"

# Push (use main if your default branch is main)
git branch -M main
git push -u origin main
```

If your GitHub default branch is **master** instead of main:

```bash
git push -u origin master
```

## Authentication

- **HTTPS:** GitHub will ask for username and password. For password, use a [Personal Access Token](https://github.com/settings/tokens) (not your GitHub password).
- **SSH:** If you use SSH keys, change the remote and push:
  ```bash
  git remote set-url origin git@github.com:saikrishnachalavadi/careflow.git
  git push -u origin main
  ```

## After pushing

1. Open **https://dashboard.render.com** → New → Web Service.
2. Connect **saikrishnachalavadi/careflow**.
3. Add env vars: `GOOGLE_API_KEY`, `GOOGLE_MAPS_API_KEY`.
4. Deploy. Your app: `https://<service-name>.onrender.com/ui`
