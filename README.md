# Sun Devil Circles ☀️😈

**Live Platform**: [https://sun-devil-circle.vercel.app/](https://sun-devil-circle.vercel.app/)

A peer support platform for ASU international freshmen, featuring AI-powered personalized suggestions and empathetic support. It matches students into small, private peer circles for non-clinical, trust-based support, focusing on transition challenges like homesickness and culture shock.

### Origin & Recognition

SunDevil Circles was created at the [hackathon name] at Arizona State University in [Month Year], where it was awarded [brief award description]. It is a guided peer-connection platform for international freshmen to reduce loneliness through small, private peer circles focused on transition challenges (such as homesickness and culture shock), with clear escalation pathways for more serious concerns.

You can read the official write-up by the organizers here: [PASTE ORGANIZER ARTICLE LINK HERE – leave as a placeholder for me if you do not know it].

## Features
- **Semantic Matching**: Connects students with peers and groups based on shared challenges, interests, and profile compatibility.
- **AI Support**: Uses Cerebras AI (Llama 3.3 70B) to provide empathetic responses and personalized resource suggestions.
- **Topic-Based Chat**: Real-time group chats with AI moderation and message editing/deleting.
- **Resource Hub**: Curated ASU resources and support options.
- **25+ Support Groups**: Pre-configured peer support groups covering emotional wellness, academic challenges, identity communities, and daily functioning. Includes groups for anxiety, depression, LGBTQ+ students, international students, and more.
- **Smart Search**: Search groups by name, description, or topic labels for easier discovery.
- **Best Match Sorting**: Groups and peers are ranked by compatibility based on profile overlap, shared challenges, and semantic similarity.

## 🚀 Quick Start

The platform is deployed and live at: **[https://sun-devil-circle.vercel.app/](https://sun-devil-circle.vercel.app/)**

---

## 💻 Local Development

If you prefer to run the application locally for development:

1. **Clone the repository**: 
   ```bash
   git clone https://github.com/Rudheer127/Sun-Devil-Circle.git
   cd Sun-Devil-Circle
   ```
2. **Set up a virtual environment** (recommended):
   ```bash
   python -m venv venv
   # macOS/Linux: source venv/bin/activate
   # Windows: .\venv\Scripts\activate
   ```
3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```
4. **Run the application**:
   ```bash
   python app.py
   ```

## 🔑 AI Configuration

The application is pre-configured with a default API key for the Cerebras AI features, so **it works out of the box**.

If you wish to use your own API key, you can set an environment variable:
```bash
export CEREBRAS_API_KEY="your-api-key-here"
```

## 🛠 Tech Stack
- **Backend**: Flask (Python)
- **Database**: SQLite
- **AI**: Cerebras Cloud SDK (Llama 3.3 70B)
- **Frontend**: HTML5, CSS3, Vanilla JavaScript

### Authors

- Rudheer Reddy Chintakuntla (primary author, GitHub: @Rudheer127)
