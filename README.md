```
   🚧 ┌─────────────────────────────────────────────┐ 🚧
      │                                               │
      │      🍳  SOMETHING IS COOKING HERE  🍳        │
      │                                               │
      │   AI-Powered Investor Intelligence Platform   │
      │                                               │
      │   Status: chunks chunking, tables behaving,   │
      │   embeddings embedding (mostly), dashboard    │
      │   still just a twinkle in a Jupyter cell.     │
      │                                               │
      └─────────────────────────────────────────────┘
```

# 📈 Investor Intelligence Bot
### *"It reads 10-Ks so you don't have to cry over 120 pages of legal footnotes."*

---

## ⚠️ Construction Notice

This repo is currently powered by:
- 🧠 A RAG pipeline
- ☕ Vibes
- 🐛 A surprising number of `<br>` tags that refused to leave quietly
- 🙏 The unwavering hope that Apple's net income shows up on the first try

**Do not feed the chatbot after midnight.** It gets hallucinate-y.

---

## 🗺️ What This Thing Does (Or Will Do, Soon™)

| Feature | Status |
|---|---|
| Upload a 10-K | ✅ Works |
| PDF → Markdown | ✅ Works (tables mostly behave now) |
| Chunking that doesn't chop a table in half | ✅ Works (RIP look-ahead, you tried) |
| Chatbot that actually answers "what was net income?" | 🔧 Debugging in progress — currently 2-for-2 on root causes found |
| KPI Dashboard | 🐣 Egg stage |
| Deployment | 👀 Somewhere on the horizon |
| Multi-company comparison | 📦 v2, ask again later |

---

## 🕵️ Known Suspects Currently Under Investigation

- Why did the caption rank #4 and the actual numbers rank #47? *(We found out. It was rude.)*
- 256 tokens walked into a table and only half walked out.
- The embedding model has opinions about `base64` and it will tell you about them.

---

## 🍜 Recipe For This Project

```
1 part  10-K PDF
2 parts stubborn debugging
3 parts "wait, why is Tesla's Services table wrong"
1 dash  Evidence Units research paper (for legitimacy)
∞       patience
```
Simmer slowly. Do not rush the chunking step — it will curdle.

---

## 🚦 Contributing / Poking Around

If you're a hiring manager reading this: yes, the bugs are documented on purpose.
See [`journey.md`](./journey.md) for the full soap opera — plot twists, root
causes, and one embedding model that really did not want to give us `float`
values without being asked nicely.

If you're future-me reading this after a long break: hi. Re-read `journey.md`
before touching `chunking.py`. Trust me.

---

*Built with 🐍 Python, 🧩 ChromaDB, 🦙 Groq, and an above-average tolerance
for staring at markdown tables until they make sense.*
