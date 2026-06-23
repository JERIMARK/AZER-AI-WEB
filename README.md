# MyAI Web App v3.0

Personal AI Assistant — Flask Web Edition

## Features
- 💬 Chat interface sa browser
- 📚 Knowledge Base (add, search, delete)
- 🧠 Memory Bank (auto-save ng mga sagot)
- 🌐 Internet Search (DuckDuckGo, Tavily, Brave, Google)
- 🤖 Groq AI integration
- 📜 Chat History
- ⚙️ Settings panel

---

## I-run sa Termux / Local

```bash
pip install -r requirements.txt
python app.py
```

Buksan ang browser: `http://localhost:5000`

---

## I-deploy sa Vercel

### Step 1: I-upload sa GitHub
```bash
git init
git add .
git commit -m "MyAI Web App v3.0"
git remote add origin https://github.com/USERNAME/myai.git
git push -u origin main
```

### Step 2: I-deploy
1. Pumunta sa **vercel.com**
2. Sign in gamit GitHub
3. Click **"Add New Project"**
4. Piliin ang repo mo
5. Click **"Deploy"**

### Step 3: I-set ang Environment Variable
Sa Vercel dashboard → Settings → Environment Variables:
```
GROQ_API_KEY = gsk_xxxxxxxxxxxxxxxxx
```

---

## I-deploy sa Render (Mas maganda para sa Python)

1. Pumunta sa **render.com**
2. New → Web Service
3. I-connect ang GitHub repo
4. Settings:
   - Build Command: `pip install -r requirements.txt`
   - Start Command: `gunicorn app:app`
5. I-add ang Environment Variable: `GROQ_API_KEY`

---

## Kumuha ng Libreng Groq API Key

1. Pumunta sa **console.groq.com**
2. Mag-sign up (libre)
3. Gumawa ng API key
4. I-paste sa Settings ng app

---

## Structure ng Files
```
myai_webapp/
├── app.py           ← Main Flask app
├── requirements.txt ← Dependencies
├── vercel.json      ← Vercel config
└── myai_data/       ← Auto-gagawin (data storage)
    ├── config/
    │   └── settings.json
    └── data/
        ├── memory.json
        ├── history.json
        └── knowledge/
```

> **Note:** Sa Vercel, hindi persistent ang file storage.
> Para sa permanent na storage, gumamit ng Render + disk,
> o i-upgrade sa database (SQLite, PostgreSQL).
