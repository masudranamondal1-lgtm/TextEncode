import streamlit as st

THEMES = {
    "Classic Light": {
        "bg": "#F7F6F2", "surface": "#FFFFFF", "text": "#24272A", 
        "text_muted": "#777A7D", "accent": "#244C56", "border": "#E5E2DB",
        "nav_bg": "#FFFFFF", "nav_text": "#24272A", "highlight": "#E8DCC4"
    },
    "Dark Research": {
        "bg": "#17191B", "surface": "#202326", "text": "#E8E5DE", 
        "text_muted": "#A5A7A6", "accent": "#78A5AA", "border": "#373B3D",
        "nav_bg": "#202326", "nav_text": "#E8E5DE", "highlight": "#3A4A4C"
    },
    "Eye Comfort": {
        "bg": "#EDE6D8", "surface": "#F5F0E5", "text": "#39352F", 
        "text_muted": "#777064", "accent": "#52645B", "border": "#D8CEBD",
        "nav_bg": "#F5F0E5", "nav_text": "#39352F", "highlight": "#D4C7B0"
    },
    "High Contrast": {
        "bg": "#FFFFFF", "surface": "#F8F9FA", "text": "#000000", 
        "text_muted": "#333333", "accent": "#0000CC", "border": "#000000",
        "nav_bg": "#F8F9FA", "nav_text": "#000000", "highlight": "#FFFF00"
    }
}

def apply_theme(mode_name: str):
    c = THEMES.get(mode_name, THEMES["Classic Light"])
    
    # Streamlit base config
    st._config.set_option("theme.base", "dark" if mode_name == "Dark Research" else "light")
    st._config.set_option("theme.primaryColor", c["accent"])
    st._config.set_option("theme.backgroundColor", c["bg"])
    st._config.set_option("theme.secondaryBackgroundColor", c["surface"])
    st._config.set_option("theme.textColor", c["text"])

    css = f"""
    <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Source+Serif+4:opsz,wght@8..60,400;8..60,600&family=Noto+Serif+Bengali:wght@400;600&family=IBM+Plex+Mono&display=swap');
        
        :root {{
            --bg: {c['bg']};
            --surface: {c['surface']};
            --text: {c['text']};
            --text-muted: {c['text_muted']};
            --accent: {c['accent']};
            --border: {c['border']};
            --nav-bg: {c['nav_bg']};
            --nav-text: {c['nav_text']};
            --highlight: {c['highlight']};
        }}

        /* Global Overrides */
        html, body, [class*="css"] {{
            font-family: 'Inter', 'Noto Sans Bengali', sans-serif;
            background-color: var(--bg) !important;
            color: var(--text) !important;
        }}
        
        h1, h2, h3, h4 {{
            font-family: 'Source Serif 4', 'Noto Serif Bengali', serif !important;
            color: var(--text) !important;
            font-weight: 600 !important;
        }}

        /* Sidebar */
        [data-testid="stSidebar"] {{
            background-color: var(--nav-bg) !important;
            border-right: 1px solid var(--border) !important;
        }}
        [data-testid="stSidebarNav"]::before {{
            content: "📖 TextEncode";
            margin-left: 20px; margin-top: 20px;
            font-size: 1.2rem; font-family: 'Source Serif 4', serif;
            font-weight: 600; color: var(--accent);
            display: block; margin-bottom: 20px;
        }}
        [data-testid="stSidebarNav"] a {{
            color: var(--nav-text) !important;
        }}
        
        /* Buttons */
        .stButton > button {{
            background-color: var(--accent) !important;
            color: var(--surface) !important;
            border: none !important; border-radius: 4px !important;
            font-weight: 500 !important; transition: all 0.2s ease;
        }}
        .stButton > button:hover {{
            opacity: 0.9 !important;
        }}
        
        /* Inputs */
        .stTextInput > div > div > input, .stSelectbox > div > div > div, .stTextArea > div > div > textarea {{
            background-color: var(--surface) !important;
            border: 1px solid var(--border) !important;
            color: var(--text) !important;
        }}
        
        /* Tables */
        .stDataFrame {{
            border: 1px solid var(--border) !important;
            border-radius: 8px; background-color: var(--surface) !important;
        }}
        .stDataFrame th {{
            background-color: var(--bg) !important;
            color: var(--text-muted) !important;
            font-family: 'Inter', sans-serif !important;
            text-transform: uppercase; font-size: 0.8rem;
        }}
        
        /* Reader Container */
        .reader-container {{
            background-color: var(--surface);
            padding: 40px;
            border-radius: 6px;
            border: 1px solid var(--border);
            font-family: 'Source Serif 4', 'Noto Serif Bengali', serif;
            font-size: {st.session_state.get('reading_font_size', 1.15)}rem;
            line-height: {st.session_state.get('reading_line_height', 1.8)};
            max-width: {st.session_state.get('reading_width', 800)}px;
            margin: 0 auto;
            color: var(--text);
        }}
        
        mark {{
            background-color: var(--highlight);
            color: var(--text);
            padding: 0 4px; border-radius: 3px;
            font-weight: 500;
        }}
        
        /* Metric Cards */
        .metric-container {{
            background: var(--surface);
            padding: 20px; border-radius: 6px;
            border: 1px solid var(--border);
        }}
        .metric-label {{
            color: var(--text-muted); font-size: 0.85rem;
            text-transform: uppercase; letter-spacing: 0.05em;
            margin-bottom: 5px;
        }}
        .metric-value {{
            font-family: 'Source Serif 4', serif;
            font-size: 2.2rem; color: var(--text); font-weight: 600;
        }}
        
        /* Hide Streamlit Branding */
        #MainMenu {{visibility: hidden;}}
        footer {{visibility: hidden;}}
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)
