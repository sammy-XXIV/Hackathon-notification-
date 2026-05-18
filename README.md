# Hackathon Tracker Bot

A Telegram bot that tracks hackathon deadlines and sends a daily digest at 6am WAT.

## Features

- Add hackathons with a name and end date
- View all tracked hackathons with days remaining
- Remove hackathons from the list
- Daily digest sent automatically at 6am WAT
- Warns when a hackathon is ending within 7 days
- Auto-cleans hackathons that ended more than 1 day ago

## Commands

| Command | Description |
|---------|-------------|
| `/start` | Show available commands |
| `/add` | Add a new hackathon |
| `/list` | View all hackathons and their deadlines |
| `/remove` | Remove a hackathon |
| `/cancel` | Cancel an ongoing add/remove operation |

## Setup

### Prerequisites

- Python 3.10+
- A Telegram bot token from [@BotFather](https://t.me/BotFather)
- A [Supabase](https://supabase.com) project

### Supabase Table

Create a `hackathons` table with the following columns:

| Column | Type |
|--------|------|
| `id` | int8 (primary key) |
| `name` | text |
| `end_date` | date |
| `added_by` | text |

### Environment Variables

| Variable | Description |
|----------|-------------|
| `BOT_TOKEN` | Telegram bot token |
| `CHAT_ID` | Telegram chat ID to send the daily digest to |
| `SUPABASE_URL` | Your Supabase project URL |
| `SUPABASE_KEY` | Your Supabase anon/service key |

### Run Locally

```bash
pip install -r requirements.txt
export BOT_TOKEN=...
export CHAT_ID=...
export SUPABASE_URL=...
export SUPABASE_KEY=...
python bot.py
```

## Deployment (Railway)

1. Push this repo to GitHub
2. Create a new project on [Railway](https://railway.app) and connect the repo
3. Set the environment variables in the Railway dashboard
4. Railway will build and deploy automatically using the `railway.toml` config
