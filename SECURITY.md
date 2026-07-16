# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in this project, please **do not** open a public GitHub issue.

Instead, report it privately via one of these methods:
- Open a [GitHub Security Advisory](https://docs.github.com/en/code-security/security-advisories) on this repo
- Or email the maintainer directly (see profile)

We will respond within 48 hours and coordinate a fix before any public disclosure.

---

## Secret Management

This project follows strict secret hygiene:

### What is NEVER committed to Git
| File | Why |
|---|---|
| `.env` | Contains live API keys and secrets |
| `users.json` | Contains password hashes for dashboard login |
| `*.db` | SQLite database with real event data |
| `*.log` | Runtime logs that may contain PII |
| `chat_history.json` | AI conversation history |
| `seen_ids.json` | Runtime state file |
| `training_signals.jsonl` | Runtime training data |

All of the above are covered by `.gitignore`.

### How secrets are loaded
All secrets are loaded exclusively via environment variables using `python-dotenv`:

```python
from dotenv import load_dotenv
import os

load_dotenv()
API_KEY = os.getenv("DASHSCOPE_API_KEY")
```

**Zero hardcoded credentials exist in any source file.**

### Setting up secrets locally

```bash
cp .env.example .env
# Edit .env with your real credentials — never commit it
```

---

## Supported Versions

| Version | Supported |
|---|---|
| `main` branch | ✅ |
| Older branches | ❌ |

---

## API Key Rotation

If you believe your `DASHSCOPE_API_KEY` or any other secret may have been exposed:

1. Go to [Alibaba Cloud DashScope Console](https://dashscope.console.aliyun.com/) → API Keys
2. **Revoke the compromised key immediately**
3. Generate a new key
4. Update your local `.env` file

> [!WARNING]
> Git history is permanent. If a secret was ever committed (even briefly), consider it compromised even after removal. Always rotate immediately.
