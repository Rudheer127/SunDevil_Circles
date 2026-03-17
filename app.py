"""
Sun Devil Circles - Peer Support Platform for ASU Students
Flask backend with in-memory storage, AI abstraction, and safety moderation.
"""

import os
import re
import secrets
import sqlite3
from urllib.parse import unquote
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, session, redirect, url_for, jsonify, g, flash
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
# Use a stable secret key for session persistence
app.secret_key = os.environ.get("SECRET_KEY", "sun-devil-circle-dev-key-2024")

# AI Configuration - Set defaults so AI works out of the box
if not os.environ.get("LIVE_AI"):
    os.environ["LIVE_AI"] = "1"

# Detect if running on Vercel (serverless) - use in-memory storage instead of SQLite
IS_VERCEL = os.environ.get("VERCEL") == "1" or os.environ.get("VERCEL_ENV") is not None

DATABASE = "auth.db"

# In-memory user storage for Vercel (serverless can't use SQLite files)
memory_users = {}  # {username: {id, username, password_hash, created_at}}
memory_profiles = {}  # {user_id: profile_dict}
memory_user_counter = 1  # Auto-increment ID



# -----------------------------------------------------------------------------
# Database Functions (SQLite for credentials only)
# -----------------------------------------------------------------------------

def get_db():
    """Get database connection."""
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db


@app.teardown_appcontext
def close_connection(exception):
    """Close database connection."""
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()


def init_db():
    """Initialize the database with users and profiles tables."""
    with app.app_context():
        db = get_db()
        db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        ''')
        db.execute('''
            CREATE TABLE IF NOT EXISTS profiles (
                user_id INTEGER PRIMARY KEY,
                display_name TEXT,
                gender TEXT DEFAULT '',
                preferred_language TEXT DEFAULT '',
                primary_challenge TEXT DEFAULT '',
                support_style TEXT DEFAULT 'mixed',
                support_topics TEXT DEFAULT '',
                private_topics TEXT DEFAULT '',
                languages TEXT DEFAULT '',
                cultural_background TEXT DEFAULT '',
                onboarding_complete INTEGER DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        # Migrate existing tables to add new columns if they don't exist
        try:
            db.execute('ALTER TABLE profiles ADD COLUMN support_topics TEXT DEFAULT ""')
        except:
            pass
        try:
            db.execute('ALTER TABLE profiles ADD COLUMN private_topics TEXT DEFAULT ""')
        except:
            pass
        try:
            db.execute('ALTER TABLE profiles ADD COLUMN languages TEXT DEFAULT ""')
        except:
            pass
        try:
            db.execute('ALTER TABLE profiles ADD COLUMN cultural_background TEXT DEFAULT ""')
        except:
            pass
        try:
            db.execute('ALTER TABLE profiles ADD COLUMN onboarding_complete INTEGER DEFAULT 0')
        except:
            pass
        try:
            db.execute('ALTER TABLE profiles ADD COLUMN graduation_year TEXT DEFAULT ""')
        except:
            pass
        try:
            db.execute('ALTER TABLE profiles ADD COLUMN degree_program TEXT DEFAULT ""')
        except:
            pass
        try:
            db.execute('ALTER TABLE profiles ADD COLUMN gender TEXT DEFAULT ""')
        except:
            pass
        db.commit()


def save_profile_to_db(user_id, profile_dict):
    """Save profile to database or in-memory storage."""
    if IS_VERCEL:
        # Use in-memory storage on Vercel
        memory_profiles[user_id] = profile_dict.copy()
        return
    
    # Use SQLite locally
    db = get_db()
    challenges = ','.join(profile_dict.get('primary_challenge', []))
    support_topics = ','.join(profile_dict.get('support_topics', []))
    private_topics = ','.join(profile_dict.get('private_topics', []))
    languages = ','.join(profile_dict.get('languages', []))
    cultural_background = ','.join(profile_dict.get('cultural_background', []))
    db.execute('''
        INSERT OR REPLACE INTO profiles 
        (user_id, display_name, gender, preferred_language, primary_challenge, support_style, support_topics, private_topics, languages, cultural_background, onboarding_complete, graduation_year, degree_program)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        user_id,
        profile_dict.get('display_name', ''),
        profile_dict.get('gender', ''),
        profile_dict.get('preferred_language', ''),
        challenges,
        profile_dict.get('support_style', 'mixed'),
        support_topics,
        private_topics,
        languages,
        cultural_background,
        1 if profile_dict.get('onboarding_complete') else 0,
        profile_dict.get('graduation_year', ''),
        profile_dict.get('degree_program', '')
    ))
    db.commit()


def load_profile_from_db(user_id):
    """Load profile from database or in-memory storage."""
    if IS_VERCEL:
        # Use in-memory storage on Vercel
        return memory_profiles.get(user_id)
    
    # Use SQLite locally
    db = get_db()
    row = db.execute('SELECT * FROM profiles WHERE user_id = ?', (user_id,)).fetchone()
    if row:
        challenges = row['primary_challenge'].split(',') if row['primary_challenge'] else []
        # Handle new columns that might not exist in older databases
        support_topics = []
        private_topics = []
        languages = []
        cultural_background = []
        onboarding_complete = False
        graduation_year = ''
        degree_program = ''
        try:
            support_topics = row['support_topics'].split(',') if row['support_topics'] else []
            private_topics = row['private_topics'].split(',') if row['private_topics'] else []
            languages = row['languages'].split(',') if row['languages'] else []
            cultural_background = row['cultural_background'].split(',') if row['cultural_background'] else []
            onboarding_complete = bool(row['onboarding_complete'])
        except:
            pass
        try:
            graduation_year = row['graduation_year'] or ''
            degree_program = row['degree_program'] or ''
        except:
            pass
        # Try to get gender field (may not exist in older databases)
        gender = ''
        try:
            gender = row['gender'] or ''
        except:
            pass
        return {
            'display_name': row['display_name'] or '',
            'gender': gender,
            'preferred_language': row['preferred_language'] or '',
            'primary_challenge': challenges,
            'support_style': row['support_style'] or 'mixed',
            'support_topics': support_topics,
            'private_topics': private_topics,
            'languages': languages,
            'cultural_background': cultural_background,
            'onboarding_complete': onboarding_complete,
            'graduation_year': graduation_year,
            'degree_program': degree_program
        }
    return None



def login_required(f):
    """Decorator to require login for routes."""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated_function


# -----------------------------------------------------------------------------
# In-Memory Storage
# -----------------------------------------------------------------------------

# Support topics taxonomy (used across onboarding, profile, filters, and groups)
SUPPORT_TOPIC_CATEGORIES = [
    (
        "Mental Health & Crisis",
        [
            ("suicide_self_harm", "🆘", "Suicide / self-harm"),
            ("crisis_panic", "🚨", "Crisis / panic attack"),
            ("depression", "🌧", "Depression"),
            ("anxiety", "😰", "Anxiety"),
            ("social_anxiety", "😳", "Social anxiety"),
            ("stress", "⚡", "Stress"),
            ("burnout", "🔥", "Burnout"),
            ("sleep_insomnia", "🌙", "Sleep problems / insomnia"),
            ("eating_disorders", "🍽", "Eating disorders / disordered eating"),
            ("body_image", "🪞", "Body image concerns"),
            ("trauma_ptsd", "🧩", "Trauma / PTSD"),
            ("grief_loss", "🕯", "Grief & loss"),
            ("anger_management", "🌋", "Anger management"),
            ("ocd", "🌀", "OCD"),
            ("phobias", "🕸", "Phobias"),
            ("bipolar", "⚖", "Bipolar disorder"),
            ("psychosis", "🧠", "Psychosis / schizophrenia-spectrum concerns"),
            ("substance_use", "🍺", "Substance use (alcohol/drugs)"),
            ("addiction", "🔗", "Addiction / dependence"),
            ("adhd", "🎯", "ADHD / attention & focus problems"),
            ("autism", "🧩", "Autism spectrum / neurodiversity support"),
        ],
    ),
    (
        "Relationships & Social",
        [
            ("relationship_issues", "💞", "Relationship issues"),
            ("breakups", "💔", "Breakups"),
            ("family_problems", "🏠", "Family problems"),
            ("roommate_conflict", "🛏", "Roommate conflict"),
            ("loneliness_isolation", "🌫", "Loneliness / isolation"),
            ("homesickness", "🧳", "Homesickness"),
            ("culture_shock", "🌍", "Culture shock / adjustment issues"),
            ("discrimination_bias", "⚠", "Discrimination / bias experiences"),
            ("identity_concerns", "🪪", "Identity concerns (sexuality / gender / faith)"),
            ("sexual_assault", "🛡", "Sexual assault / harassment"),
            ("dating_violence", "🧯", "Domestic/dating violence"),
            ("safety_concerns", "🚧", "Safety concerns / violence risk"),
        ],
    ),
    (
        "Academic & Career",
        [
            ("academic_problems", "📚", "Academic problems"),
            ("test_anxiety", "📝", "Test anxiety"),
            ("time_management", "⏰", "Time management / procrastination"),
            ("motivation_focus", "🧠", "Motivation / concentration problems"),
            ("career_stress", "🧭", "Career stress / \"no direction\""),
            ("financial_stress", "💰", "Financial stress"),
        ],
    ),
]

SUPPORT_TOPIC_INDEX = {
    topic_id: {"icon": icon, "label": label, "category": category}
    for category, topics in SUPPORT_TOPIC_CATEGORIES
    for topic_id, icon, label in topics
}

def normalize_topic_ids(topic_ids):
    """Return a clean list of topic ids."""
    legacy_map = {
        "loneliness": "loneliness_isolation",
        "academics": "academic_problems",
        "relationships": "relationship_issues",
        "identity": "identity_concerns",
        "finances": "financial_stress",
    }
    normalized = []
    for raw in topic_ids:
        if not raw:
            continue
        topic = raw.strip()
        topic = legacy_map.get(topic, topic)
        if topic in SUPPORT_TOPIC_INDEX:
            normalized.append(topic)
    return normalized

def get_topic_label(topic_id):
    """Get display label for a topic id."""
    info = SUPPORT_TOPIC_INDEX.get(topic_id)
    if info and info.get("label"):
        return info["label"]
    return str(topic_id) if topic_id else ""

def get_topic_labels(topic_ids):
    """Map topic ids to display labels."""
    return [label for label in (get_topic_label(t) for t in normalize_topic_ids(topic_ids)) if label]

# -----------------------------------------------------------------------------
# Preset Support Groups
# These are the default peer support groups available to all users.
# Groups are organized by category: core emotional, safety/higher-risk, 
# daily functioning, and identity-based communities.
# Each group has associated metadata (description, topics) defined in seed_group_meta().
# -----------------------------------------------------------------------------
PRESET_GROUPS = [
    # Mental Health & Crisis
    "🆘 Suicide / Self-harm Support",
    "🚨 Crisis / Panic Attack Support",
    "🌧 Depression Support",
    "😰 Anxiety Support",
    "😳 Social Anxiety Support",
    "⚡ Stress Management",
    "🔥 Burnout Recovery",
    "🌙 Sleep Problems / Insomnia",
    "🍽 Eating Disorders / Disordered Eating",
    "🪞 Body Image Concerns",
    "🧩 Trauma / PTSD Support",
    "🕯 Grief & Loss Support",
    "🌋 Anger Management",
    "🌀 OCD Support",
    "🕸 Phobias Support",
    "⚖ Bipolar Disorder Support",
    "🧠 Psychosis / Schizophrenia-spectrum Support",
    "🍺 Substance Use (Alcohol/Drugs)",
    "🔗 Addiction / Dependence Support",
    "🎯 ADHD / Attention & Focus Problems",
    "🧩 Autism Spectrum / Neurodiversity Support",
    # Relationships & Social
    "💞 Relationship Issues",
    "💔 Breakups Support",
    "🏠 Family Problems",
    "🛏 Roommate Conflict",
    "🌫 Loneliness / Isolation",
    "🧳 Homesickness Support",
    "🌍 Culture Shock / Adjustment Issues",
    "⚠ Discrimination / Bias Experiences",
    "🪪 Identity Concerns (Sexuality / Gender / Faith)",
    "🛡 Sexual Assault / Harassment Support",
    "🧯 Domestic/Dating Violence Support",
    "🚧 Safety Concerns / Violence Risk",
    # Academic & Career
    "📚 Academic Problems",
    "📝 Test Anxiety",
    "⏰ Time Management / Procrastination",
    "🧠 Motivation / Concentration Problems",
    "🧭 Career Stress / No Direction",
    "💰 Financial Stress",
]

# In-memory groups: { "topic": [ {"timestamp": str, "display_name": str, "text": str}, ... ] }
groups = {topic: [] for topic in PRESET_GROUPS}

# Group metadata
GROUP_TYPES = ["Peer Support", "Study/Accountability", "Identity/Community", "Social"]
group_meta = {}
group_members = {}
group_requests = {}
group_invitations = {}  # { user_id: [ {group_name, inviter_id, timestamp}, ... ] }
group_member_dates = {}  # { group_name: { user_id: join_timestamp } }

def seed_group_meta():
    """Seed group metadata for preset groups."""
    # Unique descriptions for each preset group
    group_descriptions = {
        # Mental Health & Crisis
        "🆘 Suicide / Self-harm Support": "A safe, peer-supported space to talk about difficult thoughts. Not for emergencies - if you're in immediate danger, use the 24/7 crisis resources.",
        "🚨 Crisis / Panic Attack Support": "For students experiencing panic attacks or crisis moments. Share grounding techniques and support each other.",
        "🌧 Depression Support": "For students experiencing sadness, low energy, or feeling down. Connect with others who understand.",
        "😰 Anxiety Support": "A space for students dealing with anxiety and constant worry. Share coping strategies and feel less alone.",
        "😳 Social Anxiety Support": "Struggling with social situations? Connect with others who understand social anxiety.",
        "⚡ Stress Management": "Feeling overwhelmed? Share stress management tips and support each other through tough times.",
        "🔥 Burnout Recovery": "Feeling exhausted and drained? Share experiences and steps to recover from burnout.",
        "🌙 Sleep Problems / Insomnia": "Struggling to fall or stay asleep? Share tips and routines for better rest.",
        "🍽 Eating Disorders / Disordered Eating": "A supportive space for those navigating eating challenges. Share experiences and coping strategies.",
        "🪞 Body Image Concerns": "Struggling with body image? Connect with peers who understand and support each other.",
        "🧩 Trauma / PTSD Support": "A trauma-aware space for students living with past trauma. Focus on coping and healing together.",
        "🕯 Grief & Loss Support": "Processing loss or grief? Connect with others who understand and share your journey.",
        "🌋 Anger Management": "Working on managing anger? Share strategies and support each other.",
        "🌀 OCD Support": "Living with OCD? Connect with peers who understand and share coping strategies.",
        "🕸 Phobias Support": "Dealing with phobias? Share experiences and support each other in overcoming fears.",
        "⚖ Bipolar Disorder Support": "A space for students managing bipolar disorder. Share experiences and support.",
        "🧠 Psychosis / Schizophrenia-spectrum Support": "A supportive space for students with psychosis or schizophrenia-spectrum experiences.",
        "🍺 Substance Use (Alcohol/Drugs)": "For students wanting to talk about substance use and finding healthier coping strategies.",
        "🔗 Addiction / Dependence Support": "Working through addiction or dependence? Connect with peers on similar journeys.",
        "🎯 ADHD / Attention & Focus Problems": "Trouble focusing or finishing tasks? Connect with others navigating ADHD and attention challenges.",
        "🧩 Autism Spectrum / Neurodiversity Support": "A welcoming space for neurodivergent students to connect and share experiences.",
        # Relationships & Social
        "💞 Relationship Issues": "Navigating relationship challenges? Share experiences and get peer support.",
        "💔 Breakups Support": "Going through a breakup? Connect with others who understand and heal together.",
        "🏠 Family Problems": "Dealing with family challenges? Share experiences and find support from peers.",
        "🛏 Roommate Conflict": "Roommate issues? Share tips and strategies for living together peacefully.",
        "🌫 Loneliness / Isolation": "Feeling lonely or isolated? Connect with others seeking community and belonging.",
        "🧳 Homesickness Support": "Missing home? Connect with others who understand being far from family and loved ones.",
        "🌍 Culture Shock / Adjustment Issues": "Navigating cultural transitions? Share experiences and tips for adjusting.",
        "⚠ Discrimination / Bias Experiences": "Experienced discrimination or bias? Find solidarity and support here.",
        "🪪 Identity Concerns (Sexuality / Gender / Faith)": "Exploring your identity? A safe space to discuss sexuality, gender, faith, and more.",
        "🛡 Sexual Assault / Harassment Support": "A trauma-informed space for survivors of sexual assault or harassment. You're not alone.",
        "🧯 Domestic/Dating Violence Support": "Navigating domestic or dating violence? Find support and resources here.",
        "🚧 Safety Concerns / Violence Risk": "Concerned about safety or violence? Get peer support and resources.",
        # Academic & Career
        "📚 Academic Problems": "Struggling with coursework or academics? Share strategies and support each other.",
        "📝 Test Anxiety": "Dealing with test anxiety? Share tips and coping strategies with peers.",
        "⏰ Time Management / Procrastination": "Trouble managing time or procrastinating? Connect with others working on these skills.",
        "🧠 Motivation / Concentration Problems": "Low motivation or trouble concentrating? Share strategies and support.",
        "🧭 Career Stress / No Direction": "Feeling lost about career direction? Explore your path with peer support.",
        "💰 Financial Stress": "Dealing with money worries? Find support and share resources with peers.",
    }
    
    # Map group names to their associated topic IDs for filtering
    group_topics = {
        # Mental Health & Crisis
        "🆘 Suicide / Self-harm Support": ["suicide_self_harm", "crisis_panic", "depression"],
        "🚨 Crisis / Panic Attack Support": ["crisis_panic", "anxiety", "stress"],
        "🌧 Depression Support": ["depression", "motivation_focus", "loneliness_isolation"],
        "😰 Anxiety Support": ["anxiety", "stress", "crisis_panic"],
        "😳 Social Anxiety Support": ["social_anxiety", "anxiety", "loneliness_isolation"],
        "⚡ Stress Management": ["stress", "burnout", "anxiety"],
        "🔥 Burnout Recovery": ["burnout", "stress", "motivation_focus"],
        "🌙 Sleep Problems / Insomnia": ["sleep_insomnia", "stress", "anxiety"],
        "🍽 Eating Disorders / Disordered Eating": ["eating_disorders", "body_image", "anxiety"],
        "🪞 Body Image Concerns": ["body_image", "eating_disorders", "anxiety"],
        "🧩 Trauma / PTSD Support": ["trauma_ptsd", "anxiety", "depression"],
        "🕯 Grief & Loss Support": ["grief_loss", "depression", "loneliness_isolation"],
        "🌋 Anger Management": ["anger_management", "stress", "relationship_issues"],
        "🌀 OCD Support": ["ocd", "anxiety", "stress"],
        "🕸 Phobias Support": ["phobias", "anxiety", "stress"],
        "⚖ Bipolar Disorder Support": ["bipolar", "depression", "anxiety"],
        "🧠 Psychosis / Schizophrenia-spectrum Support": ["psychosis", "anxiety", "depression"],
        "🍺 Substance Use (Alcohol/Drugs)": ["substance_use", "addiction", "stress"],
        "🔗 Addiction / Dependence Support": ["addiction", "substance_use", "stress"],
        "🎯 ADHD / Attention & Focus Problems": ["adhd", "time_management", "motivation_focus"],
        "🧩 Autism Spectrum / Neurodiversity Support": ["autism", "identity_concerns", "social_anxiety"],
        # Relationships & Social
        "💞 Relationship Issues": ["relationship_issues", "stress", "loneliness_isolation"],
        "💔 Breakups Support": ["breakups", "grief_loss", "loneliness_isolation"],
        "🏠 Family Problems": ["family_problems", "stress", "loneliness_isolation"],
        "🛏 Roommate Conflict": ["roommate_conflict", "stress", "loneliness_isolation"],
        "🌫 Loneliness / Isolation": ["loneliness_isolation", "social_anxiety", "depression"],
        "🧳 Homesickness Support": ["homesickness", "loneliness_isolation", "family_problems"],
        "🌍 Culture Shock / Adjustment Issues": ["culture_shock", "homesickness", "identity_concerns"],
        "⚠ Discrimination / Bias Experiences": ["discrimination_bias", "identity_concerns", "stress"],
        "🪪 Identity Concerns (Sexuality / Gender / Faith)": ["identity_concerns", "discrimination_bias", "loneliness_isolation"],
        "🛡 Sexual Assault / Harassment Support": ["sexual_assault", "trauma_ptsd", "safety_concerns"],
        "🧯 Domestic/Dating Violence Support": ["dating_violence", "trauma_ptsd", "safety_concerns"],
        "🚧 Safety Concerns / Violence Risk": ["safety_concerns", "trauma_ptsd", "stress"],
        # Academic & Career
        "📚 Academic Problems": ["academic_problems", "stress", "motivation_focus"],
        "📝 Test Anxiety": ["test_anxiety", "anxiety", "academic_problems"],
        "⏰ Time Management / Procrastination": ["time_management", "adhd", "motivation_focus"],
        "🧠 Motivation / Concentration Problems": ["motivation_focus", "adhd", "depression"],
        "🧭 Career Stress / No Direction": ["career_stress", "identity_concerns", "stress"],
        "💰 Financial Stress": ["financial_stress", "stress", "career_stress"],
    }
    
    for name in PRESET_GROUPS:
        if name not in group_meta:
            group_meta[name] = {
                "name": name,
                "description": group_descriptions.get(name, "A supportive space to connect with peers around this topic."),
                "topics": group_topics.get(name, []),
                "group_type": "Peer Support",
                "is_private": False,
                "owner_id": None,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            group_members[name] = set()
        else:
            # Update existing groups with topics if missing
            if not group_meta[name].get("topics"):
                group_meta[name]["topics"] = group_topics.get(name, [])

seed_group_meta()


def ensure_group_exists(group_name):
    """Ensure a group exists in in-memory stores."""
    if group_name not in groups:
        groups[group_name] = []
    if group_name not in group_meta:
        group_meta[group_name] = {
            "name": group_name,
            "description": "A supportive space to connect with peers.",
            "topics": [],
            "group_type": "Peer Support",
            "is_private": False,
            "owner_id": None,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
    if group_name not in group_members:
        group_members[group_name] = set()
    if group_name not in group_requests:
        group_requests[group_name] = set()

def get_group_topics_labels(topic_ids):
    return get_topic_labels(topic_ids)

# Connection requests: { recipient_user_id: [ {sender_id, sender_display_name, message, timestamp}, ... ] }
pending_requests = {}

# Outgoing requests: { sender_user_id: [ {recipient_id, recipient_display_name, timestamp}, ... ] }
outgoing_requests = {}

# Accepted peer connections: { user_id: set() of connected user_ids }
peer_connections = {}

# User profiles cache for display: { user_id: {display_name, profile_summary} }
user_profiles = {}

# Basic profanity list for validation
PROFANITY_LIST = [
    "damn", "hell", "crap", "bastard", "idiot", "stupid", "dumb", "loser",
    "jerk", "moron", "fool", "imbecile", "ass", "shut up"
]

# Severe distress keywords
SEVERE_DISTRESS_KEYWORDS = [
    "suicide", "kill myself", "end my life", "want to die", "self-harm",
    "cutting myself", "overdose", "no reason to live", "better off dead"
]

# Offensive language patterns
OFFENSIVE_PATTERNS = [
    r"\b(hate\s+you|go\s+to\s+hell|f\s*u\s*c\s*k|s\s*h\s*i\s*t)\b",
    r"\b(retard|faggot|nigger|bitch|whore|slut)\b"
]

# -----------------------------------------------------------------------------
# ASU Resources (Real URLs)
# -----------------------------------------------------------------------------

ASU_RESOURCES = [
    {"name": "ASU Counseling Services", "url": "https://eoss.asu.edu/counseling"},
    {"name": "International Students and Scholars Center", "url": "https://issc.asu.edu/"},
    {"name": "ASU Health Services", "url": "https://eoss.asu.edu/health"},
    {"name": "Dean of Students", "url": "https://eoss.asu.edu/dos"},
    {"name": "ASU Career and Professional Development Services", "url": "https://career.asu.edu/"},
    {"name": "ASU Tutoring and Academic Success", "url": "https://tutoring.asu.edu/"},
    {"name": "Sun Devil Fitness Complex", "url": "https://fitness.asu.edu/"},
    {"name": "ASU Writing Centers", "url": "https://tutoring.asu.edu/writing-centers"},
]

EMERGENCY_RESOURCE = {
    "name": "988 Suicide and Crisis Lifeline",
    "url": "https://988lifeline.org/"
}

# -----------------------------------------------------------------------------
# Semantic Matching (Hugging Face Embeddings)
# -----------------------------------------------------------------------------

# In-memory embedding storage
user_embeddings = {}  # {user_id: [float, ...]}
group_embeddings = {}  # {group_name: [float, ...]}

# HF model for embeddings
HF_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
HF_API_URL = f"https://api-inference.huggingface.co/pipeline/feature-extraction/{HF_EMBEDDING_MODEL}"


def build_profile_text(profile_dict):
    """Build a readable text block from profile fields for embedding."""
    parts = []

    gender = profile_dict.get("gender", "")
    if gender:
        parts.append(f"I identify as {gender}.")

    cultural_bg = profile_dict.get("cultural_background", [])
    if cultural_bg:
        bg_text = ", ".join(cultural_bg) if isinstance(cultural_bg, list) else cultural_bg
        parts.append(f"My cultural background is {bg_text}.")

    challenges = normalize_topic_ids(profile_dict.get("primary_challenge", []))
    support_topics = normalize_topic_ids(profile_dict.get("support_topics", []))
    private_topics = normalize_topic_ids(profile_dict.get("private_topics", []))
    combined_topics = list(dict.fromkeys(challenges + support_topics + private_topics))
    if combined_topics:
        challenge_text = ", ".join(get_topic_labels(combined_topics))
        parts.append(f"My main challenges are: {challenge_text}.")

    language = profile_dict.get("preferred_language")
    if language:
        parts.append(f"My preferred language is {language}.")

    support_style = profile_dict.get("support_style", "mixed")
    if support_style == "listening":
        parts.append("I prefer to listen and receive support.")
    elif support_style == "sharing":
        parts.append("I prefer to share my experiences with others.")
    else:
        parts.append("I am open to both listening and sharing.")

    interests = profile_dict.get("interests", [])
    if interests:
        interest_text = ", ".join(interests)
        parts.append(f"My interests include: {interest_text}.")
    
    graduation_year = profile_dict.get("graduation_year", "")
    if graduation_year:
        parts.append(f"I'm graduating in {graduation_year}.")
    
    degree_program = profile_dict.get("degree_program", "")
    if degree_program:
        degree_readable = degree_program.replace("_", " ").title()
        parts.append(f"I'm pursuing a {degree_readable} degree.")

    display_name = profile_dict.get("display_name", "")
    if display_name:
        parts.insert(0, f"My name is {display_name}.")

    return " ".join(parts) if parts else "ASU student looking for peer support."


def embed_text(text):
    """
    Get embedding vector from Hugging Face Inference API.
    Returns list of floats or None if API fails.
    """
    if os.environ.get("LIVE_AI") != "1":
        return None

    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        return None

    try:
        import requests
        headers = {"Authorization": f"Bearer {hf_token}"}
        payload = {"inputs": text, "options": {"wait_for_model": True}}
        response = requests.post(HF_API_URL, headers=headers, json=payload, timeout=10)

        if response.status_code == 200:
            result = response.json()
            if isinstance(result, list) and len(result) > 0:
                if isinstance(result[0], list):
                    return result[0]
                return result
        return None
    except Exception:
        return None


def cosine_similarity(vec_a, vec_b):
    """Compute cosine similarity between two vectors."""
    if not vec_a or not vec_b or len(vec_a) != len(vec_b):
        return 0.0

    dot_product = sum(a * b for a, b in zip(vec_a, vec_b))
    magnitude_a = sum(a * a for a in vec_a) ** 0.5
    magnitude_b = sum(b * b for b in vec_b) ** 0.5

    if magnitude_a == 0 or magnitude_b == 0:
        return 0.0

    return dot_product / (magnitude_a * magnitude_b)


def get_top_matches(target_embedding, candidates, top_n=5, threshold=0.3):
    """
    Find top matching candidates based on cosine similarity.
    candidates: dict of {key: embedding}
    Returns: list of (key, similarity_score) sorted by score descending
    """
    if not target_embedding:
        return []

    scores = []
    for key, embedding in candidates.items():
        if embedding:
            sim = cosine_similarity(target_embedding, embedding)
            if sim >= threshold:
                scores.append((key, sim))

    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[:top_n]


def keyword_score(text_a, text_b):
    """Fallback keyword-based similarity scoring."""
    if not text_a or not text_b:
        return 0.0

    words_a = set(text_a.lower().split())
    words_b = set(text_b.lower().split())

    stopwords = {"i", "am", "a", "an", "the", "is", "are", "my", "to", "and", "or", "for", "with", "in", "on", "at"}
    words_a = words_a - stopwords
    words_b = words_b - stopwords

    if not words_a or not words_b:
        return 0.0

    intersection = len(words_a & words_b)
    union = len(words_a | words_b)

    return intersection / union if union > 0 else 0.0


def get_keyword_matches(target_text, candidates_text, top_n=5, threshold=0.1):
    """
    Fallback matching using keyword overlap.
    candidates_text: dict of {key: text}
    Returns: list of (key, score) sorted by score descending
    """
    scores = []
    for key, text in candidates_text.items():
        score = keyword_score(target_text, text)
        if score >= threshold:
            scores.append((key, score))

    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[:top_n]


def store_user_embedding(user_id, profile_dict):
    """Generate and store embedding for a user profile."""
    profile_text = build_profile_text(profile_dict)
    embedding = embed_text(profile_text)

    if embedding:
        user_embeddings[user_id] = embedding
    else:
        user_embeddings[user_id] = {"text": profile_text}

    return embedding is not None


def store_group_embedding(group_name):
    """Generate and store embedding for a group topic."""
    if group_name in group_embeddings:
        return True

    embedding = embed_text(group_name)

    if embedding:
        group_embeddings[group_name] = embedding
    else:
        group_embeddings[group_name] = {"text": group_name}

    return embedding is not None


def init_group_embeddings():
    """Initialize embeddings for all preset groups."""
    for group_name in PRESET_GROUPS:
        store_group_embedding(group_name)


def get_recommended_groups_semantic(user_id, top_n=5):
    """
    Get recommended groups for a user using semantic matching.
    Falls back to keyword matching if embeddings unavailable.
    """
    user_data = user_embeddings.get(user_id)

    if not user_data:
        return list(PRESET_GROUPS)[:top_n]

    if isinstance(user_data, list):
        valid_embeddings = {
            k: v for k, v in group_embeddings.items()
            if isinstance(v, list)
        }
        if valid_embeddings:
            matches = get_top_matches(user_data, valid_embeddings, top_n=top_n, threshold=0.2)
            if matches:
                return [m[0] for m in matches]

    user_text = user_data.get("text", "") if isinstance(user_data, dict) else ""
    if user_text:
        group_texts = {
            k: v.get("text", k) if isinstance(v, dict) else k
            for k, v in group_embeddings.items()
        }
        matches = get_keyword_matches(user_text, group_texts, top_n=top_n, threshold=0.05)
        if matches:
            return [m[0] for m in matches]

    return list(PRESET_GROUPS)[:top_n]


def get_similar_users(user_id, top_n=5, threshold=0.4):
    """
    Find similar users based on profile embeddings.
    Excludes self from results.
    Falls back to keyword matching if embeddings unavailable.
    """
    user_data = user_embeddings.get(user_id)

    if not user_data:
        return []

    other_users = {k: v for k, v in user_embeddings.items() if k != user_id}

    if not other_users:
        return []

    if isinstance(user_data, list):
        valid_embeddings = {
            k: v for k, v in other_users.items()
            if isinstance(v, list)
        }
        if valid_embeddings:
            matches = get_top_matches(user_data, valid_embeddings, top_n=top_n, threshold=threshold)
            return [(m[0], m[1]) for m in matches]

    user_text = user_data.get("text", "") if isinstance(user_data, dict) else ""
    if user_text:
        other_texts = {
            k: v.get("text", "") if isinstance(v, dict) else ""
            for k, v in other_users.items()
        }
        matches = get_keyword_matches(user_text, other_texts, top_n=top_n, threshold=0.1)
        return [(m[0], m[1]) for m in matches]

    return []


def get_users_for_group(group_name, top_n=10):
    """
    Find users who might be interested in a specific group.
    Used for group creation and suggestions.
    """
    group_data = group_embeddings.get(group_name)

    if not group_data:
        store_group_embedding(group_name)
        group_data = group_embeddings.get(group_name)

    if not group_data:
        return []

    if isinstance(group_data, list):
        valid_users = {
            k: v for k, v in user_embeddings.items()
            if isinstance(v, list)
        }
        if valid_users:
            matches = get_top_matches(group_data, valid_users, top_n=top_n, threshold=0.3)
            return [(m[0], m[1]) for m in matches]

    group_text = group_data.get("text", group_name) if isinstance(group_data, dict) else group_name
    user_texts = {
        k: v.get("text", "") if isinstance(v, dict) else ""
        for k, v in user_embeddings.items()
    }
    matches = get_keyword_matches(group_text, user_texts, top_n=top_n, threshold=0.05)
    return [(m[0], m[1]) for m in matches]

# -----------------------------------------------------------------------------
# AI Abstraction Functions
# -----------------------------------------------------------------------------

def detect_severe_distress(text):
    """Check if text contains severe distress signals."""
    text_lower = text.lower()
    for keyword in SEVERE_DISTRESS_KEYWORDS:
        if keyword in text_lower:
            return True
    return False


def detect_offensive_language(text):
    """Check if text contains offensive language."""
    text_lower = text.lower()
    for pattern in OFFENSIVE_PATTERNS:
        if re.search(pattern, text_lower, re.IGNORECASE):
            return True
    for word in PROFANITY_LIST:
        if re.search(r"\b" + re.escape(word) + r"\b", text_lower):
            return True
    return False


def get_mock_support_options(issue_text, profile_dict):
    """Generate deterministic support options based on keywords."""
    options = ["Talk to a peer who understands your situation"]
    issue_lower = issue_text.lower()

    if any(w in issue_lower for w in ["lonely", "alone", "isolated", "miss"]):
        options.append("Join a peer support group for homesickness")
    if any(w in issue_lower for w in ["stress", "pressure", "overwhelm", "exam", "grade"]):
        options.append("Explore academic support resources")
    if any(w in issue_lower for w in ["friend", "social", "connect", "people"]):
        options.append("Attend a campus social event")
    if any(w in issue_lower for w in ["language", "english", "speak", "communication"]):
        options.append("Use language exchange or tutoring services")
    if any(w in issue_lower for w in ["money", "financial", "expensive", "afford"]):
        options.append("Consult financial aid or emergency assistance")
    if any(w in issue_lower for w in ["health", "sick", "doctor", "tired", "sleep"]):
        options.append("Visit campus health services")

    if len(options) == 1:
        options.append("Reach out to the International Students Center")
        options.append("Speak with a counselor for guidance")

    return options[:5]


def get_mock_recommended_groups(issue_text, profile_dict):
    """Recommend groups based on issue keywords."""
    recommended = []
    issue_lower = issue_text.lower()

    keyword_map = {
        "Homesickness and Family": ["home", "homesick", "family", "miss", "lonely", "alone"],
        "Academic Pressure": ["exam", "grade", "study", "stress", "class", "professor"],
        "Making Friends": ["friend", "social", "connect", "people", "meet"],
        "Cultural Adjustment": ["culture", "different", "adjust", "custom", "food"],
        "Language Barriers": ["language", "english", "speak", "understand", "communication"],
        "Financial Stress": ["money", "financial", "expensive", "afford", "job"],
        "Health and Wellness": ["health", "sick", "tired", "sleep", "exercise", "mental"],
        "Career and Internships": ["career", "internship", "job", "resume", "interview"],
    }

    for group, keywords in keyword_map.items():
        if any(kw in issue_lower for kw in keywords):
            recommended.append(group)

    if not recommended:
        recommended = ["Homesickness and Family", "Making Friends"]

    return recommended[:3]


def mock_ai_suggest_resources_and_options(issue_text, profile_dict, followup_count, followup_question=None):
    """Deterministic mock AI for resource suggestions."""
    support_options = get_mock_support_options(issue_text, profile_dict)
    recommended_groups = get_mock_recommended_groups(issue_text, profile_dict)

    resources = ASU_RESOURCES[:8].copy()
    if detect_severe_distress(issue_text):
        resources.insert(0, EMERGENCY_RESOURCE)

    disclaimer = (
        "These suggestions are informational only and do not constitute professional "
        "or medical advice. If you are in crisis, please contact a professional immediately."
    )

    if followup_question:
        followup_lower = followup_question.lower()
        if "how" in followup_lower or "what" in followup_lower:
            support_options.insert(0, "Consider starting with the first resource listed above")
        if "more" in followup_lower:
            support_options.append("Explore the ASU Student Services portal for additional options")

    return {
        "support_options": support_options,
        "asu_resources": resources,
        "recommended_groups": recommended_groups,
        "safe_disclaimer": disclaimer
    }


def mock_ai_moderate_message(message_text):
    """Deterministic mock AI for chat moderation."""
    if detect_offensive_language(message_text):
        return {
            "allowed": False,
            "reason": "offensive_language",
            "user_message": "Your message was not sent because it contains inappropriate language."
        }
    if detect_severe_distress(message_text):
        return {
            "allowed": True,
            "reason": "severe_distress",
            "user_message": message_text
        }
    return {
        "allowed": True,
        "reason": "ok",
        "user_message": message_text
    }


def call_live_ai(endpoint, payload):
    """Call live AI endpoint if configured."""
    import requests
    ai_url = os.environ.get("AI_ENDPOINT_URL")
    ai_key = os.environ.get("AI_ENDPOINT_KEY")

    if not ai_url or not ai_key:
        return None

    try:
        headers = {"Authorization": f"Bearer {ai_key}", "Content-Type": "application/json"}
        response = requests.post(f"{ai_url}/{endpoint}", json=payload, headers=headers, timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception:
        pass
    return None


import time
AI_RATE_LIMITS = {}

def check_rate_limit(ip_address, limit=5, window_seconds=60):
    """Simple in-memory rate limiting."""
    now = time.time()
    if ip_address not in AI_RATE_LIMITS:
        AI_RATE_LIMITS[ip_address] = []
    
    AI_RATE_LIMITS[ip_address] = [t for t in AI_RATE_LIMITS[ip_address] if now - t < window_seconds]
    
    if len(AI_RATE_LIMITS[ip_address]) >= limit:
        return False
        
    AI_RATE_LIMITS[ip_address].append(now)
    return True

def call_ai_api(prompt, max_tokens=300):
    """Call Cerebras AI API for text generation."""
    try:
        from flask import request
        if not check_rate_limit(request.remote_addr, limit=5, window_seconds=60):
            print("Rate limit exceeded for AI API")
            return None
    except Exception:
        pass

    if os.environ.get("LIVE_AI") != "1":
        return None

    api_key = os.environ.get("CEREBRAS_API_KEY")
    if not api_key:
        return None

    try:
        from cerebras.cloud.sdk import Cerebras

        client = Cerebras(api_key=api_key)

        completion = client.chat.completions.create(
            messages=[{"role": "user", "content": prompt}],
            model="llama-3.3-70b",
            max_completion_tokens=max_tokens,
            temperature=0.7,
            top_p=1,
            stream=False
        )

        return completion.choices[0].message.content.strip()
    except Exception as e:
        print(f"Cerebras API error: {e}")
        return None






def generate_support_response(issue_text, profile_dict):
    """Generate personalized support response with empathetic message, suggestions, and relevant resources."""
    profile_summary = build_profile_text(profile_dict)
    
    # Format available resources for the prompt
    resources_list = "\n".join([f"{i+1}. {r['name']}" for i, r in enumerate(ASU_RESOURCES)])

    prompt = f"""You are a caring, supportive counselor at ASU helping an international freshman student who is struggling.

Student Profile: {profile_summary}

Student's Issue: {issue_text}

Available ASU Resources:
{resources_list}

Task:
1. Write a warm, empathetic message (2-3 sentences) acknowledging their feelings and validating their experience.
2. Provide 5 specific, actionable suggestions.
3. Select the 3 most relevant ASU Resources from the list above by their number (e.g., 1, 4, 7).

Format your response EXACTLY like this:
MESSAGE: [Your empathetic message here]

SUGGESTIONS:
1. [First suggestion]
2. [Second suggestion]  
3. [Third suggestion]
4. [Fourth suggestion]
5. [Fifth suggestion]

RESOURCES: [comma separated numbers, e.g. 1, 5, 8]"""

    response = call_ai_api(prompt, max_tokens=500)

    if response:
        # Parse message, suggestions, and resources
        empathetic_message = ""
        suggestions = []
        resource_indices = []
        
        # Extract Message
        if "MESSAGE:" in response:
            parts = response.split("SUGGESTIONS:")
            if len(parts) >= 2:
                empathetic_message = parts[0].replace("MESSAGE:", "").strip()
                remaining = parts[1]
                
                # Extract Suggestions and Resources
                if "RESOURCES:" in remaining:
                    sugg_parts = remaining.split("RESOURCES:")
                    suggestion_text = sugg_parts[0]
                    resource_text = sugg_parts[1].strip()
                    
                    # Parse Suggestions
                    lines = suggestion_text.split('\n')
                    for line in lines:
                        line = line.strip()
                        if line and len(line) > 3:
                            if line[0].isdigit() and '.' in line[:3]:
                                line = line.split('.', 1)[1].strip()
                            if line:
                                suggestions.append(line)

                    # Parse Resource Indices
                    try:
                        # Extract numbers using regex to handle various formats
                        import re
                        numbers = re.findall(r'\d+', resource_text)
                        resource_indices = [int(n) - 1 for n in numbers if n.isdigit()] # Convert 1-based to 0-based
                        # Filter valid indices
                        resource_indices = [idx for idx in resource_indices if 0 <= idx < len(ASU_RESOURCES)]
                    except Exception:
                        pass
        
        if empathetic_message or suggestions:
            return {
                "message": empathetic_message,
                "suggestions": suggestions[:5] if suggestions else [],
                "resource_indices": resource_indices
            }

    return None




def generate_followup_answer(issue_text, followup_question, profile_dict, history=None):
    """Generate answer to a follow-up question using AI."""
    profile_summary = build_profile_text(profile_dict)

    history_text = ""
    if history:
        history_text = "\n\nPrevious Q&A:\n"
        for item in history[-3:]:  # Last 3 items only
            history_text += f"Q: {item['question']}\nA: {item['answer']}\n"

    prompt = f"""You are a supportive counselor at ASU helping an international freshman student.

Student Profile: {profile_summary}
Original Issue: {issue_text}
{history_text}
Current Question: {followup_question}

Provide a helpful, specific answer to the student's question. Be warm, practical, and reference ASU resources when relevant. Keep your response to 2-3 sentences.

Answer:"""

    response = call_ai_api(prompt, max_tokens=150)

    if response:
        # Clean up the response
        answer = response.strip()
        if answer.startswith("Answer:"):
            answer = answer[7:].strip()
        if answer:
            return answer

    return None


def ai_suggest_resources_and_options(issue_text, profile_dict, followup_count, followup_question=None):
    """AI abstraction for resource suggestions. Falls back to mock if live AI unavailable."""
    # Try to get AI-generated response
    ai_response = None
    empathetic_message = ""
    support_options = []

    if os.environ.get("LIVE_AI") == "1":
        ai_response = generate_support_response(issue_text, profile_dict)

    if ai_response:
        empathetic_message = ai_response.get("message", "")
        support_options = ai_response.get("suggestions", [])
        
    # Get resources
    resources = []
    
    # Use AI-selected resources if available
    if ai_response and ai_response.get("resource_indices"):
        for idx in ai_response["resource_indices"]:
            if 0 <= idx < len(ASU_RESOURCES):
                resources.append(ASU_RESOURCES[idx])
    
    # If no valid AI resources, use default fallback (first 8)
    if not resources:
        resources = ASU_RESOURCES[:8].copy()

    # Always add emergency resource if distress detected
    if detect_severe_distress(issue_text):
        resources.insert(0, EMERGENCY_RESOURCE)

    # Fall back to mock if AI didn't provide suggestions
    if not support_options:
        support_options = get_mock_support_options(issue_text, profile_dict)

    # Get recommended groups
    recommended_groups = get_mock_recommended_groups(issue_text, profile_dict)

    disclaimer = (

        "These suggestions are informational only and do not constitute professional "
        "or medical advice. If you are in crisis, please contact a professional immediately."
    )

    return {
        "empathetic_message": empathetic_message,
        "support_options": support_options,
        "asu_resources": resources,
        "recommended_groups": recommended_groups,
        "safe_disclaimer": disclaimer
    }



def ai_generate_followup_response(issue_text, followup_question, profile_dict, history=None):
    """Generate a response to a follow-up question."""
    if os.environ.get("LIVE_AI") == "1":
        ai_response = generate_followup_answer(issue_text, followup_question, profile_dict, history)
        if ai_response:
            return ai_response

    # Fallback response
    return ("Based on your question, consider exploring the resources listed above. "
            "Start with the option that feels most relevant to your situation.")


def ai_moderate_message(message_text):
    """AI abstraction for chat moderation. Falls back to mock if live AI unavailable."""
    if os.environ.get("LIVE_AI") == "1":
        payload = {"message_text": message_text}
        result = call_live_ai("moderate", payload)
        if result:
            return result

    return mock_ai_moderate_message(message_text)


# -----------------------------------------------------------------------------
# Helper Functions
# -----------------------------------------------------------------------------

def get_profile_dict():
    """Extract profile fields from session."""
    return {
        "display_name": session.get("display_name", ""),
        "gender": session.get("gender", ""),
        "preferred_language": session.get("preferred_language", ""),
        "primary_challenge": session.get("primary_challenge", []),
        "support_style": session.get("support_style", "mixed"),
        "support_topics": session.get("support_topics", []),
        "private_topics": session.get("private_topics", []),
        "languages": session.get("languages", []),
        "cultural_background": session.get("cultural_background", []),
        "graduation_year": session.get("graduation_year", ""),
        "degree_program": session.get("degree_program", ""),
    }


def check_profanity(text):
    """Basic profanity check for group topic validation."""
    text_lower = text.lower()
    for word in PROFANITY_LIST:
        if word in text_lower:
            return True
    return False


def find_relevant_group(topic_text):
    """Check if a relevant active group exists based on keyword overlap."""
    topic_lower = topic_text.lower()
    words = set(topic_lower.split())

    for group_topic in groups.keys():
        group_words = set(group_topic.lower().split())
        if words & group_words:
            return group_topic
    return None


# -----------------------------------------------------------------------------
# Landing Page Route
# -----------------------------------------------------------------------------

@app.route("/")
def index():
    """Landing page with hero section."""
    return render_template("index.html")


# -----------------------------------------------------------------------------
# Authentication Routes
# -----------------------------------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    """Login page."""
    if session.get("user_id"):
        # Check if onboarding is complete
        profile = load_profile_from_db(session.get("user_id"))
        if profile and profile.get("onboarding_complete"):
            return redirect(url_for("decision"))
        return redirect(url_for("onboarding"))

    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            error = "Username and password are required."
        else:
            user = None
            if IS_VERCEL:
                # Use in-memory storage on Vercel
                user_data = memory_users.get(username)
                if user_data and check_password_hash(user_data["password_hash"], password):
                    user = user_data
            else:
                # Use SQLite locally
                db = get_db()
                user_row = db.execute(
                    "SELECT * FROM users WHERE username = ?", (username,)
                ).fetchone()
                if user_row and check_password_hash(user_row["password_hash"], password):
                    user = {"id": user_row["id"], "username": user_row["username"]}

            if user:
                session["user_id"] = user["id"]
                session["username"] = user["username"]

                # Load profile from database if exists
                profile = load_profile_from_db(user["id"])
                if profile:
                    session["display_name"] = profile["display_name"]
                    session["gender"] = profile.get("gender", "")
                    session["preferred_language"] = profile["preferred_language"]
                    session["primary_challenge"] = profile["primary_challenge"]
                    session["support_style"] = profile["support_style"]
                    session["support_topics"] = profile.get("support_topics", [])
                    session["private_topics"] = profile.get("private_topics", [])
                    session["languages"] = profile.get("languages", [])
                    session["cultural_background"] = profile.get("cultural_background", [])
                    session["onboarding_complete"] = profile.get("onboarding_complete", False)
                    
                    # Redirect based on onboarding status
                    if profile.get("onboarding_complete"):
                        return redirect(url_for("decision"))
                    else:
                        return redirect(url_for("onboarding"))
                else:
                    return redirect(url_for("onboarding"))
            else:
                error = "Invalid username or password."

    return render_template("login.html", error=error)



@app.route("/signup", methods=["GET", "POST"])
def signup():
    """Signup page."""
    global memory_user_counter
    if session.get("user_id"):
        return redirect(url_for("profile"))

    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        if not username:
            error = "Username is required."
        elif not password:
            error = "Password cannot be empty."
        elif password != confirm_password:
            error = "Passwords do not match."
        elif len(username) > 50:
            error = "Username must be 50 characters or less."
        else:
            existing = None
            if IS_VERCEL:
                # Use in-memory storage on Vercel
                existing = memory_users.get(username)
            else:
                # Use SQLite locally
                db = get_db()
                existing = db.execute(
                    "SELECT id FROM users WHERE username = ?", (username,)
                ).fetchone()

            if existing:
                error = "Username already exists. Please choose another."
            else:
                password_hash = generate_password_hash(password)
                created_at = datetime.now().isoformat()
                
                if IS_VERCEL:
                    # Store in memory on Vercel
                    user_id = memory_user_counter
                    memory_user_counter += 1
                    memory_users[username] = {
                        "id": user_id,
                        "username": username,
                        "password_hash": password_hash,
                        "created_at": created_at
                    }
                    session["user_id"] = user_id
                    session["username"] = username
                else:
                    # Store in SQLite locally
                    db = get_db()
                    db.execute(
                        "INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                        (username, password_hash, created_at)
                    )
                    db.commit()

                    user = db.execute(
                        "SELECT * FROM users WHERE username = ?", (username,)
                    ).fetchone()
                    session["user_id"] = user["id"]
                    session["username"] = user["username"]
                
                return redirect(url_for("onboarding"))

    return render_template("signup.html", error=error)


@app.route("/logout")
def logout():
    """Logout and clear session."""
    session.clear()
    return redirect(url_for("index"))


# -----------------------------------------------------------------------------
# Onboarding Routes
# -----------------------------------------------------------------------------

@app.route("/onboarding")
@login_required
def onboarding():
    """Multi-step onboarding wizard."""
    # If onboarding already complete, redirect to dashboard
    user_id = session.get("user_id")
    profile = load_profile_from_db(user_id)
    if profile and profile.get("onboarding_complete"):
        return redirect(url_for("decision"))
    return render_template("onboarding.html")


@app.route("/onboarding/submit", methods=["POST"])
@login_required
def onboarding_submit():
    """Process onboarding form submission."""
    user_id = session.get("user_id")
    
    # Parse form data
    support_topics = request.form.get("support_topics", "").split(",")
    support_topics = [t.strip() for t in support_topics if t.strip()]
    
    languages = request.form.get("languages", "").split(",")
    languages = [l.strip() for l in languages if l.strip()]
    
    support_style = request.form.get("support_style", "mixed")
    
    cultural_background = request.form.get("cultural_background", "").split(",")
    cultural_background = [c.strip() for c in cultural_background if c.strip()]
    
    gender = request.form.get("gender", "").strip()
    display_name = request.form.get("display_name", "").strip()[:50]
    graduation_year = request.form.get("graduation_year", "").strip()
    degree_program = request.form.get("degree_program", "").strip()
    
    # Build profile dict
    profile_dict = {
        "display_name": display_name,
        "gender": gender,
        "preferred_language": languages[0] if languages else "",
        "primary_challenge": support_topics,
        "support_style": support_style,
        "support_topics": support_topics,
        "private_topics": [],
        "languages": languages,
        "cultural_background": cultural_background,
        "graduation_year": graduation_year,
        "degree_program": degree_program,
        "onboarding_complete": True
    }
    
    # Save to database
    save_profile_to_db(user_id, profile_dict)
    
    # Store in session for quick access
    session["display_name"] = display_name
    session["gender"] = gender
    session["preferred_language"] = languages[0] if languages else ""
    session["primary_challenge"] = support_topics
    session["support_style"] = support_style
    session["support_topics"] = support_topics
    session["private_topics"] = []
    session["languages"] = languages
    session["cultural_background"] = cultural_background
    session["onboarding_complete"] = True
    
    # Store user embedding for semantic matching
    store_user_embedding(user_id, profile_dict)
    
    return redirect(url_for("decision"))


# -----------------------------------------------------------------------------
# Routes
# -----------------------------------------------------------------------------

@app.route("/profile", methods=["GET", "POST"])
@login_required
def profile():
    """Profile settings page - full edit capabilities."""
    user_id = session.get("user_id")
    
    if request.method == "POST":
        # Get form data
        display_name = request.form.get("display_name", "").strip()[:30]
        gender = request.form.get("gender", "").strip()
        support_style = request.form.get("support_style", "mixed")
        if support_style not in ["listening", "advice", "mixed"]:
            support_style = "mixed"
        
        # Get multi-select fields
        support_topics = request.form.getlist("support_topics")
        private_topics = request.form.getlist("private_topics")
        private_topics = [t for t in private_topics if t in support_topics]
        languages = request.form.getlist("languages")
        cultural_background = request.form.getlist("cultural_background")
        graduation_year = request.form.get("graduation_year", "").strip()
        degree_program = request.form.get("degree_program", "").strip()
        
        # Update session
        session["display_name"] = display_name
        session["gender"] = gender
        session["support_style"] = support_style
        session["support_topics"] = support_topics
        session["private_topics"] = private_topics
        session["languages"] = languages
        session["preferred_language"] = languages[0] if languages else ""
        session["cultural_background"] = cultural_background
        session["graduation_year"] = graduation_year
        session["degree_program"] = degree_program
        session["primary_challenge"] = support_topics  # For compatibility
        
        # Build profile dict
        profile_dict = {
            "display_name": display_name,
            "gender": gender,
            "preferred_language": languages[0] if languages else "",
            "primary_challenge": support_topics,
            "support_style": support_style,
            "support_topics": support_topics,
            "private_topics": private_topics,
            "languages": languages,
            "cultural_background": cultural_background,
            "graduation_year": graduation_year,
            "degree_program": degree_program,
            "onboarding_complete": True
        }
        
        # Save to database
        if user_id:
            save_profile_to_db(user_id, profile_dict)
            store_user_embedding(user_id, profile_dict)
            cache_user_profile(user_id, display_name, profile_dict)
        
        flash("Profile saved successfully!", "success")
        return redirect(url_for("profile"))

    # GET - Load existing profile
    existing_profile = load_profile_from_db(user_id) if user_id else None
    
    # Fallback to session data if no DB profile
    if not existing_profile:
        existing_profile = {
            "display_name": session.get("display_name", ""),
            "gender": session.get("gender", ""),
            "preferred_language": session.get("preferred_language", ""),
            "primary_challenge": session.get("primary_challenge", []),
            "support_style": session.get("support_style", "mixed"),
            "support_topics": session.get("support_topics", []),
            "private_topics": session.get("private_topics", []),
            "languages": session.get("languages", []),
            "cultural_background": session.get("cultural_background", [])
        }
    
    return render_template("profile.html", 
                         profile=existing_profile,
                         username=session.get("username"),
                         support_topic_categories=SUPPORT_TOPIC_CATEGORIES,
                         support_topic_index=SUPPORT_TOPIC_INDEX)


@app.route("/issue", methods=["GET", "POST"])
@login_required
def issue():
    """Issue input page."""
    if not session.get("display_name"):
        return redirect(url_for("profile"))

    if request.method == "POST":
        issue_text = request.form.get("issue_text", "").strip()
        if issue_text:
            session["current_issue"] = issue_text
            session["followup_count"] = 0
            return redirect(url_for("resources"))

    return render_template(
        "issue.html",
        username=session.get("username"),
        support_topic_categories=SUPPORT_TOPIC_CATEGORIES
    )


@app.route("/resources", methods=["GET", "POST"])
@login_required
def resources():
    """Resource page with AI suggestions and follow-up Q and A."""
    if not session.get("display_name"):
        return redirect(url_for("profile"))

    issue_text = session.get("current_issue", "")
    if not issue_text:
        return redirect(url_for("issue"))

    # Initialize follow-up history if not present
    if "followup_history" not in session:
        session["followup_history"] = []

    followup_count = session.get("followup_count", 0)
    followup_question = None
    followup_response = None

    if request.method == "POST":
        followup_question = request.form.get("followup_question", "").strip()
        if followup_question:
            session["followup_count"] = followup_count + 1
            followup_count = session["followup_count"]

            # Generate AI response
            profile_dict = get_profile_dict()
            history = session.get("followup_history", [])
            followup_response = ai_generate_followup_response(
                issue_text, followup_question, profile_dict, history
            )

            # Store in history
            history.append({
                "question": followup_question,
                "answer": followup_response
            })
            session["followup_history"] = history

    profile_dict = get_profile_dict()
    ai_result = ai_suggest_resources_and_options(issue_text, profile_dict, followup_count, followup_question)

    # Get semantically ranked groups
    user_id = session.get("user_id")
    semantic_groups = []
    if user_id:
        semantic_groups = get_recommended_groups_semantic(user_id, top_n=5)

    # Combine AI-recommended and semantic groups
    ai_groups = ai_result.get("recommended_groups", [])
    combined_groups = []
    seen = set()
    for g in semantic_groups + ai_groups:
        if g not in seen:
            combined_groups.append(g)
            seen.add(g)
    combined_groups = combined_groups[:5]

    return render_template(
        "resources.html",
        empathetic_message=ai_result.get("empathetic_message", ""),
        support_options=ai_result.get("support_options", []),
        asu_resources=ai_result.get("asu_resources", []),
        recommended_groups=combined_groups,
        disclaimer=ai_result.get("safe_disclaimer", ""),
        followup_count=followup_count,
        followup_question=followup_question,
        followup_response=followup_response,
        followup_history=session.get("followup_history", [])[:-1] if followup_question else session.get("followup_history", []),
        username=session.get("username")

    )


@app.route("/resources-hub", methods=["GET"])
@login_required
def resources_hub():
    """Resource hub page with all resources and filtering."""
    return render_template("resources_hub.html", username=session.get("username"))


@app.route("/decision", methods=["GET"])
@login_required
def decision():
    """Decision page to join or create groups."""
    if not session.get("display_name"):
        return redirect(url_for("profile"))

    user_id = session.get("user_id")
    issue_text = session.get("current_issue", "")
    profile_dict = get_profile_dict()

    # Get semantic group recommendations if user has embedding
    semantic_groups = []
    if user_id:
        semantic_groups = get_recommended_groups_semantic(user_id, top_n=5)

    # Fallback to keyword-based recommendations
    ai_result = ai_suggest_resources_and_options(issue_text, profile_dict, 0)
    keyword_groups = ai_result.get("recommended_groups", [])

    # Combine: semantic first, then keyword, deduplicated
    recommended = []
    seen = set()
    for g in semantic_groups + keyword_groups:
        if g not in seen:
            recommended.append(g)
            seen.add(g)
    recommended = recommended[:5]

    # Get similar users for "People you may want to connect with"
    similar_users = []
    if user_id:
        similar_users = get_similar_users(user_id, top_n=5, threshold=0.3)

    available_groups = list(groups.keys())

    return render_template(
        "decision.html",
        recommended_groups=recommended,
        available_groups=available_groups,
        similar_users=similar_users,
        username=session.get("username"),
        display_name=session.get("display_name"),
        current_group=session.get("current_group")
    )


@app.route("/groups", methods=["GET"])
@login_required
def groups_page():
    """Group discovery and creation page."""
    if not session.get("display_name"):
        return redirect(url_for("profile"))

    user_id = session.get("user_id")
    username = session.get("username")
    search_query = request.args.get("q", "").strip().lower()
    selected_topics = normalize_topic_ids(request.args.getlist("topics"))
    sort_by = request.args.get("sort", "best")  # best, members, newest, a_z

    # Load current user's profile for match scoring
    current_profile = load_profile_from_db(user_id) if user_id else None
    if not current_profile:
        current_profile = get_profile_dict()
    
    # Get user's last issue text from session for better matching
    last_issue_text = session.get("last_issue_text", "")

    # Get user's joined groups
    joined_groups = []
    for name, members in group_members.items():
        if username in members or user_id in members:
            meta = group_meta.get(name, {})
            match_score = calculate_group_match_score(current_profile, meta, last_issue_text)
            match_label = "Best Fit" if match_score >= 70 else ("Good Fit" if match_score >= 40 else "")
            joined_groups.append({
                "name": name,
                "description": meta.get("description", ""),
                "topics": normalize_topic_ids(meta.get("topics", [])),
                "topic_labels": get_group_topics_labels(normalize_topic_ids(meta.get("topics", []))),
                "group_type": meta.get("group_type", "Peer Support"),
                "is_private": bool(meta.get("is_private")),
                "member_count": len(members),
                "owner_id": meta.get("owner_id"),
                "match_score": match_score,
                "match_label": match_label,
            })

    available = []
    for name, meta in group_meta.items():
        topics = normalize_topic_ids(meta.get("topics", []))
        is_private = bool(meta.get("is_private"))

        # Topic filter with relevance-based OR logic
        if selected_topics:
            # Check 1: Direct topic ID match
            has_topic_match = bool(set(selected_topics) & set(topics))
            
            # Check 2: Topic label appears in group name or description (relevance matching)
            group_text = (name + " " + meta.get("description", "")).lower()
            has_relevance_match = False
            for topic_id in selected_topics:
                topic_info = SUPPORT_TOPIC_INDEX.get(topic_id, {})
                topic_label = topic_info.get("label", "").lower()
                # Check if any significant word from the label appears in group text
                label_words = [w for w in topic_label.split() if len(w) > 3]
                for word in label_words:
                    if word in group_text:
                        has_relevance_match = True
                        break
                if has_relevance_match:
                    break
            
            # Show group if either match type succeeds
            if not has_topic_match and not has_relevance_match:
                continue

        if search_query:
            # Build searchable text from name, description, AND topic labels
            topic_labels = " ".join(get_topic_labels(topics))
            searchable = " ".join([name, meta.get("description", ""), topic_labels]).lower()
            # Split search query into words and check if any word matches
            search_words = search_query.split()
            found_match = False
            for word in search_words:
                if len(word) >= 3 and word in searchable:
                    found_match = True
                    break
            if not found_match:
                continue

        # Calculate match score for this group
        match_score = calculate_group_match_score(current_profile, meta, last_issue_text)
        if match_score >= 70:
            match_label = "Best Fit"
        elif match_score >= 40:
            match_label = "Good Fit"
        else:
            match_label = "New Group"

        available.append({
            "name": name,
            "description": meta.get("description", ""),
            "topics": topics,
            "topic_labels": get_group_topics_labels(topics),
            "group_type": meta.get("group_type", "Peer Support"),
            "is_private": is_private,
            "member_count": len(group_members.get(name, set())),
            "owner_id": meta.get("owner_id"),
            "created_at": meta.get("created_at", "2024-01-01"),
            "match_score": match_score,
            "match_label": match_label,
        })

    # Apply sorting
    if sort_by == "newest":
        available.sort(key=lambda g: g.get("created_at", ""), reverse=True)
    elif sort_by == "a_z":
        available.sort(key=lambda g: g.get("name", "").lower())
    elif sort_by == "members":
        available.sort(key=lambda g: g.get("member_count", 0), reverse=True)
    else:  # best (default)
        available.sort(key=lambda g: g.get("match_score", 0), reverse=True)

    return render_template(
        "groups.html",
        groups=available,
        joined_groups=joined_groups,
        support_topic_categories=SUPPORT_TOPIC_CATEGORIES,
        selected_topics=selected_topics,
        search_query=search_query,
        sort_by=sort_by,
        group_types=GROUP_TYPES,
        username=session.get("username")
    )


@app.route("/groups/create", methods=["POST"])
@login_required
def create_group_full():
    """Create a new group with full metadata."""
    if not session.get("display_name"):
        return redirect(url_for("profile"))

    name = request.form.get("group_name", "").strip()[:60]
    description = request.form.get("group_description", "").strip()[:300]
    topics = normalize_topic_ids(request.form.getlist("group_topics"))
    group_type = request.form.get("group_type", "Peer Support")
    is_private = request.form.get("group_visibility") == "private"
    
    # New duration fields
    duration = request.form.get("group_duration", "ongoing")
    end_date = request.form.get("group_end_date", "")

    if not name or not description or not topics:
        flash("Please provide a group name, description, and topics.", "error")
        return redirect(url_for("groups_page"))

    if check_profanity(name):
        flash("Please choose a different group name.", "error")
        return redirect(url_for("groups_page"))

    if name in group_meta:
        flash("A group with that name already exists.", "error")
        return redirect(url_for("groups_page"))

    ensure_group_exists(name)
    group_meta[name].update({
        "name": name,
        "description": description,
        "topics": topics,
        "group_type": group_type if group_type in GROUP_TYPES else "Peer Support",
        "is_private": is_private,
        "owner_id": session.get("user_id"),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "duration": duration,
        "end_date": end_date if duration == "temporary" and end_date else None,
    })

    group_members[name].add(session.get("user_id"))
    store_group_embedding(name)
    flash("Group created successfully!", "success")
    return redirect(url_for("group_detail", group_name=name))


@app.route("/groups/join", methods=["POST"])
@login_required
def join_group_full():
    """Join or request access to a group."""
    group_name = request.form.get("group_name", "").strip()
    group_name = unquote(group_name)
    if not group_name or group_name not in group_meta:
        flash("Group not found.", "error")
        return redirect(url_for("groups_page"))

    ensure_group_exists(group_name)
    user_id = session.get("user_id")
    if group_meta[group_name].get("is_private"):
        group_requests.setdefault(group_name, set()).add(user_id)
        flash("Request sent. The group owner will review your request.", "success")
        return redirect(url_for("groups_page"))

    group_members[group_name].add(user_id)
    
    # Track join date
    if group_name not in group_member_dates:
        group_member_dates[group_name] = {}
    group_member_dates[group_name][user_id] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    session["current_group"] = group_name
    return redirect(url_for("group_detail", group_name=group_name))


@app.route("/groups/<path:group_name>", methods=["GET"])
@login_required
def group_detail(group_name):
    """Group detail page."""
    group_name = unquote(group_name)
    if group_name not in group_meta:
        flash("Group not found.", "error")
        return redirect(url_for("groups_page"))

    ensure_group_exists(group_name)
    meta = group_meta[group_name]
    user_id = session.get("user_id")
    is_owner = meta.get("owner_id") == user_id
    is_member = user_id in group_members.get(group_name, set())
    pending_requests = []
    if is_owner:
        for requester_id in group_requests.get(group_name, set()):
            profile = load_profile_from_db(requester_id)
            if profile:
                pending_requests.append({
                    "user_id": requester_id,
                    "display_name": profile.get("display_name") or "Anonymous",
                })

    members = []
    for member_id in group_members.get(group_name, set()):
        profile = load_profile_from_db(member_id)
        if profile:
            members.append(profile.get("display_name") or "Anonymous")

    recent_messages = []
    for msg in groups.get(group_name, [])[-5:]:
        recent_messages.append({
            "display_name": msg.get("display_name", "Anonymous"),
            "text": msg.get("text", ""),
            "timestamp": format_human_timestamp(msg.get("timestamp", ""))
        })

    return render_template(
        "group_detail.html",
        group=meta,
        group_topics=get_group_topics_labels(meta.get("topics", [])),
        member_count=len(group_members.get(group_name, set())),
        members=members,
        recent_messages=recent_messages,
        is_owner=is_owner,
        is_member=is_member,
        pending_requests=pending_requests,
        username=session.get("username")
    )


@app.route("/groups/<path:group_name>/leave", methods=["POST"])
@login_required
def group_leave(group_name):
    group_name = unquote(group_name)
    if group_name in group_members:
        group_members[group_name].discard(session.get("user_id"))
    if session.get("current_group") == group_name:
        session["current_group"] = None
    flash("You have left the group.", "success")
    return redirect(url_for("groups_page"))


@app.route("/groups/<path:group_name>/visibility", methods=["POST"])
@login_required
def group_toggle_visibility(group_name):
    group_name = unquote(group_name)
    meta = group_meta.get(group_name)
    if not meta:
        flash("Group not found.", "error")
        return redirect(url_for("groups_page"))
    if meta.get("owner_id") != session.get("user_id"):
        flash("Only the group owner can change visibility.", "error")
        return redirect(url_for("group_detail", group_name=group_name))

    new_visibility = request.form.get("visibility")
    meta["is_private"] = new_visibility == "private"
    flash("Group visibility updated.", "success")
    return redirect(url_for("group_detail", group_name=group_name))


@app.route("/groups/<path:group_name>/requests/approve", methods=["POST"])
@login_required
def group_request_approve(group_name):
    group_name = unquote(group_name)
    meta = group_meta.get(group_name)
    if not meta or meta.get("owner_id") != session.get("user_id"):
        flash("Not authorized.", "error")
        return redirect(url_for("group_detail", group_name=group_name))

    requester_id = request.form.get("requester_id")
    if not requester_id:
        flash("Invalid request.", "error")
        return redirect(url_for("group_detail", group_name=group_name))
    try:
        requester_id = int(requester_id)
    except Exception:
        flash("Invalid request.", "error")
        return redirect(url_for("group_detail", group_name=group_name))

    if requester_id in group_requests.get(group_name, set()):
        group_requests[group_name].discard(requester_id)
        group_members[group_name].add(requester_id)
        flash("Request approved.", "success")
    return redirect(url_for("group_detail", group_name=group_name))


@app.route("/groups/<path:group_name>/invite", methods=["GET"])
@login_required
def group_invite(group_name):
    """Invite people to a group with AI-inspired recommendations."""
    group_name = unquote(group_name)
    meta = group_meta.get(group_name)
    if not meta:
        flash("Group not found.", "error")
        return redirect(url_for("groups_page"))

    user_id = session.get("user_id")
    topics = normalize_topic_ids(meta.get("topics", []))
    search_query = request.args.get("q", "").strip().lower()

    # Get current user profile for matching
    current_profile = load_profile_from_db(user_id) if user_id else None
    if not current_profile:
        current_profile = {}

    db = get_db()
    # Exclude current user from results (same as people page)
    all_profiles = db.execute('''
        SELECT p.*, u.username FROM profiles p
        JOIN users u ON p.user_id = u.id
        WHERE p.user_id != ? AND p.display_name IS NOT NULL AND p.display_name != ''
    ''', (user_id,)).fetchall()

    benefit = []
    support = []
    
    for row in all_profiles:
        # Skip users already in the group
        if row['user_id'] in group_members.get(group_name, set()):
            continue
        
        # Skip users already invited to this group
        user_invites = group_invitations.get(row['user_id'], [])
        if any(inv.get("group_name") == group_name for inv in user_invites):
            continue
            
        challenges = normalize_topic_ids((row['primary_challenge'] or '').split(','))
        supports = normalize_topic_ids((row['support_topics'] or '').split(','))
        privates = normalize_topic_ids((row['private_topics'] or '').split(','))
        all_topics = list(dict.fromkeys(challenges + supports))

        # Apply search filter (same as people page)
        if search_query:
            searchable = " ".join([
                row['display_name'] or '',
                row['username'] or '',
                row['preferred_language'] or '',
                ",".join(all_topics),
            ]).lower()
            # Word-based matching for flexibility
            query_words = search_query.split()
            found = False
            for word in query_words:
                if len(word) >= 3 and word in searchable:
                    found = True
                    break
            if not found and search_query not in searchable:
                continue

        # Build peer profile for match scoring
        peer_profile = {
            "display_name": row['display_name'] or 'Anonymous',
            "gender": row['gender'] if 'gender' in row.keys() else '',
            "preferred_language": row['preferred_language'] or '',
            "primary_challenge": challenges,
            "support_topics": supports,
            "private_topics": privates,
            "languages": (row['languages'] or '').split(',') if row['languages'] else [],
            "cultural_background": (row['cultural_background'] or '').split(',') if row['cultural_background'] else [],
            "support_style": row['support_style'] or 'mixed'
        }
        try:
            peer_profile["graduation_year"] = row['graduation_year'] or ''
            peer_profile["degree_program"] = row['degree_program'] or ''
        except:
            pass

        # Calculate match score based on group topics overlap
        benefit_overlap = len(set(challenges + privates) & set(topics))
        support_overlap = len(set(supports + privates) & set(topics))
        
        # Calculate general match score for sorting
        match_score = calculate_match_score(current_profile, peer_profile)
        
        # Add topic match bonus to score
        topic_bonus = (benefit_overlap + support_overlap) * 10
        final_score = min(100, match_score + topic_bonus)
        
        if final_score >= 80:
            match_label = "Best Fit"
        elif final_score >= 60:
            match_label = "Good Fit"
        elif benefit_overlap > 0 or support_overlap > 0:
            match_label = "Topic Match"
        else:
            match_label = "New Peer"

        user_data = {
            "user_id": row['user_id'],
            "display_name": row['display_name'],
            "match_label": match_label,
            "match_score": final_score,
            "benefit_overlap": benefit_overlap,
            "support_overlap": support_overlap
        }

        # Show ALL users - categorize by topic overlap but include everyone
        # Users with topic overlap appear in their relevant section
        # Users without overlap go to the "benefit" section (general recommendations)
        if benefit_overlap > 0:
            benefit.append(user_data)
        elif support_overlap > 0:
            support.append(user_data)
        else:
            # Include users even without topic overlap (like Find Peers does)
            benefit.append(user_data)
    
    # Sort by match score (best match first)
    benefit.sort(key=lambda x: x['match_score'], reverse=True)
    support.sort(key=lambda x: x['match_score'], reverse=True)

    return render_template(
        "group_invite.html",
        group=meta,
        benefit_candidates=benefit[:20],
        support_candidates=support[:20],
        search_query=search_query,
        username=session.get("username")
    )


@app.route("/groups/<path:group_name>/invite", methods=["POST"])
@login_required
def send_group_invite(group_name):
    """Send an invitation to a user to join the group."""
    group_name = unquote(group_name)
    meta = group_meta.get(group_name)
    if not meta:
        flash("Group not found.", "error")
        return redirect(url_for("groups_page"))
    
    user_id = request.form.get("user_id")
    if not user_id:
        flash("Invalid user.", "error")
        return redirect(url_for("group_invite", group_name=group_name))
    
    try:
        user_id = int(user_id)
    except ValueError:
        flash("Invalid user.", "error")
        return redirect(url_for("group_invite", group_name=group_name))
    
    # Check if user is already in the group
    if user_id in group_members.get(group_name, set()):
        flash("User is already a member of this group.", "info")
        return redirect(url_for("group_invite", group_name=group_name))
    
    # Add invitation
    if user_id not in group_invitations:
        group_invitations[user_id] = []
    
    # Check if already invited
    already_invited = any(inv.get("group_name") == group_name for inv in group_invitations[user_id])
    if already_invited:
        flash("User has already been invited to this group.", "info")
        return redirect(url_for("group_invite", group_name=group_name))
    
    # Add the invitation
    group_invitations[user_id].append({
        "group_name": group_name,
        "inviter_id": session.get("user_id"),
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    
    # Get user name for flash message
    invitee_profile = load_profile_from_db(user_id)
    invitee_name = invitee_profile.get("display_name", "User") if invitee_profile else "User"
    
    flash(f"Invitation sent to {invitee_name}!", "success")
    return redirect(url_for("group_invite", group_name=group_name))


@app.route("/join_group", methods=["POST"])
@login_required
def join_group():
    """Join an existing group."""
    if not session.get("display_name"):
        return redirect(url_for("profile"))

    group_topic = request.form.get("group_topic", "").strip()
    if group_topic in groups or group_topic in group_meta:
        ensure_group_exists(group_topic)
        group_members[group_topic].add(session.get("user_id"))
        session["current_group"] = group_topic
        return redirect(url_for("chat"))

    return redirect(url_for("decision"))


@app.route("/create_group", methods=["POST"])
@login_required
def create_group():
    """Create a new group if no relevant active group exists."""
    if not session.get("display_name"):
        return redirect(url_for("profile"))

    new_topic = request.form.get("new_topic", "").strip()[:40]

    if not new_topic:
        return redirect(url_for("decision"))

    if check_profanity(new_topic):
        return redirect(url_for("decision"))

    relevant = find_relevant_group(new_topic)
    if relevant:
        session["current_group"] = relevant
        return redirect(url_for("chat"))

    ensure_group_exists(new_topic)
    store_group_embedding(new_topic)  # Store embedding for semantic matching
    group_meta[new_topic]["description"] = "A supportive space to connect with peers around this topic."
    group_members[new_topic].add(session.get("user_id"))
    session["current_group"] = new_topic
    return redirect(url_for("chat"))


@app.route("/chat", methods=["GET", "POST"])
@login_required
def chat():
    """Topic room chat with moderation."""
    if not session.get("display_name"):
        return redirect(url_for("profile"))

    current_group = session.get("current_group")
    if not current_group or current_group not in groups:
        return redirect(url_for("decision"))

    warning = None
    distress_banner = False

    if request.method == "POST":
        message_text = request.form.get("message_text", "").strip()
        if message_text:
            moderation = ai_moderate_message(message_text)

            if not moderation["allowed"]:
                warning = moderation["user_message"]
            else:
                # Generate unique message ID
                msg_id = f"{session.get('user_id')}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
                groups[current_group].append({
                    "id": msg_id,
                    "user_id": session.get("user_id"),
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "display_name": session.get("display_name", "Anonymous"),
                    "text": moderation["user_message"]
                })
                if moderation["reason"] == "severe_distress":
                    distress_banner = True

    messages = groups.get(current_group, [])[-50:]

    return render_template(
        "chat.html",
        group_topic=current_group,
        messages=messages,
        warning=warning,
        distress_banner=distress_banner,
        username=session.get("username"),
        current_user_id=session.get("user_id")
    )



@app.route("/api/messages", methods=["GET"])
@login_required
def api_messages():
    """API endpoint for polling chat messages."""
    current_group = session.get("current_group")
    if not current_group or current_group not in groups:
        return jsonify({"messages": [], "error": "No active group"})

    messages = groups.get(current_group, [])[-50:]
    return jsonify({"messages": messages})


def format_human_timestamp(timestamp_str):
    """Convert timestamp to human-readable format."""
    try:
        dt = datetime.strptime(timestamp_str, "%Y-%m-%d %H:%M:%S")
        now = datetime.now()
        diff = now - dt

        if diff.seconds < 60:
            return "Just now"
        elif diff.seconds < 3600:
            mins = diff.seconds // 60
            return f"{mins} min ago"
        elif diff.days == 0:
            return dt.strftime("%I:%M %p")
        elif diff.days == 1:
            return "Yesterday " + dt.strftime("%I:%M %p")
        else:
            return dt.strftime("%b %d, %I:%M %p")
    except Exception:
        return timestamp_str


@app.route("/leave_group", methods=["POST"])
@login_required
def leave_group():
    """Leave current group and add system message."""
    current_group = session.get("current_group")
    display_name = session.get("display_name", "Someone")

    if current_group and current_group in groups:
        groups[current_group].append({
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "display_name": "System",
            "text": f"{display_name} has left the group.",
            "is_system": True
        })

    session["current_group"] = None
    return redirect(url_for("decision"))


@app.route("/api/message/edit", methods=["POST"])
@login_required
def edit_message():
    """Edit a user's own message."""
    data = request.get_json()
    msg_id = data.get("message_id")
    new_text = data.get("text", "").strip()
    
    if not msg_id or not new_text:
        return jsonify({"success": False, "error": "Missing message ID or text"})
    
    current_group = session.get("current_group")
    user_id = session.get("user_id")
    
    if not current_group or current_group not in groups:
        return jsonify({"success": False, "error": "No active group"})
    
    # Find and edit the message
    for msg in groups[current_group]:
        if msg.get("id") == msg_id and msg.get("user_id") == user_id:
            # Moderate the new text
            moderation = ai_moderate_message(new_text)
            if not moderation["allowed"]:
                return jsonify({"success": False, "error": moderation["user_message"]})
            
            msg["text"] = moderation["user_message"]
            msg["edited"] = True
            return jsonify({"success": True, "text": msg["text"]})
    
    return jsonify({"success": False, "error": "Message not found or not authorized"})


@app.route("/api/message/delete", methods=["POST"])
@login_required
def delete_message():
    """Delete a user's own message."""
    data = request.get_json()
    msg_id = data.get("message_id")
    
    if not msg_id:
        return jsonify({"success": False, "error": "Missing message ID"})
    
    current_group = session.get("current_group")
    user_id = session.get("user_id")
    
    if not current_group or current_group not in groups:
        return jsonify({"success": False, "error": "No active group"})
    
    # Find and delete the message
    for i, msg in enumerate(groups[current_group]):
        if msg.get("id") == msg_id and msg.get("user_id") == user_id:
            groups[current_group].pop(i)
            return jsonify({"success": True})
    
    return jsonify({"success": False, "error": "Message not found or not authorized"})


# -----------------------------------------------------------------------------
# Peer Connection Routes
# -----------------------------------------------------------------------------

def get_profile_summary(profile_dict):
    """Generate a short profile summary for display."""
    parts = []
    
    gender = profile_dict.get("gender", "")
    if gender and gender != "prefer-not-to-say":
        parts.append(gender.title())
    
    challenges = normalize_topic_ids(profile_dict.get("primary_challenge", []))
    support_topics = normalize_topic_ids(profile_dict.get("support_topics", []))
    private_topics = set(normalize_topic_ids(profile_dict.get("private_topics", [])))
    public_topics = [t for t in (challenges + support_topics) if t not in private_topics]
    if public_topics:
        parts.append(f"Facing: {', '.join(get_topic_labels(public_topics[:2]))}")
    
    language = profile_dict.get("preferred_language")
    if language:
        parts.append(f"Speaks: {language}")
    
    return " | ".join(parts) if parts else "ASU Student"


def cache_user_profile(user_id, display_name, profile_dict):
    """Cache user profile for peer display."""
    user_profiles[user_id] = {
        "display_name": display_name,
        "profile_summary": get_profile_summary(profile_dict),
        "gender": profile_dict.get("gender", ""),
        "preferred_language": profile_dict.get("preferred_language", ""),
        "support_topics": profile_dict.get("support_topics", []),
        "private_topics": profile_dict.get("private_topics", []),
        "languages": profile_dict.get("languages", []),
        "cultural_background": profile_dict.get("cultural_background", []),
        "support_style": profile_dict.get("support_style", "mixed"),
    }


def get_pending_requests_for_user(user_id):
    """Get all pending connection requests for a user."""
    return pending_requests.get(user_id, [])


def calculate_match_score(current_profile, peer_profile):
    """Calculate a simple match score between two profiles."""
    current_topics = normalize_topic_ids(
        (current_profile.get("primary_challenge", []) or [])
        + (current_profile.get("support_topics", []) or [])
        + (current_profile.get("private_topics", []) or [])
    )
    peer_topics = normalize_topic_ids(
        (peer_profile.get("support_topics", []) or [])
        + (peer_profile.get("primary_challenge", []) or [])
        + (peer_profile.get("private_topics", []) or [])
    )

    topic_overlap = len(set(current_topics) & set(peer_topics))
    topic_union = len(set(current_topics) | set(peer_topics))
    topic_score = (topic_overlap / topic_union) if topic_union else 0.0

    lang_score = 0.0
    current_langs = set(current_profile.get("languages", []) or [])
    peer_langs = set(peer_profile.get("languages", []) or [])
    if current_profile.get("preferred_language"):
        current_langs.add(current_profile.get("preferred_language"))
    if peer_profile.get("preferred_language"):
        peer_langs.add(peer_profile.get("preferred_language"))
    if current_langs & peer_langs:
        lang_score = 1.0

    culture_score = 0.0
    current_cultures = set(current_profile.get("cultural_background", []) or [])
    peer_cultures = set(peer_profile.get("cultural_background", []) or [])
    if current_cultures & peer_cultures:
        culture_score = 1.0

    # Gender matching (optional - only if both specify)
    gender_score = 0.0
    current_gender = current_profile.get("gender", "")
    peer_gender = peer_profile.get("gender", "")
    if current_gender and peer_gender and current_gender == peer_gender and current_gender != "prefer-not-to-say":
        gender_score = 1.0
    
    # Graduation year matching (within 1 year counts as match)
    grad_year_score = 0.0
    current_grad = current_profile.get("graduation_year", "")
    peer_grad = peer_profile.get("graduation_year", "")
    if current_grad and peer_grad:
        try:
            current_year = int(current_grad.replace("+", "")[:4])  # Handle "2030+"
            peer_year = int(peer_grad.replace("+", "")[:4])
            if abs(current_year - peer_year) <= 1:
                grad_year_score = 1.0
        except:
            pass
    
    # Degree program matching
    degree_score = 0.0
    current_degree = current_profile.get("degree_program", "")
    peer_degree = peer_profile.get("degree_program", "")
    if current_degree and peer_degree and current_degree == peer_degree:
        degree_score = 1.0

    score = (topic_score * 60) + (lang_score * 10) + (culture_score * 10) + (gender_score * 10) + (grad_year_score * 5) + (degree_score * 5)
    return int(round(score))


def calculate_group_match_score(user_profile, group_meta_dict, last_issue_text=None):
    """
    Calculate how well a group matches a user's profile.
    Returns a score from 0-100.
    """
    score = 0.0
    
    # Get user's topics (all types combined)
    user_topics = normalize_topic_ids(
        (user_profile.get("primary_challenge", []) or [])
        + (user_profile.get("support_topics", []) or [])
        + (user_profile.get("private_topics", []) or [])
    )
    
    # Get group's topics
    group_topics = normalize_topic_ids(group_meta_dict.get("topics", []) or [])
    
    # Topic overlap score (up to 50 points)
    if user_topics and group_topics:
        overlap = len(set(user_topics) & set(group_topics))
        max_possible = min(len(user_topics), len(group_topics))
        if max_possible > 0:
            score += (overlap / max_possible) * 50
    
    # Group name/description keyword matching against user profile (up to 30 points)
    group_text = (group_meta_dict.get("name", "") + " " + group_meta_dict.get("description", "")).lower()
    user_topic_labels = [get_topic_label(t).lower() for t in user_topics if get_topic_label(t)]
    
    keyword_matches = 0
    for label in user_topic_labels:
        # Check if any word from the label appears in group text
        label_words = label.split()
        for word in label_words:
            if len(word) > 3 and word in group_text:
                keyword_matches += 1
                break
    
    if user_topic_labels:
        score += (min(keyword_matches, 3) / 3) * 30
    
    # Issue text matching (up to 20 points) if available
    if last_issue_text:
        issue_lower = last_issue_text.lower()
        # Check if group name keywords appear in issue
        group_name_words = group_meta_dict.get("name", "").lower().split()
        name_matches = sum(1 for w in group_name_words if len(w) > 3 and w in issue_lower)
        if group_name_words:
            score += (min(name_matches, 2) / 2) * 20
    else:
        # If no issue text, give partial points based on profile completeness
        if user_topics:
            score += 10
    
    return int(round(min(score, 100)))

def add_connection_request(sender_id, sender_display_name, recipient_id, message):
    """Add a connection request to pending requests and track outgoing."""
    if recipient_id not in pending_requests:
        pending_requests[recipient_id] = []
    
    # Check if request already exists
    for req in pending_requests[recipient_id]:
        if req["sender_id"] == sender_id:
            return False  # Already sent
    
    # Get recipient display name for outgoing tracking
    recipient_display_name = "User"
    if recipient_id in user_profiles:
        recipient_display_name = user_profiles[recipient_id].get("display_name", "User")
    else:
        db = get_db()
        row = db.execute('SELECT display_name FROM profiles WHERE user_id = ?', (recipient_id,)).fetchone()
        if row and row['display_name']:
            recipient_display_name = row['display_name']
    
    pending_requests[recipient_id].append({
        "sender_id": sender_id,
        "sender_display_name": sender_display_name,
        "message": message,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    
    # Track outgoing request for sender
    if sender_id not in outgoing_requests:
        outgoing_requests[sender_id] = []
    outgoing_requests[sender_id].append({
        "recipient_id": recipient_id,
        "recipient_display_name": recipient_display_name,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    })
    
    return True


def remove_connection_request(recipient_id, sender_id):
    """Remove a connection request."""
    if recipient_id in pending_requests:
        pending_requests[recipient_id] = [
            req for req in pending_requests[recipient_id]
            if req["sender_id"] != sender_id
        ]


@app.route("/people", methods=["GET"])
@login_required
def people():
    """Show recommended peers based on semantic matching."""
    if not session.get("display_name"):
        return redirect(url_for("onboarding"))
    
    user_id = session.get("user_id")
    search_query = request.args.get("q", "").strip().lower()
    selected_topics = request.args.getlist("topics")
    sort_by = request.args.get("sort", "best")
    filter_challenge = request.args.get("filter", "")
    selected_topics = normalize_topic_ids(selected_topics)
    
    current_profile = load_profile_from_db(user_id) if user_id else None
    if not current_profile:
        current_profile = get_profile_dict()
    
    # Get all profiles from database
    db = get_db()
    all_profiles = db.execute('''
        SELECT p.*, u.username FROM profiles p 
        JOIN users u ON p.user_id = u.id 
        WHERE p.user_id != ? AND p.display_name IS NOT NULL AND p.display_name != ''
    ''', (user_id,)).fetchall()
    
    peers = []
    for row in all_profiles:
        challenges = normalize_topic_ids((row['primary_challenge'] or '').split(','))
        support_topics = normalize_topic_ids((row['support_topics'] or '').split(','))
        private_topics = set(normalize_topic_ids((row['private_topics'] or '').split(',')))
        peer_topics = list(dict.fromkeys(challenges + support_topics))
        public_topics = [t for t in peer_topics if t not in private_topics]

        peer_profile = {
            "display_name": row['display_name'] or 'Anonymous',
            "gender": row['gender'] if 'gender' in row.keys() else '',
            "preferred_language": row['preferred_language'] or '',
            "primary_challenge": challenges,
            "support_topics": support_topics,
            "private_topics": list(private_topics),
            "languages": (row['languages'] or '').split(',') if row['languages'] else [],
            "cultural_background": (row['cultural_background'] or '').split(',') if row['cultural_background'] else [],
            "support_style": row['support_style'] or 'mixed'
        }

        # Apply topic filter if specified
        if selected_topics:
            if not set(selected_topics) & set(peer_topics):
                continue

        # Backward-compatible filter pills
        if filter_challenge:
            filter_lower = filter_challenge.lower()
            all_challenges_lower = ",".join(peer_topics).lower()
            if filter_lower not in all_challenges_lower:
                if filter_lower == 'homesickness' and 'homesickness' not in all_challenges_lower:
                    continue
                elif filter_lower == 'academic' and 'academic' not in all_challenges_lower:
                    continue
                elif filter_lower == 'social' and 'loneliness' not in all_challenges_lower and 'relationship' not in all_challenges_lower:
                    continue
                elif filter_lower == 'cultural' and 'culture' not in all_challenges_lower:
                    continue
                elif filter_lower == 'language' and 'language' not in all_challenges_lower:
                    continue

        # Apply search query
        if search_query:
            searchable = " ".join([
                row['display_name'] or '',
                row['preferred_language'] or '',
                ",".join(peer_topics),
            ]).lower()
            if search_query not in searchable:
                continue

        match_score = calculate_match_score(current_profile, peer_profile)
        if match_score >= 80:
            match_label = "Best Fit"
        elif match_score >= 60:
            match_label = "Good Fit"
        else:
            match_label = "New Peer"

        peers.append({
            "user_id": row['user_id'],
            "display_name": row['display_name'] or 'Anonymous',
            "gender": row['gender'] if 'gender' in row.keys() else '',
            "preferred_language": row['preferred_language'] or '',
            "primary_challenge": ",".join(peer_topics),
            "public_topics": public_topics,
            "support_style": row['support_style'] or 'mixed',
            "languages": peer_profile.get("languages", []),
            "match_score": match_score,
            "match_label": match_label
        })
    
    # Also add from in-memory cache for real-time peers
    if user_id:
        similar = get_similar_users(user_id, top_n=10, threshold=0.2)
        for peer_id, score in similar:
            peer_profile = user_profiles.get(peer_id)
            if peer_profile and not any(p['user_id'] == peer_id for p in peers):
                match_score = int(round(score * 100))
                if match_score >= 80:
                    match_label = "Best Fit"
                elif match_score >= 60:
                    match_label = "Good Fit"
                else:
                    match_label = "New Peer"
                peers.append({
                    "user_id": peer_id,
                    "display_name": peer_profile.get("display_name", "Anonymous"),
                    "gender": peer_profile.get("gender", ""),
                    "preferred_language": peer_profile.get("preferred_language", ""),
                    "primary_challenge": ",".join(peer_profile.get("support_topics", [])),
                    "public_topics": [t for t in peer_profile.get("support_topics", []) if t not in peer_profile.get("private_topics", [])],
                    "support_style": peer_profile.get("support_style", "mixed"),
                    "languages": peer_profile.get("languages", []),
                    "match_score": match_score,
                    "match_label": match_label
                })
    
    # Get pending requests for current user
    incoming_requests = get_pending_requests_for_user(user_id)
    
    if sort_by == "alpha":
        peers.sort(key=lambda p: p.get("display_name", ""))
    elif sort_by == "recent":
        peers.sort(key=lambda p: p.get("user_id", 0), reverse=True)
    else:
        peers.sort(key=lambda p: p.get("match_score", 0), reverse=True)

    recommended_peers = peers[:3]

    return render_template(
        "people.html",
        peers=peers,
        recommended_peers=recommended_peers,
        filter=filter_challenge,
        incoming_requests=incoming_requests,
        username=session.get("username"),
        support_topic_categories=SUPPORT_TOPIC_CATEGORIES,
        support_topic_index=SUPPORT_TOPIC_INDEX,
        selected_topics=selected_topics,
        search_query=search_query,
        sort_by=sort_by
    )


@app.route("/connect", methods=["POST"])
@login_required
def connect():
    """Send a connection request to another user."""
    if not session.get("display_name"):
        return jsonify({"success": False, "error": "Profile required"}), 400
    
    sender_id = session.get("user_id")
    sender_display_name = session.get("display_name")
    recipient_id = request.form.get("recipient_id")
    message = request.form.get("message", "").strip()[:200]
    
    if not recipient_id:
        return jsonify({"success": False, "error": "Recipient required"}), 400
    
    try:
        recipient_id = int(recipient_id)
    except ValueError:
        return jsonify({"success": False, "error": "Invalid recipient"}), 400
    
    if sender_id == recipient_id:
        return jsonify({"success": False, "error": "Cannot connect with yourself"}), 400
    
    # Moderate message if provided
    distress_detected = False
    if message:
        moderation = ai_moderate_message(message)
        if not moderation["allowed"]:
            return jsonify({
                "success": False,
                "error": moderation["user_message"]
            }), 400
        if moderation["reason"] == "severe_distress":
            distress_detected = True
    
    # Add the request
    success = add_connection_request(sender_id, sender_display_name, recipient_id, message)
    
    if success:
        return jsonify({
            "success": True,
            "message": "Connection request sent",
            "distress_detected": distress_detected
        })
    else:
        return jsonify({
            "success": False,
            "error": "Request already sent"
        }), 400


@app.route("/connect/accept", methods=["POST"])
@login_required
def connect_accept():
    """Accept a connection request."""
    user_id = session.get("user_id")
    sender_id = request.form.get("sender_id")
    action = request.form.get("action", "group")  # "group" or "message"
    
    if not sender_id:
        flash("Sender required", "error")
        return redirect(url_for("people"))
    
    try:
        sender_id = int(sender_id)
    except ValueError:
        flash("Invalid sender", "error")
        return redirect(url_for("people"))
    
    # Find the request
    requests_list = get_pending_requests_for_user(user_id)
    request_found = None
    for req in requests_list:
        if req["sender_id"] == sender_id:
            request_found = req
            break
    
    if not request_found:
        flash("Request not found", "error")
        return redirect(url_for("people"))
    
    # Remove the request
    remove_connection_request(user_id, sender_id)
    
    flash(f"Connection with {request_found['sender_display_name']} accepted!", "success")
    return redirect(url_for("people"))


@app.route("/connect/ignore", methods=["POST"])
@login_required
def connect_ignore():
    """Ignore/remove a connection request."""
    user_id = session.get("user_id")
    sender_id = request.form.get("sender_id")
    
    if not sender_id:
        flash("Sender required", "error")
        return redirect(url_for("people"))
    
    try:
        sender_id = int(sender_id)
    except ValueError:
        flash("Invalid sender", "error")
        return redirect(url_for("people"))
    
    remove_connection_request(user_id, sender_id)
    
    flash("Request removed", "info")
    return redirect(url_for("people"))


# -----------------------------------------------------------------------------
# Peers Page Routes
# -----------------------------------------------------------------------------

def get_connected_peers(user_id):
    """Get list of connected peers for a user."""
    connected_ids = peer_connections.get(user_id, set())
    peers = []
    for peer_id in connected_ids:
        peer_profile = user_profiles.get(peer_id)
        if peer_profile:
            peers.append({
                "user_id": peer_id,
                "display_name": peer_profile.get("display_name", "Anonymous"),
                "match_reason": peer_profile.get("profile_summary", "")
            })
        else:
            # Try to load from DB
            db = get_db()
            row = db.execute('SELECT display_name FROM profiles WHERE user_id = ?', (peer_id,)).fetchone()
            if row:
                peers.append({
                    "user_id": peer_id,
                    "display_name": row['display_name'] or "Anonymous",
                    "match_reason": ""
                })
    return peers

def get_outgoing_requests(user_id):
    """Get list of outgoing connection requests for a user."""
    return outgoing_requests.get(user_id, [])

def add_peer_connection(user_a_id, user_b_id):
    """Add a mutual peer connection."""
    if user_a_id not in peer_connections:
        peer_connections[user_a_id] = set()
    if user_b_id not in peer_connections:
        peer_connections[user_b_id] = set()
    peer_connections[user_a_id].add(user_b_id)
    peer_connections[user_b_id].add(user_a_id)

def remove_outgoing_request(sender_id, recipient_id):
    """Remove an outgoing connection request."""
    if sender_id in outgoing_requests:
        outgoing_requests[sender_id] = [
            req for req in outgoing_requests[sender_id]
            if req["recipient_id"] != recipient_id
        ]


@app.route("/peers", methods=["GET"])
@login_required
def peers_page():
    """Peers page showing connected peers, pending requests, and suggestions."""
    if not session.get("display_name"):
        return redirect(url_for("profile"))
    
    user_id = session.get("user_id")
    
    # Get connected peers
    connected_peers = get_connected_peers(user_id)
    
    # Get incoming requests
    incoming_requests = get_pending_requests_for_user(user_id)
    
    # Get outgoing requests
    outgoing_reqs = get_outgoing_requests(user_id)
    
    # Get suggested peers using semantic matching
    suggested_peers = []
    if user_id:
        similar = get_similar_users(user_id, top_n=6, threshold=0.3)
        connected_ids = peer_connections.get(user_id, set())
        for peer_id, score in similar:
            # Skip already connected peers
            if peer_id in connected_ids:
                continue
            # Skip peers with pending requests
            has_pending = any(req["sender_id"] == peer_id for req in incoming_requests)
            if has_pending:
                continue
            has_outgoing = any(req["recipient_id"] == peer_id for req in outgoing_reqs)
            if has_outgoing:
                continue
            
            peer_profile = user_profiles.get(peer_id)
            if peer_profile:
                current_profile = load_profile_from_db(user_id)
                common_topics = []
                if current_profile and peer_profile:
                    my_topics = set(normalize_topic_ids(current_profile.get("support_topics", [])))
                    peer_topics_list = normalize_topic_ids(peer_profile.get("support_topics", []))
                    common = my_topics & set(peer_topics_list)
                    common_topics = get_topic_labels(list(common)[:3])
                
                suggested_peers.append({
                    "user_id": peer_id,
                    "display_name": peer_profile.get("display_name", "Anonymous"),
                    "match_score": score,
                    "common_topics": common_topics
                })
    
    return render_template(
        "peers.html",
        connected_peers=connected_peers,
        incoming_requests=incoming_requests,
        outgoing_requests=outgoing_reqs,
        suggested_peers=suggested_peers[:5],
        username=session.get("username")
    )


@app.route("/peers/accept", methods=["POST"])
@login_required
def accept_connection():
    """Accept a peer connection request."""
    user_id = session.get("user_id")
    sender_id = request.form.get("sender_id")
    
    if not sender_id:
        flash("Sender required", "error")
        return redirect(url_for("peers_page"))
    
    try:
        sender_id = int(sender_id)
    except ValueError:
        flash("Invalid sender", "error")
        return redirect(url_for("peers_page"))
    
    # Find the request
    requests_list = get_pending_requests_for_user(user_id)
    request_found = None
    for req in requests_list:
        if req["sender_id"] == sender_id:
            request_found = req
            break
    
    if not request_found:
        flash("Request not found", "error")
        return redirect(url_for("peers_page"))
    
    # Create the connection
    add_peer_connection(user_id, sender_id)
    
    # Remove the pending request
    remove_connection_request(user_id, sender_id)
    
    # Remove from sender's outgoing requests
    remove_outgoing_request(sender_id, user_id)
    
    flash(f"Connected with {request_found['sender_display_name']}!", "success")
    return redirect(url_for("peers_page"))


@app.route("/peers/decline", methods=["POST"])
@login_required
def decline_connection():
    """Decline a peer connection request."""
    user_id = session.get("user_id")
    sender_id = request.form.get("sender_id")
    
    if not sender_id:
        flash("Sender required", "error")
        return redirect(url_for("peers_page"))
    
    try:
        sender_id = int(sender_id)
    except ValueError:
        flash("Invalid sender", "error")
        return redirect(url_for("peers_page"))
    
    # Remove the request
    remove_connection_request(user_id, sender_id)
    
    # Remove from sender's outgoing requests
    remove_outgoing_request(sender_id, user_id)
    
    flash("Request declined", "info")
    return redirect(url_for("peers_page"))


@app.route("/peers/cancel", methods=["POST"])
@login_required
def cancel_connection():
    """Cancel an outgoing connection request."""
    user_id = session.get("user_id")
    recipient_id = request.form.get("recipient_id")
    
    if not recipient_id:
        flash("Recipient required", "error")
        return redirect(url_for("peers_page"))
    
    try:
        recipient_id = int(recipient_id)
    except ValueError:
        flash("Invalid recipient", "error")
        return redirect(url_for("peers_page"))
    
    # Remove from outgoing requests
    remove_outgoing_request(user_id, recipient_id)
    
    # Remove from recipient's pending requests
    remove_connection_request(recipient_id, user_id)
    
    flash("Request cancelled", "info")
    return redirect(url_for("peers_page"))


@app.route("/my-groups", methods=["GET"])
@login_required
def my_groups_page():
    """My Groups page - shows joined groups, invitations, and join requests."""
    user_id = session.get("user_id")
    
    # Get joined groups
    joined_groups = []
    for group_name, members in group_members.items():
        if user_id in members:
            group_info = group_meta.get(group_name, {})
            join_date = group_member_dates.get(group_name, {}).get(user_id, "")
            
            # Format join date
            if join_date:
                try:
                    dt = datetime.strptime(join_date, "%Y-%m-%d %H:%M:%S")
                    days_ago = (datetime.now() - dt).days
                    if days_ago == 0:
                        joined_at = "today"
                    elif days_ago == 1:
                        joined_at = "yesterday"
                    elif days_ago < 7:
                        joined_at = f"{days_ago} days ago"
                    elif days_ago < 30:
                        joined_at = f"{days_ago // 7} weeks ago"
                    else:
                        joined_at = dt.strftime("%b %d, %Y")
                except:
                    joined_at = ""
            else:
                joined_at = ""
            
            joined_groups.append({
                "name": group_name,
                "member_count": len(members),
                "group_type": group_info.get("group_type", "Peer Support"),
                "joined_at": joined_at
            })
    
    # Get group join requests (for groups you own)
    group_join_requests = []
    for group_name, requesters in group_requests.items():
        group_info = group_meta.get(group_name, {})
        if group_info.get("owner_id") == user_id:
            for requester_id in requesters:
                requester_profile = load_profile_from_db(requester_id)
                if requester_profile:
                    group_join_requests.append({
                        "user_id": requester_id,
                        "group_name": group_name,
                        "display_name": requester_profile.get("display_name", "Anonymous")
                    })
    
    # Get pending group invitations
    pending_invitations = []
    user_invitations = group_invitations.get(user_id, [])
    for invitation in user_invitations:
        group_name = invitation.get("group_name")
        if group_name and group_name in group_meta:
            # Skip if already joined
            if user_id in group_members.get(group_name, set()):
                continue
            
            group_info = group_meta.get(group_name, {})
            invited_time = invitation.get("timestamp", "")
            
            # Format invite date
            if invited_time:
                try:
                    dt = datetime.strptime(invited_time, "%Y-%m-%d %H:%M:%S")
                    days_ago = (datetime.now() - dt).days
                    if days_ago == 0:
                        invited_at = "today"
                    elif days_ago == 1:
                        invited_at = "yesterday"
                    elif days_ago < 7:
                        invited_at =f"{days_ago}d ago"
                    else:
                        invited_at = dt.strftime("%b %d")
                except:
                    invited_at = ""
            else:
                invited_at = ""
            
            pending_invitations.append({
                "group_name": group_name,
                "description": group_info.get("description", ""),
                "invited_at": invited_at
            })
    
    return render_template(
        "my_groups.html",
        joined_groups=joined_groups,
        group_join_requests=group_join_requests,
        pending_invitations=pending_invitations,
        username=session.get("username")
    )


@app.route("/groups/<path:group_name>/requests/decline", methods=["POST"])
@login_required
def group_request_decline(group_name):
    """Decline a group join request."""
    group_name = unquote(group_name)
    user_id = session.get("user_id")
    requester_id = request.form.get("requester_id")
    
    if not requester_id:
        flash("Invalid request", "error")
        return redirect(url_for("my_groups_page"))
    
    try:
        requester_id = int(requester_id)
    except ValueError:
        flash("Invalid request", "error")
        return redirect(url_for("my_groups_page"))
    
    # Check if user owns the group
    group_info = group_meta.get(group_name, {})
    if group_info.get("owner_id") != user_id:
        flash("You don't have permission to decline this request", "error")
        return redirect(url_for("my_groups_page"))
    
    # Remove from requests
    if group_name in group_requests:
        group_requests[group_name].discard(requester_id)
    
    flash("Request declined", "info")
    return redirect(url_for("my_groups_page"))


@app.route("/groups/invitation/decline", methods=["POST"])
@login_required
def decline_group_invitation():
    """Decline a group invitation."""
    user_id = session.get("user_id")
    group_name = request.form.get("group_name", "").strip()
    
    if not group_name:
        flash("Invalid invitation", "error")
        return redirect(url_for("my_groups_page"))
    
    # Remove invitation
    if user_id in group_invitations:
        group_invitations[user_id] = [
            inv for inv in group_invitations[user_id]
            if inv.get("group_name") != group_name
        ]
    
    flash("Invitation declined", "info")
    return redirect(url_for("my_groups_page"))



# -----------------------------------------------------------------------------
# Run Application
# -----------------------------------------------------------------------------

if __name__ == "__main__":
    init_db()
    init_group_embeddings()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=True)
